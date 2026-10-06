"""Route-optimizer voor drafts."""
import copy
import os
from concurrent.futures import ThreadPoolExecutor
from contextvars import copy_context
from functools import partial
from itertools import islice
import inspect
import time

from . import climbs as climbs_mod
from . import geo, gh, profiles
from .errors import DraftError

FLAT = "vlak"
_LEGACY_HM = "__legacy_hm__"
_LOAD_HEAT = object()

def _draft():
    from . import draft

    return draft


def _route_share(routes: list[dict], detail_name: str, wanted: set) -> float:
    """Aandeel meters met een GH-detail over meerdere routedelen."""
    from . import analysis

    matched = total = 0.0
    for routed in routes:
        coords = [(point[0], point[1]) for point in routed.get("coords", [])]
        total += routed.get("distance_m", geo.path_length(coords))
        matched += analysis.detail_meters(
            coords,
            routed.get("details", {}).get(detail_name, []),
            wanted,
        )
    return min(1.0, matched / max(total, 1.0))


def _unpaved_m(routes: list[dict]) -> float:
    """Onverharde meters uit GH-details; bekende verharde paden tellen niet mee."""
    from . import analysis

    total = 0.0
    unpaved = {"gravel", "dirt", "grass", "sand", "ground", "unpaved", "compacted", "fine_gravel"}
    for routed in routes:
        if "onverhard_m" in routed:
            total += routed["onverhard_m"]
            continue
        coords = routed.get("coords", [])
        details = routed.get("details") or {}
        surfaces = analysis._detail_values(coords, details.get("surface", []))
        roads = analysis._detail_values(coords, details.get("road_class", []))
        for i, surface in enumerate(surfaces):
            if surface in unpaved or (surface in {None, "missing", "unknown"} and roads[i] in analysis.OFFROAD_CLASSES):
                total += geo.haversine(*coords[i][:2], *coords[i + 1][:2])
    return total


def _paved_candidates(candidates, share):
    """Vermijd >5% onverhard als een verharde variant beschikbaar is."""
    paved = [candidate for candidate in candidates if share(candidate) <= 0.05]
    return paved or candidates


def _popular_share(routes: list[dict], cells=_LOAD_HEAT, *, profile="quiet") -> float:
    if cells is _LOAD_HEAT:
        from . import heat

        cells = heat.popular_cells(profile)
    if not cells:
        return 0.0
    points = []
    for routed in routes:
        coords = [(point[0], point[1]) for point in routed.get("coords", [])]
        if coords:
            points.extend(geo.resample(coords, 60.0))
    hits = sum(1 for point in points if geo.cell(*point) in cells)
    return hits / max(len(points), 1)


def _quiet_share(routes: list[dict], busy_cells=_LOAD_HEAT) -> float:
    """Aandeel routepunten buiten drukke TVL-cellen, of nul zonder drukdata."""
    if busy_cells is _LOAD_HEAT:
        from . import heat

        source = heat.vlaanderen_data()
        if source["version"] >= 3:
            # Niet gemarkeerd is onbekend, geen bewezen autovrije weg.
            return 0.0
        busy_cells = source["druk"]
    if not busy_cells:
        return 0.0
    points = []
    for routed in routes:
        coords = [(point[0], point[1]) for point in routed.get("coords", [])]
        if coords:
            points.extend(geo.resample(coords, 60.0))
    if not points:
        return 0.0
    busy = sum(1 for point in points if geo.cell(*point) in busy_cells)
    return 1.0 - busy / len(points)


def _candidate_surface_components(
    routes: list[dict],
    popular_cells=_LOAD_HEAT,
    busy_cells=_LOAD_HEAT,
    *, profile="quiet",
) -> dict:
    from . import analysis, route_evidence

    result = {
        "offroad": _route_share(routes, "road_class", analysis.OFFROAD_CLASSES),
        "populair": _popular_share(routes, popular_cells, profile=profile),
        "autovrij": _quiet_share(routes, busy_cells),
        "kassei": _route_share(routes, "surface", analysis.COBBLE_SURFACES),
    }
    if popular_cells is _LOAD_HEAT or busy_cells is _LOAD_HEAT:
        evidence = route_evidence.route_stats([r.get("coords", []) for r in routes], profile)
        if evidence is not None:
            if popular_cells is _LOAD_HEAT:
                result["populair"] = evidence["curatie_score"]
            if busy_cells is _LOAD_HEAT:
                result["autovrij"] = evidence["bevestigd_autovrij_pct"] / 100
    return result


