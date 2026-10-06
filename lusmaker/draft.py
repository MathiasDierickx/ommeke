"""Draft-routes: opbouwen, routeren (met lus-constraint), suggesties, opslag."""
import copy
import os
from concurrent.futures import ThreadPoolExecutor
from contextvars import copy_context
from itertools import islice
import fcntl
import inspect
import json
import re
import time
import uuid
from contextlib import contextmanager

from . import climbs as climbs_mod
from .errors import DraftError
from . import aws_state, config, geo, gh, profiles


PROFILES = ("quiet", "trail")
_DRAFT_ID_RE = re.compile(r"^[A-Za-z0-9_-]{1,64}$")
_LEGACY_HM = "__legacy_hm__"
# Vlak: een toer die niet naar klimmen zoekt en bij het opvullen de rondrit
# met de laagste stijging per km kiest (afstandsdoel blijft voorgaan).
FLAT = "vlak"
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
        from .route_library import summary_metadata
        try:
            aws_state.put_json(
                relative,
                d,
                etag=etag,
                create_only=current is None,
                metadata=summary_metadata(d),
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
        "water_via": [],  # persistente via-punten op een benoemde waterloop
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
    from . import coverage, geocode

    with config.use_region(region):
        start_point, alternatives = geocode.resolve(start)
        coverage.check_point(start_point, "startpunt")
        end_point = geocode.resolve(end)[0] if end else None
        if end_point is not None:
            coverage.check_point(end_point, "eindpunt")
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


def _project_on_line(start, a, b) -> tuple[float, float]:
    """Projecteer een punt lokaal vlak op een kort lat/lon-lijnstuk."""
    import math

    lon_scale = math.cos(math.radians((a[0] + b[0] + start[0]) / 3.0))
    ax = (a[1] - start[1]) * lon_scale
    ay = a[0] - start[0]
    bx = (b[1] - start[1]) * lon_scale
    by = b[0] - start[0]
    dx, dy = bx - ax, by - ay
    denominator = dx * dx + dy * dy
    position = 0.0 if denominator == 0 else -(ax * dx + ay * dy) / denominator
    position = max(0.0, min(1.0, position))
    return (
        a[0] + (b[0] - a[0]) * position,
        a[1] + (b[1] - a[1]) * position,
    )


def _trim_path(path, distance_m: float) -> list[tuple[float, float]]:
    out = [path[0]]
    traversed = 0.0
    for a, b in zip(path, path[1:]):
        length = geo.haversine(a[0], a[1], b[0], b[1])
        if length <= 0:
            continue
        if traversed + length >= distance_m:
            position = (distance_m - traversed) / length
            out.append(
                (
                    a[0] + (b[0] - a[0]) * position,
                    a[1] + (b[1] - a[1]) * position,
                )
            )
            break
        out.append(b)
        traversed += length
    return out


def _point_along_path(path, distance_m: float) -> tuple[float, float]:
    traversed = 0.0
    for a, b in zip(path, path[1:]):
        length = geo.haversine(a[0], a[1], b[0], b[1])
        if length <= 0:
            continue
        if traversed + length >= distance_m:
            position = (distance_m - traversed) / length
            return (
                a[0] + (b[0] - a[0]) * position,
                a[1] + (b[1] - a[1]) * position,
            )
        traversed += length
    return path[-1]


def water_via_points(
    start_latlon, segments, target_km, *, max_points=8
) -> list[tuple[float, float]]:
    """Kies deterministische via-punten vanaf de dichtste waterlooplocatie."""
    if not segments or target_km <= 0 or max_points <= 0:
        return []

    start = tuple(start_latlon)
    best = None
    for segment_index, raw_segment in enumerate(segments):
        segment = [tuple(point) for point in raw_segment]
        if not segment:
            continue
        if len(segment) == 1:
            projected = segment[0]
            candidates = [(-1, projected)]
        else:
            candidates = [
                (point_index, _project_on_line(start, a, b))
                for point_index, (a, b) in enumerate(zip(segment, segment[1:]))
            ]
        for point_index, projected in candidates:
            key = (
                geo.haversine(start[0], start[1], projected[0], projected[1]),
                segment_index,
                point_index,
            )
            if best is None or key < best[0]:
                best = (key, segment, point_index, projected)
    if best is None:
        return []

    _key, segment, point_index, projected = best
    if point_index < 0:
        path = [projected]
    else:
        forward = [projected, *segment[point_index + 1 :]]
        backward = [projected, *reversed(segment[: point_index + 1])]
        # Bij gelijke lengte wint de oorspronkelijke OSM-richting.
        path = (
            forward
            if geo.path_length(forward) >= geo.path_length(backward)
            else backward
        )
    available_m = geo.path_length(path)
    travel_m = min(target_km * 500.0, available_m)
    if travel_m <= 0:
        return [projected]
    path = _trim_path(path, travel_m)
    if max_points == 1:
        return [path[-1]]
    return [
        _point_along_path(path, travel_m * index / (max_points - 1))
        for index in range(max_points)
    ]


def _waypoints(d: dict, climb_db: dict) -> list[dict]:
    """Reeks legs; een klim-leg krijgt [voet, midden, top] zodat de route
    effectief de helling zelf omhoog rijdt."""
    start = (d["start"]["lat"], d["start"]["lon"])
    legs = []
    prev_label, prev_pt = "start", start
    water_via = [tuple(point) for point in d.get("water_via", [])]
    if water_via:
        points = [start]
        for point in water_via:
            if point != points[-1]:
                points.append(point)
        legs.append(
            {
                "from": "start",
                "to": "waterloop",
                "points": points,
            }
        )
        prev_label, prev_pt = "waterloop", water_via[-1]
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
    round_anchor = None if water_via else d.get("round_trip_anchor")
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
    ] + d.get("reroute_avoid", [])


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
        effective.update(profiles.routing_prefs(
            profiles.load(d["profile_doc"]),
            (d.get("route_request") or {}).get("activiteit"),
        ))
        # Het opgeslagen sportprofiel is bij creatie al van het document
        # afgeleid; een expliciet afwijkend draftprofiel blijft leidend.
        if d.get("profile_override", False):
            effective["profile"] = d.get("profile", effective["profile"])
    for key in ("strict", "avoid_cobbles", "avoid_concrete", "avoid_busy"):
        if d.get(key, False):
            effective[key] = True
    explicit = (d.get("route_request") or {}).get("expliciete_voorkeuren") or {}
    # Antwoorden op de situationele vragen gelden voor deze rit.
    if explicit.get("oversteken") == "vermijd":
        effective["strict"] = True
    return effective


