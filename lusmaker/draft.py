"""Draft-routes: opbouwen, routeren (met lus-constraint), suggesties, opslag."""
import copy
import fcntl
import json
import re
import time
import uuid
from contextlib import contextmanager

from . import climbs as climbs_mod
from . import aws_state, config, geo, gh, profiles


class DraftError(RuntimeError):
    pass


PROFILES = ("quiet", "trail")
_DRAFT_ID_RE = re.compile(r"^[A-Za-z0-9_-]{1,64}$")
_LEGACY_HM = "__legacy_hm__"
_LOAD_HEAT = object()


def validate_draft_id(draft_id: str) -> str:
    if not isinstance(draft_id, str) or not _DRAFT_ID_RE.fullmatch(draft_id):
        raise DraftError("ongeldig draft-id")
    return draft_id


def _path(draft_id: str):
    return config.drafts_path() / f"{validate_draft_id(draft_id)}.json"


def load(draft_id: str) -> dict:
    validate_draft_id(draft_id)
    if aws_state.enabled():
        value, _etag = aws_state.get_json(f"drafts/{draft_id}.json")
        if value is None:
            raise DraftError(
                f"draft '{draft_id}' bestaat niet — zie `lus draft list`"
            )
        return value
    p = _path(draft_id)
    if not p.exists():
        raise DraftError(f"draft '{draft_id}' bestaat niet — zie `lus draft list`")
    with open(p) as f:
        return json.load(f)


def require_revision(d: dict, expected_revision: int | None) -> None:
    """Wijs een mutatie op een verouderde draft expliciet af."""
    if expected_revision is None:
        return
    actual = int(d.get("revision", 0))
    if actual != expected_revision:
        raise DraftError(
            f"draft '{d['id']}' is gewijzigd: verwachte revisie "
            f"{expected_revision}, huidige revisie {actual}; laad de draft opnieuw"
        )


def save(d: dict, expected_revision: int | None = None) -> None:
    """Schrijf een draft atomisch en verhoog zijn monotone revisie."""
    validate_draft_id(d.get("id"))
    if aws_state.enabled():
        relative = f"drafts/{d['id']}.json"
        current, etag = aws_state.get_json(relative)
        current_revision = int((current or {}).get("revision", 0))
        if expected_revision is not None and current_revision != expected_revision:
            require_revision(
                {"id": d["id"], "revision": current_revision}, expected_revision
            )
        d["revision"] = current_revision + 1
        try:
            aws_state.put_json(
                relative,
                d,
                etag=etag,
                create_only=current is None,
            )
        except aws_state.StateConflict as exc:
            raise DraftError(
                f"draft '{d['id']}' is gelijktijdig gewijzigd; laad de draft opnieuw"
            ) from exc
        return
    config.ensure_dirs()
    path = _path(d["id"])
    lock_path = path.with_name(f".{path.name}.lock")
    with open(lock_path, "a", encoding="utf-8") as lock:
        fcntl.flock(lock.fileno(), fcntl.LOCK_EX)
        current_revision = 0
        if path.exists():
            with open(path, encoding="utf-8") as handle:
                current_revision = int(json.load(handle).get("revision", 0))
        if expected_revision is not None and current_revision != expected_revision:
            require_revision(
                {"id": d["id"], "revision": current_revision}, expected_revision
            )
        d["revision"] = current_revision + 1
        temporary = path.with_name(f".{path.name}.{uuid.uuid4().hex}.tmp")
        try:
            with open(temporary, "w", encoding="utf-8") as handle:
                json.dump(d, handle, ensure_ascii=False)
                handle.flush()
            temporary.replace(path)
        finally:
            if temporary.exists():
                temporary.unlink()


def find_by_request_id(request_id: str) -> dict | None:
    """Vind een eerder gestarte idempotente routeworkflow."""
    if aws_state.enabled():
        return next(
            (
                candidate
                for candidate in aws_state.list_json("drafts")
                if (candidate.get("route_request") or {}).get("request_id")
                == request_id
            ),
            None,
        )
    drafts_path = config.drafts_path()
    if not drafts_path.exists():
        return None
    for path in sorted(drafts_path.glob("*.json")):
        with open(path, encoding="utf-8") as handle:
            candidate = json.load(handle)
        if (candidate.get("route_request") or {}).get("request_id") == request_id:
            return candidate
    return None


def _invalidate_route(d: dict) -> None:
    """Maak alle van route-invoer afgeleide waarden ongeldig."""
    d["computed"] = None
    d.pop("_geometry", None)
    d.pop("_probe", None)


