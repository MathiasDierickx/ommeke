"""Draft-routes: opbouwen, routeren (met lus-constraint), suggesties, opslag."""
import json
import time
import uuid
from contextlib import contextmanager

from . import climbs as climbs_mod
from . import config, geo, gh


class DraftError(RuntimeError):
    pass


def _path(draft_id: str):
    return config.DRAFTS / f"{draft_id}.json"


def load(draft_id: str) -> dict:
    p = _path(draft_id)
    if not p.exists():
        raise DraftError(f"draft '{draft_id}' bestaat niet — zie `lus draft list`")
    with open(p) as f:
        return json.load(f)


def save(d: dict) -> None:
    config.ensure_dirs()
    with open(_path(d["id"]), "w") as f:
        json.dump(d, f, ensure_ascii=False)


def region_slug(d: dict) -> str:
    """Oude drafts horen na migratie bij Vlaanderen."""
    if d.get("region"):
        return d["region"]
    return config.LEGACY_SLUG


@contextmanager
def region_scope(d: dict):
    with config.use_region(region_slug(d)) as region:
        yield region


def new(start: dict, name: str | None, loop: bool, end: dict | None, strict: bool = False,
        avoid_cobbles: bool = False, avoid_concrete: bool = False) -> dict:
    d = {
        "id": uuid.uuid4().hex[:6],
        "name": name or "lus",
        "created": time.strftime("%Y-%m-%d %H:%M"),
        "region": config.current_region().slug,
        "start": start,  # {lat, lon, label}
        "end": end,      # None => zelfde als start bij loop
        "loop": loop,
        "strict": strict,
        "avoid_cobbles": avoid_cobbles,
        "avoid_concrete": avoid_concrete,
        "avoid_places": [],  # [{label, lat, lon, radius_km, factor}]
        "climbs": [],    # geordende lijst klim-ids
        "computed": None,
    }
    save(d)
    return d


def create(start: str, name: str | None = None, loop: bool = True,
           end: str | None = None, strict: bool = False,
           avoid_cobbles: bool = False, avoid_concrete: bool = False,
           region: str | None = None) -> dict:
    """Maak een draft vanuit gebruikersgerichte plaatsnamen of coördinaten."""
    from . import geocode

    with config.use_region(region):
        start_point, alternatives = geocode.resolve(start)
        end_point = geocode.resolve(end)[0] if end else None
        d = new(
            start=start_point,
            name=name,
            loop=loop,
            end=end_point,
            strict=strict,
            avoid_cobbles=avoid_cobbles,
            avoid_concrete=avoid_concrete,
        )
    out = summary(d)
    out["start_geocoded_als"] = start_point["label"]
    if alternatives:
        out["andere_kandidaten"] = alternatives
    out["hint"] = (
        f"voeg klimmen toe: `lus draft add-climb {d['id']} <klim-id>` "
        f"en routeer: `lus draft route {d['id']}`"
    )
    return out


def list_all() -> list[dict]:
    out = []
    for p in sorted(config.DRAFTS.glob("*.json")):
        with open(p) as f:
            d = json.load(f)
        item = {
                "id": d["id"],
                "name": d["name"],
                "start": d["start"].get("label"),
                "loop": d["loop"],
                "climbs": d["climbs"],
                "total_km": (d.get("computed") or {}).get("total_km"),
            }
        if config.load_registry() is not None:
            item["region"] = region_slug(d)
        out.append(item)
    return out


def add_climb(draft_id: str, climb_id: str, position: int | None = None,
              climb_db: dict | None = None) -> dict:
    """Voeg een bekende klim toe en maak een bestaande berekening ongeldig."""
    d = load(draft_id)
    with region_scope(d):
        db = climbs_mod.all_climbs() if climb_db is None else climb_db
        if climb_id not in db:
            raise DraftError(f"onbekende klim '{climb_id}' — zie `lus climbs list`")
        if climb_id in d["climbs"]:
            raise DraftError(f"klim '{climb_id}' zit al in de draft")
        insert_at = position if position is not None else len(d["climbs"])
        d["climbs"].insert(insert_at, climb_id)
        d["computed"] = None
        d.pop("_geometry", None)
        save(d)
        out = summary(d)
        out["hint"] = f"herrouteer: `lus draft route {d['id']}`"
        return out


def remove_climb(draft_id: str, climb_id: str) -> dict:
    """Verwijder een klim en maak een bestaande berekening ongeldig."""
    d = load(draft_id)
    if climb_id not in d["climbs"]:
        raise DraftError(f"klim '{climb_id}' zit niet in de draft")
    d["climbs"].remove(climb_id)
    d["computed"] = None
    d.pop("_geometry", None)
    save(d)
    return summary(d)