def prefers_cycleways(d: dict) -> bool:
    """Fietspaden zijn belangrijk (antwoord op de rit, anders het profiel)."""
    request = d.get("route_request") or {}
    explicit = (request.get("expliciete_voorkeuren") or {}).get("fietspaden")
    if explicit is not None:
        return explicit == "belangrijk"
    if not d.get("profile_doc"):
        return False
    try:
        preferences = profiles.effective_preferences(
            profiles.load(d["profile_doc"]), request.get("activiteit")
        )
    except profiles.ProfileError:
        return False
    return preferences.get("fietspaden") == "belangrijk"


def _heat_activity(d: dict) -> str | None:
    request = d.get("route_request") or {}
    if "heat_activity" in request:
        return request["heat_activity"]
    from .intents import heat_activity_for

    return heat_activity_for(
        request.get("activiteit"),
        request.get("profiel_naam") or d.get("profile_doc"),
    )


def _activity_kwargs(d: dict) -> dict:
    """Routeerargumenten voor de activiteit; leeg bij oudere drafts."""
    activity = (d.get("route_request") or {}).get("activiteit")
    kwargs = {"activity": activity} if activity else {}
    if prefers_cycleways(d):
        kwargs["prefer_cycleways"] = True
    return kwargs


def _prefers_cobbles(d: dict, profile_document: dict) -> bool:
    request = d.get("route_request") or {}
    activity = request.get("activiteit")
    preferences = profiles.effective_preferences(profile_document, activity)
    explicit = (request.get("expliciete_voorkeuren") or {}).get("kasseien")
    return (explicit or preferences["kasseien"]) == "graag"


def objective_for_draft(d: dict, objective):
    """Gebruik profielgewichten tenzij de aanroep een objective overschrijft."""
    if objective is not None:
        return objective
    if d.get("profile_doc"):
        return profiles.load(d["profile_doc"])["gewichten"]
    if d.get("route_request"):
        # Nieuwe verzoeken klimmen alleen op uitdrukkelijke wens; zonder
        # profiel is een neutrale rondrit de redelijke standaard.
        return "toeren"
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