def invalidate_profile(profile_name: str) -> int:
    """Invalideer drafts die een gewijzigd voorkeurenprofiel gebruiken."""
    invalidated = 0
    if aws_state.enabled():
        drafts = aws_state.list_json("drafts")
    else:
        drafts_path = config.drafts_path()
        if not drafts_path.exists():
            return invalidated
        drafts = []
        for path in sorted(drafts_path.glob("*.json")):
            with open(path, encoding="utf-8") as handle:
                drafts.append(json.load(handle))
    for d in drafts:
        if d.get("profile_doc") != profile_name:
            continue
        _invalidate_route(d)
        save(d)
        invalidated += 1
    return invalidated


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
        avoid_cobbles: bool = False, avoid_concrete: bool = False,
        avoid_busy: bool = False,
        profile: str = config.GH_PROFILE, profile_doc: str | None = None) -> dict:
    profile_override = profile_doc is None or profile != config.GH_PROFILE
    if profile_doc is not None:
        document = profiles.load(profile_doc)
        document_prefs = profiles.routing_prefs(document)
        if profile == config.GH_PROFILE:
            profile = document_prefs["profile"]
    if profile not in PROFILES:
        raise DraftError("profiel moet 'quiet' of 'trail' zijn")
    d = {
        "id": uuid.uuid4().hex[:6],
        "name": name or "lus",
        "created": time.strftime("%Y-%m-%d %H:%M"),
        "region": config.current_region().slug,
        "start": start,  # {lat, lon, label}
        "end": end,      # None => zelfde als start bij loop
        "loop": loop,
        "profile": profile,
        "profile_doc": profile_doc,
        "profile_override": profile_override,
        "strict": strict,
        "avoid_cobbles": avoid_cobbles,
        "avoid_concrete": avoid_concrete,
        "avoid_busy": avoid_busy,
        "avoid_places": [],  # [{label, lat, lon, radius_km, factor}]
        "climbs": [],    # geordende lijst klim-ids
        "opvullingen": [],  # persistente round_trip-legs met via-punten
        "computed": None,
    }
    save(d)
    return d


def create(start: str, name: str | None = None, loop: bool = True,
           end: str | None = None, strict: bool = False,
           avoid_cobbles: bool = False, avoid_concrete: bool = False,
           avoid_busy: bool = False,
           region: str | None = None, profile: str = config.GH_PROFILE,
           profile_doc: str | None = None) -> dict:
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
            avoid_busy=avoid_busy,
            profile=profile,
            profile_doc=profile_doc,
        )
        if profile_doc is not None:
            document = profiles.load(profile_doc)
            for place in document["voorkeuren"]["vermijd_plaatsen"]:
                point, _ = geocode.resolve(place)
                d["avoid_places"].append(
                    {
                        "label": point["label"],
                        "lat": point["lat"],
                        "lon": point["lon"],
                        "radius_km": 2.5,
                        "factor": 0.35,
                    }
                )
            if document["voorkeuren"]["vermijd_plaatsen"]:
                save(d)
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
    if aws_state.enabled():
        drafts = sorted(aws_state.list_json("drafts"), key=lambda item: item["id"])
    else:
        drafts = []
        for path in sorted(config.DRAFTS.glob("*.json")):
            with open(path) as handle:
                drafts.append(json.load(handle))
    for d in drafts:
        item = {
                "id": d["id"],
                "revision": int(d.get("revision", 0)),
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
              climb_db: dict | None = None,
              expected_revision: int | None = None) -> dict:
    """Voeg een bekende klim toe en maak een bestaande berekening ongeldig."""
    d = load(draft_id)
    require_revision(d, expected_revision)
    with region_scope(d):
        db = climbs_mod.all_climbs() if climb_db is None else climb_db
        if climb_id not in db:
            raise DraftError(f"onbekende klim '{climb_id}' — zie `lus climbs list`")
        if climb_id in d["climbs"]:
            raise DraftError(f"klim '{climb_id}' zit al in de draft")
        insert_at = position if position is not None else len(d["climbs"])
        d["climbs"].insert(insert_at, climb_id)
        _invalidate_route(d)
        save(d, expected_revision=expected_revision)
        out = summary(d)
        out["hint"] = f"herrouteer: `lus draft route {d['id']}`"
        return out


def remove_climb(
    draft_id: str, climb_id: str, expected_revision: int | None = None
) -> dict:
    """Verwijder een klim en maak een bestaande berekening ongeldig."""
    d = load(draft_id)
    require_revision(d, expected_revision)
    if climb_id not in d["climbs"]:
        raise DraftError(f"klim '{climb_id}' zit niet in de draft")
    d["climbs"].remove(climb_id)
    _invalidate_route(d)
    save(d, expected_revision=expected_revision)
    return summary(d)