def _candidate_prefilter(d: dict, climb_db: dict, max_detour_km: float,
                         banned=frozenset()) -> list[tuple]:
    """Goedkope suggest-prefilter zonder routercalls."""
    if not d.get("computed") or not d.get("_geometry"):
        raise DraftError("routeer eerst: `lus draft route <id>`")

    legs_geo = d["_geometry"]
    legs_meta = d["computed"]["legs"]

    candidates = []
    for cid, c in climb_db.items():
        if cid in d["climbs"] or cid in banned:
            continue
        foot = tuple(c["foot"])
        top = tuple(c["top"])
        ests = []
        for i, (meta, coords) in enumerate(zip(legs_meta, legs_geo)):
            if meta.get("climb") or meta.get("climb_segment") or meta.get("opvulling"):
                continue  # geen klimsegment of vervangbare rondrit als omweg schatten
            a = tuple(coords[0][:2])
            b = tuple(coords[-1][:2])
            est = (
                geo.haversine(a[0], a[1], foot[0], foot[1])
                + c["length_m"]
                + geo.haversine(top[0], top[1], b[0], b[1])
                - meta["km"] * 1000
            )
            ests.append((est, i, a, b))
        ests.sort()
        # de ruwe schatting wijst soms de duurdere leg aan: hou de top-2 en
        # reken beide exact door
        for est, i, a, b in ests[:2]:
            if est / 1000 <= max_detour_km * 1.5:
                candidates.append((est, cid, c, i, a, b))

    return sorted(candidates)


# Een optimize-ronde routeerde tot 40 kandidaten x 3-4 calls (~4-5 min); met
# 12 rondes kwam de Lambda-limiet van 15 min in zicht (live, 6 okt 2026).
MAX_EXACT_CANDIDATES = 8
OPTIMIZE_TIME_BUDGET_S = 360.0


def _router_concurrency() -> int:
    """Lees de poolgrootte per uitvoering; ongeldige waarden gebruiken de default."""
    try:
        return max(1, int(os.environ.get("LUSMAKER_ROUTER_CONCURRENCY", "4")))
    except ValueError:
        return 4


def _router_results(evaluate, items):
    """Begrensde batches met een eigen requestcontext per taak, in invoervolgorde."""
    concurrency = _router_concurrency()
    if concurrency == 1:
        for item in items:
            yield evaluate(item)
        return
    items = iter(items)
    with ThreadPoolExecutor(max_workers=concurrency) as pool:
        while batch := list(islice(items, concurrency)):
            futures = [pool.submit(copy_context().run, evaluate, item) for item in batch]
            for future in futures:
                yield future.result()


def _candidates(d: dict, climb_db: dict, max_detour_km: float, limit: int,
                banned=frozenset(), router=gh.route, weighted: bool = False,
                popular_cells=_LOAD_HEAT, max_eval: int | None = None) -> list[dict]:
    """Bereken kandidaat-klimmen dicht bij de huidige route.

    ``max_eval`` begrenst het aantal exact gerouteerde kandidaten (elk ~3-4
    routercalls van ~2 s in productie); de goedkope schatting rangschikt ze.
    """
    from .progress import emit
    candidates = _candidate_prefilter(d, climb_db, max_detour_km, banned=banned)
    legs_meta = d["computed"]["legs"]
    routing = _draft().routing_preferences(d)
    zones = _draft().place_areas(d)
    per_climb: dict[str, dict] = {}
    selection = candidates[: (max_eval if max_eval is not None else max(24, limit * 4))]
    def evaluate(item):
        index, (_est, cid, c, leg_i, a, b) = item
        emit("optimizing", f"Ik bereken de omweg via {c.get('name') or cid} ({index} van {len(selection)}).")
        try:
            preferences = {
                **routing,
                "heat_activity": _draft()._heat_activity(d),
                **_draft()._activity_kwargs(d),
            }
            if weighted or _draft().prefers_paved(d):
                preferences["details"] = True
            r1 = router(
                [a, tuple(c["foot"])],
                avoid_polygons=zones,
                **preferences,
            )
            r2 = router(
                [tuple(c["foot"]), tuple(c["mid"]), tuple(c["top"])],
                **preferences,
            )
            r3 = router(
                [tuple(c["top"]), b],
                avoid_polygons=zones,
                **preferences,
            )
            # eerlijke baseline: zelfde leg zonder corridor-constraint, anders
            # vertekent een omweg-leg de vergelijking (negatieve extra's)
            base_r = router([a, b], avoid_polygons=zones, **preferences)
        except (gh.GhError, DraftError):
            return None
        return r1, r2, r3, base_r

    results = _router_results(evaluate, enumerate(selection, start=1))
    for (_est, cid, c, leg_i, a, b), result in zip(selection, results):
        if result is None:
            continue
        r1, r2, r3, base_r = result
        extra_m = r1["distance_m"] + r2["distance_m"] + r3["distance_m"] - base_r["distance_m"]
        extra_up = r1["ascend_m"] + r2["ascend_m"] + r3["ascend_m"] - base_r["ascend_m"]
        if extra_m / 1000 > max_detour_km:
            continue
        # lus-toets: als de aan- of afvoerroute de klim zelf herbeloopt is het
        # een doodlopend uitsteeksel — geen mooie lus, dus verwerpen
        if r1.get("coords") and r2.get("coords") and r3.get("coords"):
            climb_xy = [(p[0], p[1]) for p in r2["coords"]]
            approach = geo.retrace_m(climb_xy, [(p[0], p[1]) for p in r1["coords"]])
            exit_ = geo.retrace_m(climb_xy, [(p[0], p[1]) for p in r3["coords"]])
            if max(approach, exit_) > min(120.0, 0.45 * c["length_m"]):
                continue
        prev = per_climb.get(cid)
        if prev and prev["extra_km"] <= extra_m / 1000:
            continue
        # positie in de klim-volgorde: aantal klimmen vóór deze leg
        pos = sum(1 for m in legs_meta[:leg_i] if m.get("climb"))
        suggestion = {
            "climb": climbs_mod.summary(c),
            "id": cid,
            "label": (
                f"{c['name']} ({c['length_m'] / 1000:.1f} km "
                f"@ {c['avg_pct']:g}%)"
            ),
            "extra_km": round(extra_m / 1000, 1),
            "extra_hoogtemeters": round(extra_up),
            "extra_hm": round(extra_up),
            "invoegen_op_positie": pos,
            "pos": pos,
            "voorstel": f"lus draft add-climb {d['id']} {cid} --at {pos}",
        }
        if _draft().prefers_paved(d):
            suggestion["onverhard_m"] = round(_unpaved_m([r1, r2, r3]))
            suggestion["onverhard_aandeel"] = suggestion["onverhard_m"] / max(1.0, sum(r["distance_m"] for r in (r1, r2, r3)))
        if weighted:
            suggestion["score_componenten"] = _candidate_surface_components(
                [r1, r2, r3], popular_cells, profile=routing["profile"]
            )
        per_climb[cid] = suggestion
    out = sorted(per_climb.values(), key=lambda s: s["extra_km"])[:limit]
    return out