def avoid_place(draft_id: str, place: str, radius_km: float = 2.5,
                factor: float = 0.35) -> dict:
    """Voeg een zachte vermijdzone rond een plaats toe."""
    from . import geocode

    d = load(draft_id)
    with region_scope(d):
        point, alternatives = geocode.resolve(place)
    d.setdefault("avoid_places", []).append(
        {
            "label": point["label"],
            "lat": point["lat"],
            "lon": point["lon"],
            "radius_km": radius_km,
            "factor": factor,
        }
    )
    d["computed"] = None
    d.pop("_geometry", None)
    save(d)
    out = summary(d)
    if alternatives:
        out["andere_kandidaten"] = alternatives
    out["hint"] = f"herrouteer: `lus draft route {d['id']}`"
    return out


def unavoid_place(draft_id: str, place: str) -> dict:
    """Verwijder vermijdzones waarvan het label de zoektekst bevat."""
    d = load(draft_id)
    before = len(d.get("avoid_places", []))
    d["avoid_places"] = [
        point for point in d.get("avoid_places", [])
        if place.lower() not in point["label"].lower()
    ]
    if len(d["avoid_places"]) == before:
        raise DraftError(f"geen vermijdzone gevonden voor '{place}'")
    d["computed"] = None
    d.pop("_geometry", None)
    save(d)
    return summary(d)


def _waypoints(d: dict, climb_db: dict) -> list[dict]:
    """Reeks legs; een klim-leg krijgt [voet, midden, top] zodat de route
    effectief de helling zelf omhoog rijdt."""
    start = (d["start"]["lat"], d["start"]["lon"])
    legs = []
    prev_label, prev_pt = "start", start
    for cid in d["climbs"]:
        c = climb_db.get(cid)
        if not c:
            raise DraftError(f"klim '{cid}' niet in database (zie `lus climbs list`)")
        foot, mid, top = tuple(c["foot"]), tuple(c["mid"]), tuple(c["top"])
        legs.append({"from": prev_label, "to": f"{c['name']} (voet)", "points": [prev_pt, foot]})
        legs.append({"from": f"{c['name']} (voet)", "to": f"{c['name']} (top)",
                     "points": [foot, mid, top], "climb": cid})
        prev_label, prev_pt = f"{c['name']} (top)", top
    if d["loop"]:
        legs.append({"from": prev_label, "to": "start", "points": [prev_pt, start]})
    elif d.get("end"):
        end = (d["end"]["lat"], d["end"]["lon"])
        legs.append({"from": prev_label, "to": d["end"].get("label", "einde"), "points": [prev_pt, end]})
    return legs


def _circle_ring(lat, lon, radius_km, n=24):
    import math

    ring = []
    for i in range(n + 1):
        a = 2 * math.pi * i / n
        dlat = radius_km * 1000 * math.cos(a) / 111320.0
        dlon = radius_km * 1000 * math.sin(a) / (111320.0 * math.cos(math.radians(lat)))
        ring.append([round(lon + dlon, 6), round(lat + dlat, 6)])
    return ring


def place_areas(d: dict) -> list[dict]:
    return [
        {"ring": _circle_ring(p["lat"], p["lon"], p["radius_km"]), "factor": p["factor"]}
        for p in d.get("avoid_places", [])
    ]


def route(d: dict, climb_db: dict, router=gh.route) -> dict:
    with region_scope(d):
        return _route(d, climb_db, router)