def avoid_place(draft_id: str, place: str, radius_km: float = 2.5,
                factor: float = 0.35,
                expected_revision: int | None = None) -> dict:
    """Voeg een zachte vermijdzone rond een plaats toe."""
    from . import geocode

    d = load(draft_id)
    require_revision(d, expected_revision)
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
    _invalidate_route(d)
    save(d, expected_revision=expected_revision)
    out = summary(d)
    if alternatives:
        out["andere_kandidaten"] = alternatives
    out["hint"] = f"herrouteer: `lus draft route {d['id']}`"
    return out


def unavoid_place(
    draft_id: str, place: str, expected_revision: int | None = None
) -> dict:
    """Verwijder vermijdzones waarvan het label de zoektekst bevat."""
    d = load(draft_id)
    require_revision(d, expected_revision)
    before = len(d.get("avoid_places", []))
    d["avoid_places"] = [
        point for point in d.get("avoid_places", [])
        if place.lower() not in point["label"].lower()
    ]
    if len(d["avoid_places"]) == before:
        raise DraftError(f"geen vermijdzone gevonden voor '{place}'")
    _invalidate_route(d)
    save(d, expected_revision=expected_revision)
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
        foot, top = tuple(c["foot"]), tuple(c["top"])
        geom = [tuple(q) for q in c["geom"]]
        kern_van, kern_tot = c.get("kern_van"), c.get("kern_tot")
        if (
            isinstance(kern_van, int)
            and isinstance(kern_tot, int)
            and 0 <= kern_van <= kern_tot < len(geom)
        ):
            # De kruispunt-uiteinden blijven aansluitpunten, maar alleen de
            # steile kern krijgt gedwongen via-punten.
            core_via = [tuple(p) for p in geo.resample(
                geom[kern_van : kern_tot + 1], 150.0
            )]
            via = [foot]
            for point in [*core_via, top]:
                if point != via[-1]:
                    via.append(point)
        else:
            # Oude klimrecords zonder kerngrenzen behouden hun gedrag.
            via = [tuple(p) for p in geo.resample(geom, 150.0)]
        name_hint = c["name"].split(" (")[0]
        legs.append({"from": prev_label, "to": f"{c['name']} (voet)", "points": [prev_pt, foot],
                     "hints": ["", name_hint]})
        legs.append({"from": f"{c['name']} (voet)", "to": f"{c['name']} (top)",
                     "points": via, "climb": cid, "hints": [name_hint] * len(via)})
        prev_label, prev_pt = f"{c['name']} (top)", top
    round_anchor = d.get("round_trip_anchor")
    if round_anchor:
        anchor = (round_anchor["lat"], round_anchor["lon"])
        anchor_label = round_anchor.get("label") or "rond-plek"
        if geo.haversine(prev_pt[0], prev_pt[1], anchor[0], anchor[1]) >= 10.0:
            legs.append(
                {
                    "from": prev_label,
                    "to": anchor_label,
                    "points": [prev_pt, anchor],
                }
            )
        prev_label, prev_pt = anchor_label, anchor
    if d["loop"]:
        legs.append({"from": prev_label, "to": "start", "points": [prev_pt, start]})
    elif d.get("end"):
        end = (d["end"]["lat"], d["end"]["lon"])
        legs.append({"from": prev_label, "to": d["end"].get("label", "einde"), "points": [prev_pt, end]})
    fills = list(d.get("opvullingen", []))
    if not fills:
        return legs

    def at_same_point(a, b):
        return geo.haversine(a[0], a[1], b[0], b[1]) < 10.0

    integrated = []
    remaining = list(fills)
    for leg in legs:
        matches = []
        for fill in remaining:
            for point_i, point in enumerate(leg["points"]):
                if at_same_point(fill["anchor"], point):
                    matches.append((point_i, fill))
                    break
        matches.sort(key=lambda item: item[0])
        if not matches:
            integrated.append(leg)
            continue

        cursor = 0
        from_label = leg["from"]
        for point_i, fill in matches:
            label = fill.get("label", "opvulpunt")
            if point_i > cursor:
                before = {
                    **leg,
                    "from": from_label,
                    "to": label,
                    "points": leg["points"][cursor : point_i + 1],
                }
                if cursor > 0 and before.get("climb"):
                    before["climb_segment"] = before.pop("climb")
                integrated.append(before)
            integrated.append(
                {
                    "from": label,
                    "to": label,
                    "points": [tuple(point) for point in fill["points"]],
                    "opvulling": True,
                }
            )
            remaining.remove(fill)
            cursor = point_i
            from_label = label
        if cursor < len(leg["points"]) - 1:
            after = {
                **leg,
                "from": from_label,
                "points": leg["points"][cursor:],
            }
            if cursor > 0 and after.get("climb"):
                after["climb_segment"] = after.pop("climb")
            integrated.append(after)
        elif cursor == 0 and len(leg["points"]) > 1:
            integrated.append(leg)
    for fill in remaining:
        label = fill.get("label", "opvulpunt")
        integrated.append(
            {
                "from": label,
                "to": label,
                "points": [tuple(point) for point in fill["points"]],
                "opvulling": True,
            }
        )
    return integrated


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