def suggest(d: dict, climb_db: dict, max_detour_km: float = 10.0, limit: int = 5,
            router=gh.route) -> list[dict]:
    """Klimmen dicht bij de huidige route, gerangschikt op extra kilometers."""
    with _draft().region_scope(d):
        if not d.get("profile_doc"):
            return _draft()._candidates(d, climb_db, max_detour_km, limit, router=router)
        profile_document = profiles.load(d["profile_doc"])
        candidates = _draft()._candidates(
            d,
            climb_db,
            max_detour_km,
            max(10, limit),
            router=router,
            weighted=True,
        )
        weights = profile_document["gewichten"]
        prefer_cobbles = _draft()._prefers_cobbles(d, profile_document)
        for candidate in candidates:
            components = _score_components(candidate, max_detour_km)
            score = sum(weights[name] * components[name] for name in profiles.WEIGHT_KEYS)
            if prefer_cobbles:
                score += 0.15 * components["kassei"]
            candidate["score"] = round(score, 6)
            candidate["score_componenten"] = components
        return sorted(
            candidates,
            key=lambda candidate: (
                -candidate["score"],
                -candidate["extra_hoogtemeters"],
                candidate["extra_km"],
                candidate["climb"]["id"],
            ),
        )[:limit]


def _pick_anchor(start: dict, climb_db: dict, max_km: float) -> dict | None:
    """Kies de zwaarste bereikbare klim als startpunt voor een lege lus."""
    climbs = climb_db.values() if isinstance(climb_db, dict) else climb_db
    reachable = []
    for climb in climbs:
        distance_m = geo.haversine(
            start["lat"], start["lon"], climb["foot"][0], climb["foot"][1]
        )
        estimate_m = 2 * distance_m * 1.3 + climb["length_m"]
        if estimate_m <= max_km * 1000:
            reachable.append(climb)
    if not reachable:
        return None
    return sorted(reachable, key=lambda c: (-c["gain_m"], c["id"]))[0]


pick_anchor = _pick_anchor


def _eligible_candidates(candidates: list[dict], budget_km: float,
                         min_ratio: float, banned=frozenset()) -> list[dict]:
    """Filter kandidaten puur op banlijst, veiligheidsbudget en hm/km."""
    max_detour_km = budget_km * 0.85
    return [
        candidate for candidate in candidates
        if candidate["climb"]["id"] not in banned
        and candidate["extra_km"] <= max_detour_km
        and candidate["extra_hoogtemeters"] / max(candidate["extra_km"], 0.3) >= min_ratio
    ]