def _route(d: dict, climb_db: dict, router=gh.route) -> dict:
    """Routeer alle legs; elke leg vermijdt de corridor van de vorige legs."""
    legs = _waypoints(d, climb_db)
    if not legs:
        raise DraftError("draft heeft geen doel: voeg een klim toe of zet een eindpunt")

    start_pt = (d["start"]["lat"], d["start"]["lon"])
    protect = [start_pt]
    avoid = list(place_areas(d))
    leg_details = []
    computed_legs = []
    total_m = ascend = descend = 0.0

    for leg in legs:
        is_climb = "climb" in leg
        # klim-legs niet blokkeren door de eigen corridor: zonder avoid routen
        res = router(leg["points"],
                     avoid_polygons=place_areas(d) if is_climb else avoid,
                     strict=d.get("strict", False),
                     avoid_cobbles=d.get("avoid_cobbles", False),
                     avoid_concrete=d.get("avoid_concrete", False), details=True)
        coords_latlon = [(c[0], c[1]) for c in res["coords"]]
        seg_len = max(1500.0, res["distance_m"] / 25.0)
        avoid.extend(
            {"ring": r, "factor": 0.30}
            for r in geo.corridor_polygons(coords_latlon, seg_len_m=seg_len, protect=protect)
        )
        leg_details.append(res.get("details", {}))
        total_m += res["distance_m"]
        ascend += res["ascend_m"]
        descend += res["descend_m"]
        computed_legs.append(
            {
                "from": leg["from"],
                "to": leg["to"],
                "km": round(res["distance_m"] / 1000, 2),
                "ascend_m": res["ascend_m"],
                "climb": leg.get("climb"),
                "coords": [[round(a, 6), round(b, 6), (round(e, 1) if e is not None else None)] for a, b, e in res["coords"]],
            }
        )

    d["computed"] = {
        "routed_at": time.strftime("%Y-%m-%d %H:%M"),
        "total_km": round(total_m / 1000, 1),
        "ascend_m": round(ascend),
        "descend_m": round(descend),
        "legs": [
            {k: v for k, v in leg.items() if k != "coords"} for leg in computed_legs
        ],
    }
    d["_geometry"] = [leg["coords"] for leg in computed_legs]
    from . import analysis

    try:
        d["computed"]["kwaliteit"] = analysis.route_stats(d["_geometry"], leg_details)
    except Exception as e:  # metriek mag routeren nooit blokkeren
        d["computed"]["kwaliteit"] = {"error": str(e)}
    save(d)
    return summary(d)


def summary(d: dict) -> dict:
    out = {
        "id": d["id"],
        "name": d["name"],
        "start": d["start"].get("label"),
        "loop": d["loop"],
        "strict": d.get("strict", False),
        "avoid_cobbles": d.get("avoid_cobbles", False),
        "avoid_concrete": d.get("avoid_concrete", False),
        "avoid_places": d.get("avoid_places", []),
        "climbs": d["climbs"],
        "computed": d.get("computed"),
    }
    if config.load_registry() is not None:
        out["region"] = region_slug(d)
    return out


def _candidates(d: dict, climb_db: dict, max_detour_km: float, limit: int,
                banned=frozenset(), router=gh.route) -> list[dict]:
    """Bereken kandidaat-klimmen dicht bij de huidige route."""
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
            if meta.get("climb"):
                continue  # niet invoegen midden in een andere klim
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

    candidates.sort()
    strict = d.get("strict", False)
    cobb = d.get("avoid_cobbles", False)
    conc = d.get("avoid_concrete", False)
    zones = place_areas(d)
    per_climb: dict[str, dict] = {}
    for _est, cid, c, leg_i, a, b in candidates[: max(24, limit * 4)]:
        try:
            r1 = router([a, tuple(c["foot"])], avoid_polygons=zones, strict=strict, avoid_cobbles=cobb, avoid_concrete=conc)
            r2 = router([tuple(c["foot"]), tuple(c["mid"]), tuple(c["top"])], strict=strict, avoid_cobbles=cobb, avoid_concrete=conc)
            r3 = router([tuple(c["top"]), b], avoid_polygons=zones, strict=strict, avoid_cobbles=cobb, avoid_concrete=conc)
            # eerlijke baseline: zelfde leg zonder corridor-constraint, anders
            # vertekent een omweg-leg de vergelijking (negatieve extra's)
            base_r = router([a, b], avoid_polygons=zones, strict=strict, avoid_cobbles=cobb, avoid_concrete=conc)
        except gh.GhError:
            continue
        extra_m = r1["distance_m"] + r2["distance_m"] + r3["distance_m"] - base_r["distance_m"]
        extra_up = r1["ascend_m"] + r2["ascend_m"] + r3["ascend_m"] - base_r["ascend_m"]
        if extra_m / 1000 > max_detour_km:
            continue
        prev = per_climb.get(cid)
        if prev and prev["extra_km"] <= extra_m / 1000:
            continue
        # positie in de klim-volgorde: aantal klimmen vóór deze leg
        pos = sum(1 for m in legs_meta[:leg_i] if m.get("climb"))
        per_climb[cid] = {
            "climb": climbs_mod.summary(c),
            "extra_km": round(extra_m / 1000, 1),
            "extra_hoogtemeters": round(extra_up),
            "invoegen_op_positie": pos,
            "voorstel": f"lus draft add-climb {d['id']} {cid} --at {pos}",
        }
    out = sorted(per_climb.values(), key=lambda s: s["extra_km"])[:limit]
    return out