def routing_preferences(d: dict) -> dict:
    """Combineer profielvoorkeuren met expliciete draft-knoppen."""
    effective = {
        "profile": d.get("profile", config.GH_PROFILE),
        "strict": False,
        "avoid_cobbles": False,
        "avoid_concrete": False,
        "avoid_busy": False,
    }
    if d.get("profile_doc"):
        effective.update(profiles.routing_prefs(profiles.load(d["profile_doc"])))
        # Het opgeslagen sportprofiel is bij creatie al van het document
        # afgeleid; een expliciet afwijkend draftprofiel blijft leidend.
        if d.get("profile_override", False):
            effective["profile"] = d.get("profile", effective["profile"])
    for key in ("strict", "avoid_cobbles", "avoid_concrete", "avoid_busy"):
        if d.get(key, False):
            effective[key] = True
    return effective


def objective_for_draft(d: dict, objective):
    """Gebruik profielgewichten tenzij de aanroep een objective overschrijft."""
    if objective is not None:
        return objective
    if d.get("profile_doc"):
        return profiles.load(d["profile_doc"])["gewichten"]
    return _LEGACY_HM


def _bearing(a, b) -> float:
    """Kompaskoers (graden, noord=0) van punt a naar punt b."""
    import math

    lat1, lat2 = math.radians(a[0]), math.radians(b[0])
    dlon = math.radians(b[1] - a[1])
    x = math.sin(dlon) * math.cos(lat2)
    y = math.cos(lat1) * math.sin(lat2) - math.sin(lat1) * math.cos(lat2) * math.cos(dlon)
    return (math.degrees(math.atan2(x, y)) + 360.0) % 360.0


def route(
    d: dict,
    climb_db: dict,
    router=gh.route,
    *,
    post_fn=None,
    area_evs: set[str] | frozenset[str] | None = None,
    expected_revision: int | None = None,
) -> dict:
    require_revision(d, expected_revision)
    with region_scope(d):
        return _route(
            d,
            climb_db,
            router,
            post_fn=post_fn,
            area_evs=area_evs,
            expected_revision=expected_revision,
        )


def _route(
    d: dict,
    climb_db: dict,
    router=gh.route,
    *,
    post_fn=None,
    area_evs: set[str] | frozenset[str] | None = None,
    expected_revision: int | None = None,
) -> dict:
    """Routeer alle legs; elke leg vermijdt de corridor van de vorige legs."""
    d.pop("_probe", None)
    legs = _waypoints(d, climb_db)
    if not legs:
        raise DraftError("draft heeft geen doel: voeg een klim toe of zet een eindpunt")

    start_pt = (d["start"]["lat"], d["start"]["lon"])
    protect = [start_pt]
    if d.get("round_trip_anchor"):
        protect.append(
            (
                d["round_trip_anchor"]["lat"],
                d["round_trip_anchor"]["lon"],
            )
        )
    avoid = list(place_areas(d))
    leg_details = []
    computed_legs = []
    total_m = ascend = descend = 0.0
    preferences = routing_preferences(d)

    for leg in legs:
        is_climb = "climb" in leg or "climb_segment" in leg
        # klim-legs niet blokkeren door de eigen corridor: zonder avoid routen
        route_kwargs = {
            "avoid_polygons": place_areas(d) if is_climb else avoid,
            "strict": preferences["strict"],
            "avoid_cobbles": preferences["avoid_cobbles"],
            "avoid_concrete": preferences["avoid_concrete"],
            "avoid_busy": preferences["avoid_busy"],
            "details": True,
            "profile": preferences["profile"],
        }
        if post_fn is not None:
            route_kwargs["post_fn"] = post_fn
        if area_evs is not None:
            route_kwargs["area_evs"] = area_evs
        res = router(
            leg["points"],
            **route_kwargs,
        )
        coords_latlon = [(c[0], c[1]) for c in res["coords"]]
        seg_len = max(1500.0, res["distance_m"] / 25.0)
        avoid.extend(
            {"ring": r, "factor": 0.12 if is_climb else 0.30}
            for r in geo.corridor_polygons(coords_latlon, seg_len_m=seg_len, protect=protect)
        )
        leg_details.append(res.get("details", {}))
        if len(res["coords"]) >= 2:
            tail = res["coords"][-2], res["coords"][-1]
            prev_heading = _bearing((tail[0][0], tail[0][1]), (tail[1][0], tail[1][1]))
        total_m += res["distance_m"]
        ascend += res["ascend_m"]
        descend += res["descend_m"]
        computed_leg = {
                "from": leg["from"],
                "to": leg["to"],
                "km": round(res["distance_m"] / 1000, 2),
                "ascend_m": res["ascend_m"],
                "climb": leg.get("climb"),
                "coords": [[round(a, 6), round(b, 6), (round(e, 1) if e is not None else None)] for a, b, e in res["coords"]],
            }
        if leg.get("opvulling"):
            computed_leg["opvulling"] = True
        if leg.get("climb_segment"):
            computed_leg["climb_segment"] = leg["climb_segment"]
        computed_legs.append(computed_leg)

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
        d["computed"]["kwaliteit"] = analysis.route_stats(
            d["_geometry"], leg_details, profile=preferences["profile"]
        )
    except Exception as e:  # metriek mag routeren nooit blokkeren
        d["computed"]["kwaliteit"] = {"error": str(e)}
    save(d, expected_revision=expected_revision)
    return summary(d)