def _objective_weights(objective) -> dict | None:
    if objective in ("hm-per-km", "toeren", FLAT, _LEGACY_HM):
        return None
    if objective == "hm":
        objective = {"hoogtemeters": 1.0}
    elif objective == "offroad":
        objective = {"offroad": 1.0}
    if not isinstance(objective, dict):
        raise DraftError(
            "objective moet 'hm', 'hm-per-km', 'offroad', 'toeren', 'vlak' "
            "of een gewichten-dict zijn"
        )
    try:
        return profiles.normalize_weights(objective)
    except profiles.ProfileError as exc:
        raise DraftError(str(exc)) from exc


def _score_components(candidate: dict, budget_km: float) -> dict:
    extra_km = candidate["extra_km"]
    gain = candidate["extra_hoogtemeters"]
    surface = candidate.get("score_componenten", {})
    return {
        "hoogtemeters": min(1.0, max(0.0, gain / max(extra_km, 0.3) / 20.0)),
        "offroad": min(1.0, max(0.0, surface.get("offroad", 0.0))),
        "populair": min(1.0, max(0.0, surface.get("populair", 0.0))),
        "autovrij": min(1.0, max(0.0, surface.get("autovrij", 0.0))),
        "kort": min(1.0, max(0.0, 1.0 - extra_km / max(budget_km, 0.001))),
        "kassei": min(1.0, max(0.0, surface.get("kassei", 0.0))),
    }


def _select_candidate(candidates: list[dict], objective, budget_km: float | None = None,
                      prefer_cobbles: bool = False, prefer_paved: bool = False) -> dict | None:
    """Kies deterministisch de beste kandidaat voor het gevraagde doel."""
    weights = _objective_weights(objective)
    if not candidates:
        return None
    if prefer_paved:
        candidates = _paved_candidates(candidates, lambda c: c.get("onverhard_aandeel", 0.0))
    budget_km = budget_km if budget_km is not None else max(
        candidate["extra_km"] for candidate in candidates
    )

    def key(candidate):
        extra_km = candidate["extra_km"]
        gain = candidate["extra_hoogtemeters"]
        ratio = gain / max(extra_km, 0.3)
        surface_tie = (candidate.get("onverhard_m", 0),) if prefer_paved else ()
        if objective == FLAT:
            # Laagste stijging per km wint; bij gelijkspel de kleinste stijging.
            return (ratio, gain, *surface_tie, extra_km, candidate["climb"]["id"])
        if weights is None:
            primary = gain if objective == _LEGACY_HM else ratio
        else:
            components = _score_components(candidate, budget_km)
            primary = sum(weights[name] * components[name] for name in profiles.WEIGHT_KEYS)
            if prefer_cobbles:
                primary += 0.15 * components["kassei"]
            candidate["score"] = round(primary, 6)
            candidate["score_componenten"] = components
        return (-primary, -gain, *surface_tie, extra_km, candidate["climb"]["id"])

    return sorted(candidates, key=key)[0]


def _round_trip_anchor(d: dict, climb_db: dict) -> tuple[tuple[float, float], str]:
    """Kies het route-waypoint dat hemelsbreed het verst van start ligt."""
    requested = d.get("round_trip_anchor")
    if requested:
        return (
            (requested["lat"], requested["lon"]),
            requested.get("label") or "rond-plek",
        )
    start = (d["start"]["lat"], d["start"]["lon"])
    if not d.get("climbs"):
        return start, "start"

    options = []
    base = copy.deepcopy(d)
    base["opvullingen"] = []
    for leg in _draft()._waypoints(base, climb_db):
        for point_i, point in enumerate(leg["points"]):
            if point_i == 0:
                label = leg["from"]
            elif point_i == len(leg["points"]) - 1:
                label = leg["to"]
            else:
                label = "opvulpunt"
            distance = geo.haversine(start[0], start[1], point[0], point[1])
            options.append((distance, point[0], point[1], label))
    if not options:
        return start, "start"
    _distance, lat, lon, label = max(options)
    return (lat, lon), label


def _target_tolerance_m(d: dict, target_total_m: float) -> float:
    """Toegestane afwijking rond een doelafstand (aanvraag wint van default)."""
    request = d.get("route_request") or {}
    if request.get("target_km") is not None and abs(
        request["target_km"] * 1000.0 - target_total_m
    ) < 1.0:
        return request.get("tolerance_km", 2.5) * 1000.0
    return max(100.0, target_total_m * 0.1)


def _format_km(value: float) -> str:
    return f"{value:.1f}".rstrip("0").rstrip(".").replace(".", ",")


def _friendly_stop_reason(reason: str) -> str:
    """Een technische stopreden als zin voor de gebruiker."""
    if "tijdslimiet" in reason:
        return "De rekentijd was op; dit is de beste lus die tot dan gevonden werd."
    if "dezelfde wegen" in reason or "overlap" in reason:
        return "Er lag geen extra lus in de buurt zonder dezelfde wegen opnieuw te rijden."
    return "Er paste geen extra klim of lus die bij je wensen past."