def _leg_hints_headings(leg: dict, prev_heading: float | None):
    """Bepaal point_hints en headings voor de finale routering van één leg.

    Beide lijsten hebben exact evenveel items als `leg["points"]` (GraphHopper
    weigert een mismatch) of zijn None. Hints: straatnaam per punt, "" =
    geen hint. Headings: None = geen voorkeur. Een klim-leg vertrekt in de
    klimrichting (bergop); andere legs vertrekken in de aankomstrichting van
    de vorige leg.
    """
    points = leg["points"]
    n = len(points)
    hints = leg.get("hints")
    if not hints or len(hints) != n or not any(hints):
        hints = None
    else:
        hints = list(hints)
    start_heading = None
    if "climb" in leg and n >= 2:
        start_heading = _bearing(tuple(points[0]), tuple(points[1]))
    elif prev_heading is not None:
        start_heading = prev_heading
    headings = None
    if start_heading is not None and n >= 2:
        headings = [round(start_heading, 1)] + [None] * (n - 1)
    return hints, headings


def _route(
    d: dict,
    climb_db: dict,
    router=gh.route,
    *,
    post_fn=None,
    area_evs: set[str] | frozenset[str] | None = None,
    expected_revision: int | None = None,
    save_fn=save,
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
    cues = []
    computed_legs = []
    total_m = ascend = descend = 0.0
    preferences = routing_preferences(d)
    prev_heading: float | None = None

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
            "heat_activity": _heat_activity(d),
            **_activity_kwargs(d),
        }
        if router is gh.route:
            route_kwargs["instructions"] = True
        hints, headings = _leg_hints_headings(leg, prev_heading)
        if hints is not None:
            route_kwargs["point_hints"] = hints
        if headings is not None:
            route_kwargs["headings"] = headings
        if post_fn is not None:
            route_kwargs["post_fn"] = post_fn
        if area_evs is not None:
            route_kwargs["area_evs"] = area_evs
        res = router(
            leg["points"],
            **route_kwargs,
        )
        for instruction in res.get("instructions", []):
            if instruction.get("sign") in (4, 5):
                continue  # leg-eindes zijn geen eindpunt van de volledige route
            interval = instruction.get("interval", [])
            if interval and 0 <= interval[0] < len(res["coords"]):
                pt = res["coords"][interval[0]]
                cues.append({"lat": pt[0], "lon": pt[1], "text": instruction.get("text", "Volg de route"), "sign": instruction.get("sign", 0)})
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
    d["cues"] = cues
    d["_geometry"] = [leg["coords"] for leg in computed_legs]
    from . import analysis

    try:
        d["computed"]["kwaliteit"] = analysis.route_stats(
            d["_geometry"], leg_details, profile=preferences["profile"]
        )
    except Exception as e:  # metriek mag routeren nooit blokkeren
        d["computed"]["kwaliteit"] = {"error": str(e)}
    save_fn(d, expected_revision=expected_revision)
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
            heat_activity=_heat_activity(d),
            **_activity_kwargs(d),
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
            "fietspad_pct": quality.get("fietspad_pct"),
            "klimmen_binnen_5km": len(nearby_climbs),
            "heat_dekking_pct": quality.get("populair_pct"),
            "wandelpopulariteit_beschikbaar": walking_popularity_available,
            "autovrij_pct": quality.get("autovrij_pct"),
            "druk_data_beschikbaar": busy_data_available,
            "plaatskernen": place_cores,
            "pois_langs_route": dict(sorted(poi_counts.items())),
            "voorzieningen_details": [
                {key: p.get(key) for key in ("type", "naam", "lat", "lon", "afstand_m",
                                           "wheelchair", "opening_hours", "changing_table", "fee", "access")}
                for p in route_features["pois"][:20]
            ],
            "knooppunten_langs_route": len(route_features["knopen"]),
        },
    }
    d["_probe"] = result
    save(d)
    return result




# Backward-compatible optimizer exports.
from .optimizer import (
    FLAT, MAX_EXACT_CANDIDATES, OPTIMIZE_TIME_BUDGET_S,
    _candidate_prefilter, _candidate_surface_components, _candidates,
    _eligible_candidates, _fill_with_round_trip, _friendly_stop_reason,
    _objective_weights, _optimize, _pick_anchor, _router_concurrency,
    _router_results, _round_trip_anchor, _score_components, _select_candidate,
    _target_tolerance_m, optimize, suggest,
)
pick_anchor = _pick_anchor