def summary(d: dict) -> dict:
    effective = routing_preferences(d)
    out = {
        "id": d["id"],
        "revision": int(d.get("revision", 0)),
        "name": d["name"],
        "start": d["start"].get("label"),
        "loop": d["loop"],
        "profile": effective["profile"],
        "strict": effective["strict"],
        "avoid_cobbles": effective["avoid_cobbles"],
        "avoid_concrete": effective["avoid_concrete"],
        "avoid_busy": effective["avoid_busy"],
        "avoid_places": d.get("avoid_places", []),
        "climbs": d["climbs"],
        "computed": d.get("computed"),
    }
    if d.get("profile_doc") is not None:
        out["profile_doc"] = d["profile_doc"]
    if config.load_registry() is not None:
        out["region"] = region_slug(d)
    return out


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


def _popular_share(routes: list[dict], cells=_LOAD_HEAT) -> float:
    if cells is _LOAD_HEAT:
        from . import heat

        cells = heat.popular_cells()
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

        busy_cells = heat.vlaanderen_data()["druk"]
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
) -> dict:
    from . import analysis

    return {
        "offroad": _route_share(routes, "road_class", analysis.OFFROAD_CLASSES),
        "populair": _popular_share(routes, popular_cells),
        "autovrij": _quiet_share(routes, busy_cells),
        "kassei": _route_share(routes, "surface", analysis.COBBLE_SURFACES),
    }


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
            if meta.get("climb") or meta.get("climb_segment"):
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

    return sorted(candidates)


def _candidates(d: dict, climb_db: dict, max_detour_km: float, limit: int,
                banned=frozenset(), router=gh.route, weighted: bool = False,
                popular_cells=_LOAD_HEAT) -> list[dict]:
    """Bereken kandidaat-klimmen dicht bij de huidige route."""
    candidates = _candidate_prefilter(d, climb_db, max_detour_km, banned=banned)
    legs_meta = d["computed"]["legs"]
    routing = routing_preferences(d)
    zones = place_areas(d)
    per_climb: dict[str, dict] = {}
    for _est, cid, c, leg_i, a, b in candidates[: max(24, limit * 4)]:
        try:
            preferences = {
                **routing,
            }
            if weighted:
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
        except gh.GhError:
            continue
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
        if weighted:
            suggestion["score_componenten"] = _candidate_surface_components(
                [r1, r2, r3], popular_cells
            )
        per_climb[cid] = suggestion
    out = sorted(per_climb.values(), key=lambda s: s["extra_km"])[:limit]
    return out