def _fill_with_round_trip(d: dict, climb_db: dict, budget_m: float,
                          router=None, round_trip_fn=gh.round_trip,
                          objective="hm", prefer_cobbles: bool = False,
                          popular_cells=_LOAD_HEAT,
                          target_total_m: float | None = None,
                          seed_start: int = 0,
                          deadline: float | None = None,
                          clock=time.monotonic) -> dict:
    """Vul restbudget met de beste van vijf niet-overlappende GH-rondritten."""
    if router is None:
        router = _draft().route
    if not d.get("loop"):
        return {"filled": False, "reason": "draft is geen lus"}
    if not d.get("computed"):
        return {"filled": False, "reason": "draft is nog niet gerouteerd"}

    current_m = d["computed"]["total_km"] * 1000.0
    remaining_m = budget_m - current_m
    requested_m = (
        remaining_m * 0.9
        if target_total_m is None
        else min(remaining_m, target_total_m - current_m)
    )
    if requested_m < 1500.0:
        return {"filled": False, "reason": "minder dan 1,5 km opvulbudget over"}

    anchor, label = _round_trip_anchor(d, climb_db)
    existing = [
        (point[0], point[1])
        for meta, leg in zip(d["computed"].get("legs", []), d.get("_geometry", []))
        if not meta.get("opvulling")
        for point in leg
    ]
    weights = _objective_weights(objective)
    prefer_paved = _draft().prefers_paved(d)
    preferences = {
        **_draft().routing_preferences(d),
        "avoid_polygons": _draft().place_areas(d),
        "heat_activity": _draft()._heat_activity(d),
        **_draft()._activity_kwargs(d),
    }
    candidates = []
    fallback = []
    def exhausted(reason):
        # Korte lussen hebben weinig topologische opties. Probeer pas bij
        # mislukking extra seeds; succesvolle bestaande routes veranderen niet.
        if seed_start == 0 and target_total_m is not None:
            return _fill_with_round_trip(
                d, climb_db, budget_m, router=router, round_trip_fn=round_trip_fn,
                objective=objective, prefer_cobbles=prefer_cobbles,
                popular_cells=popular_cells, target_total_m=target_total_m,
                seed_start=5, deadline=deadline, clock=clock,
            )
        return {"filled": False, "reason": reason}

    def seeds():
        for seed in range(seed_start, 5 if seed_start == 0 else 20):
            # Controleer vóór het inplannen van elke seed in een nieuwe batch.
            # De eerste poging mag altijd, ook wanneer de deadline verstreken is.
            if deadline is not None and seed > seed_start and clock() > deadline:
                break
            yield seed

    def evaluate(seed):
        from .progress import emit
        emit("variants", f"Ik toets lusvariant {seed + 1} aan je gewenste afstand.")
        try:
            candidate = round_trip_fn(
                anchor,
                requested_m,
                seed,
                details=(weights is not None or prefer_paved),
                **preferences,
            )
        except (gh.GhError, DraftError):
            return seed, None
        return seed, candidate

    for seed, candidate in _router_results(evaluate, seeds()):
        if candidate is None:
            continue
        coords = [(point[0], point[1]) for point in candidate.get("coords", [])]
        if len(coords) < 2 or current_m + candidate["distance_m"] > budget_m:
            continue
        overlap_m = max(
            geo.retrace_m(existing, coords),
            geo.retrace_m(existing, list(reversed(coords))),
            geo.retrace_m(coords, existing),
            geo.retrace_m(list(reversed(coords)), existing),
        ) if existing else 0.0
        if overlap_m > 300.0:
            # Toegangswegen vanaf het anker overlappen bij lange lussen bijna
            # altijd; bewaar als terugval in plaats van 20+ km tekort te komen.
            if overlap_m <= max(2000.0, 0.15 * candidate["distance_m"]):
                fallback.append((overlap_m, seed, candidate, coords))
            continue
        if objective == FLAT:
            score = -candidate.get("ascend_m", 0) / max(candidate["distance_m"] / 1000.0, 0.3)
        elif weights is None:
            # Ook hm-per-km koos vóór T11 de rondritlob op absolute stijging.
            score = candidate.get("ascend_m", 0)
        else:
            surface = _candidate_surface_components([candidate], popular_cells, profile=preferences["profile"])
            pseudo_candidate = {
                "extra_km": candidate["distance_m"] / 1000.0,
                "extra_hoogtemeters": candidate.get("ascend_m", 0),
                "score_componenten": surface,
            }
            components = _score_components(pseudo_candidate, remaining_m / 1000.0)
            score = sum(weights[name] * components[name] for name in profiles.WEIGHT_KEYS)
            if prefer_cobbles:
                score += 0.15 * components["kassei"]
        candidates.append((score, -seed, seed, candidate, coords))

    overlap_note = None
    if not candidates and fallback and target_total_m is not None:
        # Minste overlap eerst; de afstand blijft hieronder de eerste sleutel.
        fallback.sort(key=lambda item: item[0])
        for overlap_m, seed, candidate, coords in fallback[:3]:
            candidates.append((-overlap_m, -seed, seed, candidate, coords))
        overlap_note = f"een deel van de extra lus volgt dezelfde wegen (ongeveer {fallback[0][0] / 1000:.1f} km)".replace(".", ",")
    if not candidates:
        return exhausted("geen extra lus gevonden die niet over dezelfde wegen terugkeert")

    if prefer_paved:
        candidates = _paved_candidates(candidates, lambda item: _unpaved_m([item[3]]) / max(item[3]["distance_m"], 1.0))
    before = copy.deepcopy(d)
    tolerance_m = _target_tolerance_m(d, target_total_m or 0.0)
    # A requested distance comes before soft surface/popularity preferences.
    # Without a distance target, preserve the existing objective ordering.
    ordered = sorted(candidates, key=lambda item: (
        -abs(current_m + item[3]["distance_m"] - target_total_m) if target_total_m is not None else 0,
        item[0],
        -_unpaved_m([item[3]]) if prefer_paved else 0,
        item[1]), reverse=True)
    best = None
    best_error = float("inf")
    for _ascend, _seed_order, seed, candidate, coords in ordered:
        via = geo.resample(coords, 400.0)
        via[0] = anchor
        via[-1] = anchor
        d.setdefault("opvullingen", []).append(
            {
                "anchor": [anchor[0], anchor[1]],
                "label": label,
                "points": [[point[0], point[1]] for point in via],
                "seed": seed,
            }
        )
        d["computed"] = None
        d.pop("_geometry", None)
        try:
            router(d, climb_db)
        except (DraftError, gh.GhError):
            d.clear()
            d.update(copy.deepcopy(before))
            continue
        actual_m = d["computed"]["total_km"] * 1000.0
        if actual_m <= budget_m:
            if overlap_note:
                d["fill_note"] = overlap_note[0].upper() + overlap_note[1:] + "."
            else:
                d.pop("fill_note", None)
            result = {
                "filled": True,
                "seed": seed,
                "extra_km": round(d["computed"]["total_km"] - current_m / 1000.0, 1),
                "extra_hoogtemeters": round(
                    d["computed"]["ascend_m"] - before["computed"]["ascend_m"]
                ),
            }
            error = abs(actual_m - target_total_m) if target_total_m is not None else 0
            if error <= tolerance_m:
                return result
            if error < best_error:
                best, best_error = (copy.deepcopy(d), result), error
        d.clear()
        d.update(copy.deepcopy(before))

    if best is not None:
        # A short first batch is not success: search the bounded extra seeds
        # before retaining a clearly labelled best-effort route.
        if seed_start == 0 and target_total_m is not None:
            extra = exhausted("geen variant binnen de gewenste afstand")
            if extra.get("filled") and abs(d["computed"]["total_km"] * 1000 - target_total_m) < best_error:
                return extra
        d.clear()
        d.update(best[0])
        return best[1]
    return exhausted("round_trip-kandidaten overschrijden budget na integratie")