def suggest(d: dict, climb_db: dict, max_detour_km: float = 10.0, limit: int = 5,
            router=gh.route) -> list[dict]:
    """Klimmen dicht bij de huidige route, gerangschikt op extra kilometers."""
    with region_scope(d):
        return _candidates(d, climb_db, max_detour_km, limit, router=router)


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


def _select_candidate(candidates: list[dict], objective: str) -> dict | None:
    """Kies deterministisch de beste kandidaat voor het gevraagde doel."""
    if objective not in ("hm", "hm-per-km"):
        raise DraftError("objective moet 'hm' of 'hm-per-km' zijn")
    if not candidates:
        return None

    def key(candidate):
        extra_km = candidate["extra_km"]
        gain = candidate["extra_hoogtemeters"]
        ratio = gain / max(extra_km, 0.3)
        primary = gain if objective == "hm" else ratio
        return (-primary, -gain, extra_km, candidate["climb"]["id"])

    return sorted(candidates, key=key)[0]


def optimize(d: dict, climb_db: dict, max_km: float, objective: str = "hm",
             min_ratio: float = 8.0, max_rounds: int = 12,
             route_fn=route, candidates_fn=_candidates) -> dict:
    with region_scope(d):
        return _optimize(
            d, climb_db, max_km, objective, min_ratio, max_rounds,
            route_fn, candidates_fn,
        )


def _optimize(d: dict, climb_db: dict, max_km: float, objective: str = "hm",
              min_ratio: float = 8.0, max_rounds: int = 12,
              route_fn=route, candidates_fn=_candidates) -> dict:
    """Vul een draft greedy met klimmen binnen een hard afstandsbudget."""
    if max_km <= 0:
        raise DraftError("max-km moet groter dan 0 zijn")
    if min_ratio < 0:
        raise DraftError("min-ratio mag niet negatief zijn")
    if max_rounds < 0:
        raise DraftError("max-rounds mag niet negatief zijn")
    # Valideer ook als er door max_rounds=0 geen kandidaat gekozen wordt.
    _select_candidate([], objective)

    if not d["climbs"] and d.get("loop"):
        anchor = _pick_anchor(d["start"], climb_db, max_km)
        if anchor is None:
            raise DraftError("geen klim bereikbaar binnen het budget")
        d["climbs"].append(anchor["id"])
        d["computed"] = None
        d.pop("_geometry", None)

    if not d.get("computed") or not d.get("_geometry"):
        route_fn(d, climb_db)
    if d["computed"]["total_km"] > max_km:
        raise DraftError(
            f"huidige route is {d['computed']['total_km']:.1f} km en overschrijdt "
            f"het budget van {max_km:.1f} km"
        )

    rounds = []
    banned = set()
    stopped_because = "maximum aantal rondes bereikt"
    for round_number in range(1, max_rounds + 1):
        budget_km = max_km - d["computed"]["total_km"]
        if budget_km < 1.0:
            stopped_because = "minder dan 1 km budget over"
            break

        candidates = candidates_fn(
            d, climb_db, max_detour_km=budget_km * 0.85, limit=10,
            banned=frozenset(banned),
        )
        eligible = _eligible_candidates(candidates, budget_km, min_ratio, banned)
        selected = _select_candidate(eligible, objective)
        if selected is None:
            stopped_because = "geen kandidaten boven min-ratio binnen budget"
            break

        climb_id = selected["climb"]["id"]
        position = selected["invoegen_op_positie"]
        d["climbs"].insert(position, climb_id)
        d["computed"] = None
        d.pop("_geometry", None)
        route_fn(d, climb_db)

        round_result = {
            "ronde": round_number,
            "toegevoegd": climb_id,
            "voorspeld_extra_km": selected["extra_km"],
            "totaal_na": d["computed"]["total_km"],
        }
        if d["computed"]["total_km"] > max_km:
            round_result["status"] = "teruggedraaid (budget)"
            d["climbs"].pop(position)
            d["computed"] = None
            d.pop("_geometry", None)
            banned.add(climb_id)
            route_fn(d, climb_db)
            save(d)
        else:
            round_result["status"] = "geaccepteerd"
            save(d)
        rounds.append(round_result)

    return {
        "id": d["id"],
        "objective": objective,
        "max_km": float(max_km),
        "resultaat": summary(d),
        "rondes": rounds,
        "gestopt_omdat": stopped_because,
    }