def probe(
    d: dict,
    climb_db: dict,
    router=gh.route,
    *,
    round_trip_fn=gh.round_trip,
) -> dict:
    """Routeer eenmaal en cache een compacte terreinverkenning op de draft."""
    if d.get("_probe") is not None:
        return d["_probe"]

    effective_profile = routing_preferences(d)["profile"]
    if d.get("loop") and not d.get("climbs"):
        preferences = routing_preferences(d)
        anchor, _anchor_label = _round_trip_anchor(d, climb_db)
        exploratory = round_trip_fn(
            anchor,
            15_000.0,
            0,
            avoid_polygons=place_areas(d),
            strict=preferences["strict"],
            avoid_cobbles=preferences["avoid_cobbles"],
            avoid_concrete=preferences["avoid_concrete"],
            avoid_busy=preferences["avoid_busy"],
            profile=preferences["profile"],
            details=True,
        )
        route_coords = [
            (point[0], point[1]) for point in exploratory.get("coords", [])
        ]
        sampled_route = geo.resample(route_coords, 500.0)
        from . import analysis

        try:
            quality = analysis.route_stats(
                [exploratory.get("coords", [])],
                [exploratory.get("details", {})],
                profile=preferences["profile"],
            )
        except Exception as exc:
            quality = {"error": str(exc)}
        route_km = round(exploratory.get("distance_m", 0) / 1000.0, 1)
        route_hm = round(exploratory.get("ascend_m", 0))
        nearby_climbs = {
            climb_id
            for climb_id, climb in climb_db.items()
            if route_coords
            and min(
                geo.haversine(point[0], point[1], climb["foot"][0], climb["foot"][1])
                for point in sampled_route
            )
            <= 5_000.0
        }
    else:
        route(d, climb_db, router=router)
        quality = copy.deepcopy(d["computed"].get("kwaliteit") or {})
        route_coords = [
            (point[0], point[1])
            for leg in d.get("_geometry", [])
            for point in leg
        ]
        route_km = d["computed"]["total_km"]
        route_hm = d["computed"]["ascend_m"]
        nearby_climbs = {
            candidate[1]
            for candidate in _candidate_prefilter(d, climb_db, max_detour_km=5.0)
        }
    from . import heat

    route_features = heat.features_near_route(route_coords)
    poi_counts = {}
    for poi in route_features["pois"]:
        poi_type = poi["type"]
        poi_counts[poi_type] = poi_counts.get(poi_type, 0) + 1
    walking_popularity_available = (
        effective_profile == "trail"
        and heat.popular_cells("trail", fallback=False) is not None
    )
    busy_data_available = bool(heat.vlaanderen_data()["druk"])
    try:
        from . import geocode

        place_cores = geocode.places_near_route(route_coords, radius_m=400.0)
    except RuntimeError:
        # Een route kan uit een cassette of minimale installatie komen zonder
        # gazetteer; readiness blijft dan bruikbaar voor de andere vragen.
        place_cores = []

    result = {
        "km": route_km,
        "hm": route_hm,
        "kwaliteit": quality,
        "terrein": {
            "kassei_aanwezig_m": quality.get("kassei_m", 0),
            "beton_m": quality.get("beton_m", 0),
            "offroad_beschikbaar_pct": quality.get("offroad_pct", 0),
            "klimmen_binnen_5km": len(nearby_climbs),
            "heat_dekking_pct": quality.get("populair_pct"),
            "wandelpopulariteit_beschikbaar": walking_popularity_available,
            "autovrij_pct": quality.get("autovrij_pct"),
            "druk_data_beschikbaar": busy_data_available,
            "plaatskernen": place_cores,
            "pois_langs_route": dict(sorted(poi_counts.items())),
            "knooppunten_langs_route": len(route_features["knopen"]),
        },
    }
    d["_probe"] = result
    save(d)
    return result


def suggest(d: dict, climb_db: dict, max_detour_km: float = 10.0, limit: int = 5,
            router=gh.route) -> list[dict]:
    """Klimmen dicht bij de huidige route, gerangschikt op extra kilometers."""
    with region_scope(d):
        if not d.get("profile_doc"):
            return _candidates(d, climb_db, max_detour_km, limit, router=router)
        profile_document = profiles.load(d["profile_doc"])
        candidates = _candidates(
            d,
            climb_db,
            max_detour_km,
            max(10, limit),
            router=router,
            weighted=True,
        )
        weights = profile_document["gewichten"]
        prefer_cobbles = profile_document["voorkeuren"]["kasseien"] == "graag"
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
    if objective in ("hm-per-km", "toeren", _LEGACY_HM):
        return None
    if objective == "hm":
        objective = {"hoogtemeters": 1.0}
    elif objective == "offroad":
        objective = {"offroad": 1.0}
    if not isinstance(objective, dict):
        raise DraftError(
            "objective moet 'hm', 'hm-per-km', 'offroad', 'toeren' "
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
                      prefer_cobbles: bool = False) -> dict | None:
    """Kies deterministisch de beste kandidaat voor het gevraagde doel."""
    weights = _objective_weights(objective)
    if not candidates:
        return None
    budget_km = budget_km if budget_km is not None else max(
        candidate["extra_km"] for candidate in candidates
    )

    def key(candidate):
        extra_km = candidate["extra_km"]
        gain = candidate["extra_hoogtemeters"]
        ratio = gain / max(extra_km, 0.3)
        if weights is None:
            primary = gain if objective == _LEGACY_HM else ratio
        else:
            components = _score_components(candidate, budget_km)
            primary = sum(weights[name] * components[name] for name in profiles.WEIGHT_KEYS)
            if prefer_cobbles:
                primary += 0.15 * components["kassei"]
            candidate["score"] = round(primary, 6)
            candidate["score_componenten"] = components
        return (-primary, -gain, extra_km, candidate["climb"]["id"])

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
    for leg in _waypoints(base, climb_db):
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