def optimize(d: dict, climb_db: dict, max_km: float, objective=None,
             min_ratio: float = 8.0, max_rounds: int = 12,
             route_fn=None, candidates_fn=None, fill: bool = True,
             round_trip_fn=gh.round_trip,
             fill_target_km: float | None = None) -> dict:
    from .route_cache import RouteCache
    if route_fn is None:
        route_fn = _draft().route
    from functools import partial
    with _draft().region_scope(d):
        cache = RouteCache(gh.route)
        if candidates_fn is None:
            candidates_fn = partial(_draft()._candidates, router=cache)
        result = _draft()._optimize(
            d, climb_db, max_km, objective, min_ratio, max_rounds,
            route_fn=route_fn,
            candidates_fn=candidates_fn,
            fill=fill,
            round_trip_fn=round_trip_fn,
            fill_target_km=fill_target_km,
        )
        result["router_cache"] = {"hits": cache.hits, "misses": cache.misses}
        result["budget_rollbacks"] = sum(r.get("status") == "teruggedraaid (budget)" for r in result["rondes"])
        from . import telemetry
        telemetry.emit(
            "optimize",
            operation="draft.optimize",
            budget_rollbacks=result["budget_rollbacks"],
            rounds=len(result["rondes"]),
        )
        return result


def _optimize(d: dict, climb_db: dict, max_km: float, objective=None,
              min_ratio: float = 8.0, max_rounds: int = 12,
              route_fn=None, candidates_fn=None, fill: bool = True,
              round_trip_fn=gh.round_trip,
              fill_target_km: float | None = None,
              time_budget_s: float = OPTIMIZE_TIME_BUDGET_S,
              clock=time.monotonic) -> dict:
    """Vul een draft greedy met klimmen binnen een hard afstandsbudget."""
    if route_fn is None:
        route_fn = _draft().route
    if candidates_fn is None:
        candidates_fn = _draft()._candidates
    deadline = clock() + time_budget_s
    if max_km <= 0:
        raise DraftError("Je maximale afstand moet groter dan 0 km zijn.")
    if min_ratio < 0:
        raise DraftError("Het minimum aan hoogtemeters per extra kilometer mag niet negatief zijn.")
    if max_rounds < 0:
        raise DraftError("Het maximale aantal zoekrondes mag niet negatief zijn.")
    if fill_target_km is not None and fill_target_km <= 0:
        raise DraftError("Je gewenste afstand moet groter dan 0 km zijn.")
    if fill_target_km is not None and fill_target_km > max_km:
        raise DraftError("De gewenste afstand mag niet groter zijn dan je maximum.")
    objective = _draft().objective_for_draft(d, objective)
    # Valideer ook als er door max_rounds=0 geen kandidaat gekozen wordt.
    weights = _objective_weights(objective)
    profile_document = profiles.load(d["profile_doc"]) if d.get("profile_doc") else None
    prefer_cobbles = bool(profile_document and _draft()._prefers_cobbles(d, profile_document))
    _select_candidate([], objective, prefer_cobbles=prefer_cobbles)
    pure_offroad = weights is not None and weights["offroad"] == 1.0
    tour_only = objective in ("toeren", FLAT)

    if not d["climbs"] and d.get("loop"):
        # Offroad en een gewone toer jagen niet op klimmen: meteen opvullen.
        anchor = (
            None
            if pure_offroad or tour_only
            else _pick_anchor(d["start"], climb_db, max_km)
        )
        if anchor is None:
            if not fill:
                raise DraftError("Er is geen klim bereikbaar binnen je maximale afstand.")
            # Een nieuwe afstandsoptimalisatie vervangt eerdere rondritlobben.
            # De heen- en terugweg naar een expliciete rond-plek telt mee
            # voordat we het resterende opvulbudget aan GraphHopper geven.
            d["opvullingen"] = []
            d["computed"] = {
                "routed_at": time.strftime("%Y-%m-%d %H:%M"),
                "total_km": 0.0,
                "ascend_m": 0,
                "descend_m": 0,
                "legs": [],
                "kwaliteit": {"heen_en_weer_m": 0},
            }
            d["_geometry"] = []
            if d.get("round_trip_anchor"):
                d["computed"] = None
        else:
            d["climbs"].append(anchor["id"])
            d["computed"] = None
            d.pop("_geometry", None)

    if not d.get("computed") or (not d.get("_geometry") and d["climbs"]):
        route_fn(d, climb_db)
    if d["computed"]["total_km"] > max_km:
        raise DraftError(
            f"De route wordt {_format_km(d['computed']['total_km'])} km, "
            f"langer dan je maximum van {_format_km(max_km)} km."
        )

    rounds = []
    banned = set()
    stopped_because = "maximum aantal rondes bereikt"
    if pure_offroad or tour_only:
        max_rounds = 0
        stopped_because = (
            "toerdoel: alleen rondrit-opvulling"
            if tour_only
            else "offroad-doel: alleen rondrit-opvulling"
        )
    target_m = fill_target_km * 1000.0 if fill_target_km is not None else None
    tolerance_m = _target_tolerance_m(d, target_m) if target_m is not None else 0.0
    # Met een afstandsdoel mag een klim de route nooit buiten het doelvenster
    # duwen: een ceiling van 1,2x target liet routes tot ver boven de tolerantie
    # groeien, waarna opvulling ze niet meer kon corrigeren.
    climb_cap_km = (
        min(max_km, (target_m + tolerance_m) / 1000.0)
        if target_m is not None
        else max_km
    )

    def climb_rounds(ratio, rounds_limit, start_number, cap_km, label=None):
        nonlocal stopped_because
        for round_number in range(start_number, start_number + rounds_limit):
            from .progress import emit
            emit("optimizing", f"Ik vergelijk routevarianten (ronde {round_number}).")
            budget_km = cap_km - d["computed"]["total_km"]
            if budget_km < 1.0:
                stopped_because = "minder dan 1 km budget over"
                return
            if not d["climbs"] and not d.get("_geometry"):
                stopped_because = "geen klim bereikbaar; round_trip vanaf start"
                return

            if clock() > deadline:
                stopped_because = "tijdslimiet bereikt; beste route tot nu toe behouden"
                return
            candidate_kwargs = {
                "max_detour_km": budget_km * 0.85,
                "limit": 10,
                "banned": frozenset(banned),
            }
            if "max_eval" in inspect.signature(candidates_fn).parameters:
                candidate_kwargs["max_eval"] = MAX_EXACT_CANDIDATES
            if weights is not None:
                if "weighted" in inspect.signature(candidates_fn).parameters:
                    candidate_kwargs["weighted"] = True
            candidates = candidates_fn(d, climb_db, **candidate_kwargs)
            eligible = _eligible_candidates(candidates, budget_km, ratio, banned)
            selected = _select_candidate(
                eligible,
                objective,
                budget_km=budget_km,
                prefer_cobbles=prefer_cobbles,
                prefer_paved=_draft().prefers_paved(d),
            )
            if selected is None:
                stopped_because = "geen kandidaten boven min-ratio binnen budget"
                return

            climb_id = selected["climb"]["id"]
            position = selected["invoegen_op_positie"]
            prev_retrace = (d["computed"].get("kwaliteit") or {}).get("heen_en_weer_m", 0)
            d["climbs"].insert(position, climb_id)
            d["computed"] = None
            d.pop("_geometry", None)
            route_fn(d, climb_db)

            round_result = {
                "ronde": len(rounds) + 1,
                "toegevoegd": climb_id,
                "voorspeld_extra_km": selected["extra_km"],
                "totaal_na": d["computed"]["total_km"],
            }
            if label:
                round_result["fase"] = label
            new_retrace = (d["computed"].get("kwaliteit") or {}).get("heen_en_weer_m", 0)
            if d["computed"]["total_km"] > cap_km:
                round_result["status"] = "teruggedraaid (budget)"
                d["climbs"].pop(position)
                d["computed"] = None
                d.pop("_geometry", None)
                banned.add(climb_id)
                route_fn(d, climb_db)
                _draft().save(d)
            elif new_retrace - prev_retrace > 120:
                # de toevoeging maakte de lus heen-en-weer-achtig: terugdraaien
                round_result["status"] = "teruggedraaid (heen-en-weer)"
                round_result["heen_en_weer_delta_m"] = round(new_retrace - prev_retrace)
                d["climbs"].pop(position)
                d["computed"] = None
                d.pop("_geometry", None)
                banned.add(climb_id)
                route_fn(d, climb_db)
                _draft().save(d)
            else:
                round_result["status"] = "geaccepteerd"
                _draft().save(d)
            rounds.append(round_result)
            if label and abs(d["computed"]["total_km"] * 1000.0 - target_m) <= tolerance_m:
                return

    climb_rounds(min_ratio, max_rounds, 1, climb_cap_km)

    def short_of_target():
        return (
            target_m is not None
            and d["computed"]["total_km"] * 1000.0 < target_m - tolerance_m
        )

    can_top_up = not (pure_offroad or tour_only)
    filled = False

    def try_fill():
        nonlocal stopped_because, filled
        remaining_m = (max_km - d["computed"]["total_km"]) * 1000.0
        if not (fill and d.get("loop") and remaining_m >= 1500.0):
            return
        fill_result = _fill_with_round_trip(
            d,
            climb_db,
            max_km * 1000.0,
            router=route_fn,
            round_trip_fn=round_trip_fn,
            objective=objective,
            prefer_cobbles=prefer_cobbles,
            target_total_m=target_m,
            deadline=deadline + 60.0,
            clock=clock,
        )
        if fill_result["filled"]:
            filled = True
            rounds.append(
                {
                    "ronde": len(rounds) + 1,
                    "status": "opgevuld (round_trip)",
                    "extra_km": fill_result["extra_km"],
                    "extra_hoogtemeters": fill_result["extra_hoogtemeters"],
                    "totaal_na": d["computed"]["total_km"],
                }
            )
            stopped_because = "resterend budget opgevuld met round_trip"
        else:
            stopped_because = fill_result["reason"]
        _draft().save(d)

    try_fill()
    if short_of_target() and can_top_up and d.get("climbs"):
        # De strikte hm/km-drempel en/of de rondrit lieten de route onder het
        # doelvenster. Een gevraagde afstand gaat voor: vul aan met de beste
        # resterende klimmen zonder ratio-drempel tot het venster bereikt is.
        climb_rounds(0.0, 12, len(rounds) + 1, climb_cap_km, label="aanvulling")
        if short_of_target() and not filled:
            try_fill()
    if short_of_target():
        shortfall = target_m / 1000.0 - d["computed"]["total_km"]
        stopped_because = (
            f"doelafstand niet haalbaar: {d['computed']['total_km']:.1f} km, "
            f"{shortfall:.1f} km onder het doel van {target_m / 1000.0:.1f} km "
            f"({stopped_because})"
        )
        d["optimize_note"] = _friendly_stop_reason(stopped_because)
    else:
        d.pop("optimize_note", None)
    _draft().save(d)

    return {
        "id": d["id"],
        "objective": "hm" if objective == _LEGACY_HM else objective,
        "max_km": float(max_km),
        "resultaat": _draft().summary(d),
        "rondes": rounds,
        "gestopt_omdat": stopped_because,
    }