def _fill_with_round_trip(d: dict, climb_db: dict, budget_m: float,
                          router=route, round_trip_fn=gh.round_trip,
                          objective="hm", prefer_cobbles: bool = False,
                          popular_cells=_LOAD_HEAT,
                          target_total_m: float | None = None) -> dict:
    """Vul restbudget met de beste van vijf niet-overlappende GH-rondritten."""
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
    preferences = {
        **routing_preferences(d),
        "avoid_polygons": place_areas(d),
    }
    candidates = []
    for seed in range(5):
        try:
            candidate = round_trip_fn(
                anchor,
                requested_m,
                seed,
                details=(weights is not None),
                **preferences,
            )
        except gh.GhError:
            continue
        coords = [(point[0], point[1]) for point in candidate.get("coords", [])]
        if len(coords) < 2 or current_m + candidate["distance_m"] > budget_m:
            continue
        if existing and max(
            geo.retrace_m(existing, coords),
            geo.retrace_m(existing, list(reversed(coords))),
            geo.retrace_m(coords, existing),
            geo.retrace_m(list(reversed(coords)), existing),
        ) > 300.0:
            continue
        if weights is None:
            # Ook hm-per-km koos vóór T11 de rondritlob op absolute stijging.
            score = candidate.get("ascend_m", 0)
        else:
            surface = _candidate_surface_components([candidate], popular_cells)
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

    if not candidates:
        return {
            "filled": False,
            "reason": "geen round_trip-kandidaat zonder overlap binnen budget",
        }

    before = copy.deepcopy(d)
    for _ascend, _seed_order, seed, candidate, coords in sorted(candidates, reverse=True):
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
        if d["computed"]["total_km"] * 1000.0 <= budget_m:
            return {
                "filled": True,
                "seed": seed,
                "extra_km": round(d["computed"]["total_km"] - current_m / 1000.0, 1),
                "extra_hoogtemeters": round(
                    d["computed"]["ascend_m"] - before["computed"]["ascend_m"]
                ),
            }
        d.clear()
        d.update(copy.deepcopy(before))

    return {
        "filled": False,
        "reason": "round_trip-kandidaten overschrijden budget na integratie",
    }


def optimize(d: dict, climb_db: dict, max_km: float, objective=None,
             min_ratio: float = 8.0, max_rounds: int = 12,
             route_fn=route, candidates_fn=_candidates, fill: bool = True,
             round_trip_fn=gh.round_trip,
             fill_target_km: float | None = None) -> dict:
    with region_scope(d):
        return _optimize(
            d, climb_db, max_km, objective, min_ratio, max_rounds,
            route_fn=route_fn,
            candidates_fn=candidates_fn,
            fill=fill,
            round_trip_fn=round_trip_fn,
            fill_target_km=fill_target_km,
        )


def _optimize(d: dict, climb_db: dict, max_km: float, objective=None,
              min_ratio: float = 8.0, max_rounds: int = 12,
              route_fn=route, candidates_fn=_candidates, fill: bool = True,
              round_trip_fn=gh.round_trip,
              fill_target_km: float | None = None) -> dict:
    """Vul een draft greedy met klimmen binnen een hard afstandsbudget."""
    if max_km <= 0:
        raise DraftError("max-km moet groter dan 0 zijn")
    if min_ratio < 0:
        raise DraftError("min-ratio mag niet negatief zijn")
    if max_rounds < 0:
        raise DraftError("max-rounds mag niet negatief zijn")
    if fill_target_km is not None and fill_target_km <= 0:
        raise DraftError("fill-target-km moet groter dan 0 zijn")
    if fill_target_km is not None and fill_target_km > max_km:
        raise DraftError("fill-target-km mag het afstandsbudget niet overschrijden")
    objective = objective_for_draft(d, objective)
    # Valideer ook als er door max_rounds=0 geen kandidaat gekozen wordt.
    weights = _objective_weights(objective)
    profile_document = profiles.load(d["profile_doc"]) if d.get("profile_doc") else None
    prefer_cobbles = bool(
        profile_document
        and profile_document["voorkeuren"]["kasseien"] == "graag"
    )
    _select_candidate([], objective, prefer_cobbles=prefer_cobbles)
    pure_offroad = weights is not None and weights["offroad"] == 1.0
    tour_only = objective == "toeren"

    if not d["climbs"] and d.get("loop"):
        # Offroad en een gewone toer jagen niet op klimmen: meteen opvullen.
        anchor = (
            None
            if pure_offroad or tour_only
            else _pick_anchor(d["start"], climb_db, max_km)
        )
        if anchor is None:
            if not fill:
                raise DraftError("geen klim bereikbaar binnen het budget")
            d["computed"] = {
                "routed_at": time.strftime("%Y-%m-%d %H:%M"),
                "total_km": 0.0,
                "ascend_m": 0,
                "descend_m": 0,
                "legs": [],
                "kwaliteit": {"heen_en_weer_m": 0},
            }
            d["_geometry"] = []
        else:
            d["climbs"].append(anchor["id"])
            d["computed"] = None
            d.pop("_geometry", None)

    if not d.get("computed") or (not d.get("_geometry") and d["climbs"]):
        route_fn(d, climb_db)
    if d["computed"]["total_km"] > max_km:
        raise DraftError(
            f"huidige route is {d['computed']['total_km']:.1f} km en overschrijdt "
            f"het budget van {max_km:.1f} km"
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
    for round_number in range(1, max_rounds + 1):
        budget_km = max_km - d["computed"]["total_km"]
        if budget_km < 1.0:
            stopped_because = "minder dan 1 km budget over"
            break
        if not d["climbs"] and not d.get("_geometry"):
            stopped_because = "geen klim bereikbaar; round_trip vanaf start"
            break

        candidate_kwargs = {
            "max_detour_km": budget_km * 0.85,
            "limit": 10,
            "banned": frozenset(banned),
        }
        if weights is not None:
            import inspect

            if "weighted" in inspect.signature(candidates_fn).parameters:
                candidate_kwargs["weighted"] = True
        candidates = candidates_fn(d, climb_db, **candidate_kwargs)
        eligible = _eligible_candidates(candidates, budget_km, min_ratio, banned)
        selected = _select_candidate(
            eligible,
            objective,
            budget_km=budget_km,
            prefer_cobbles=prefer_cobbles,
        )
        if selected is None:
            stopped_because = "geen kandidaten boven min-ratio binnen budget"
            break

        climb_id = selected["climb"]["id"]
        position = selected["invoegen_op_positie"]
        prev_retrace = (d["computed"].get("kwaliteit") or {}).get("heen_en_weer_m", 0)
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
        new_retrace = (d["computed"].get("kwaliteit") or {}).get("heen_en_weer_m", 0)
        if d["computed"]["total_km"] > max_km:
            round_result["status"] = "teruggedraaid (budget)"
            d["climbs"].pop(position)
            d["computed"] = None
            d.pop("_geometry", None)
            banned.add(climb_id)
            route_fn(d, climb_db)
            save(d)
        elif new_retrace - prev_retrace > 120:
            # de toevoeging maakte de lus heen-en-weer-achtig: terugdraaien
            round_result["status"] = "teruggedraaid (heen-en-weer)"
            round_result["heen_en_weer_delta_m"] = round(new_retrace - prev_retrace)
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

    remaining_m = (max_km - d["computed"]["total_km"]) * 1000.0
    if fill and d.get("loop") and remaining_m >= 1500.0:
        fill_result = _fill_with_round_trip(
            d,
            climb_db,
            max_km * 1000.0,
            router=route_fn,
            round_trip_fn=round_trip_fn,
            objective=objective,
            prefer_cobbles=prefer_cobbles,
            target_total_m=(
                fill_target_km * 1000.0 if fill_target_km is not None else None
            ),
        )
        if fill_result["filled"]:
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
        save(d)

    return {
        "id": d["id"],
        "objective": "hm" if objective == _LEGACY_HM else objective,
        "max_km": float(max_km),
        "resultaat": summary(d),
        "rondes": rounds,
        "gestopt_omdat": stopped_because,
    }
