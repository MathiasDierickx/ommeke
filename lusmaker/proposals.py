"""Kant-en-klare voorstellen bij een klaar resultaat (maximaal twee).

Fiets: een nabije klim met weinig omweg (``draft.suggest``). Te voet: een
park/groen als rond-plek of een waterloop om langs te lopen, uit de
gazetteer die er al is. Elk voorstel bevat de exacte ``adjust_route``
argumenten, zodat de UI en het taalmodel het zonder omweg kunnen uitvoeren.
Ontbreekt er iets zinnigs, dan blijft de lijst leeg.
"""

from __future__ import annotations

import math

from . import activities, draft, geo

MAX_PROPOSALS = 2
MAX_CLIMB_DETOUR_KM = 6.0
MIN_CLIMB_GAIN_M = 15
GREEN_KINDS = {"park", "nature_reserve", "garden", "common", "village_green", "recreation_ground"}
GREEN_RADIUS_M = 3500.0
WATER_RADIUS_M = 2500.0


def _fmt(value: float, digits: int = 1) -> str:
    return f"{value:.{digits}f}".replace(".", ",")


ROAD_FACTOR = 1.3  # hemelsbreed naar wegafstand; de echte meerprijs volgt bij toepassen


def estimate_climbs(d: dict, climb_db: dict, max_detour_km: float, limit: int) -> list[dict]:
    """Klimvoorstellen zonder routercalls.

    ``draft.suggest`` routeert tot 24 kandidaten x 4 legs (~1,7 s per call in
    productie); dat is te duur voor elk resultaat. Een voorstel mag een
    schatting zijn: het toepassen routeert exact.
    """
    best: dict[str, tuple] = {}
    for est, cid, climb, *_rest in draft._candidate_prefilter(d, climb_db, max_detour_km):
        if cid not in best or est < best[cid][0]:
            best[cid] = (est, climb)
    out = []
    for cid, (est, climb) in sorted(best.items(), key=lambda item: item[1][0]):
        extra_km = max(0.5, est / 1000 * ROAD_FACTOR)
        if extra_km > max_detour_km:
            continue
        out.append({"id": cid, "climb": {"name": climb.get("name") or cid},
                    "extra_km": round(extra_km, 1), "extra_hoogtemeters": round(float(climb.get("gain_m", 0)))})
        if len(out) >= limit:
            break
    return out


def _climb_proposals(d: dict, climb_db: dict, request: dict, suggest_fn) -> list[dict]:
    explicit = request.get("expliciete_voorkeuren") or {}
    if explicit.get("heuvels") == "vlak":
        return []
    km = (d.get("computed") or {}).get("total_km")
    if not isinstance(km, (int, float)):
        return []
    hard_max = request.get("max_km") if request.get("max_km_explicit") else None
    existing = set(d.get("climbs") or [])
    out = []
    for candidate in suggest_fn(d, climb_db, max_detour_km=MAX_CLIMB_DETOUR_KM, limit=4):
        climb_id = candidate.get("id") or (candidate.get("climb") or {}).get("id")
        extra_km = candidate.get("extra_km")
        gain = candidate.get("extra_hoogtemeters") or 0
        if not climb_id or climb_id in existing or extra_km is None:
            continue
        if gain < MIN_CLIMB_GAIN_M or extra_km > MAX_CLIMB_DETOUR_KM:
            continue
        new_km = km + max(extra_km, 0.0)
        if hard_max is not None and new_km > hard_max:
            continue
        name = (candidate.get("climb") or {}).get("name") or candidate.get("label") or climb_id
        out.append({
            "titel": f"Voeg {name} toe",
            "uitleg": f"Ongeveer {_fmt(extra_km)} km extra voor {gain:g} hoogtemeters erbij.",
            "adjust_route": {
                "voeg_klimmen_toe": [climb_id],
                "target_km": math.ceil(new_km + 0.5),
            },
            "_score": gain / max(extra_km, 0.3),
        })
    out.sort(key=lambda item: -item["_score"])
    return out


def _nearest_green(start: tuple, landmarks) -> dict | None:
    best = None
    for name, kind, lat, lon in landmarks:
        if kind not in GREEN_KINDS or not name:
            continue
        distance = geo.haversine(start[0], start[1], lat, lon)
        if distance <= GREEN_RADIUS_M and (best is None or distance < best[0]):
            best = (distance, name, kind)
    return {"naam": best[1], "kind": best[2], "afstand_m": best[0]} if best else None


def _nearest_water(start: tuple, waterways) -> dict | None:
    lat0, lon0 = start
    box = WATER_RADIUS_M / 111_000.0 * 1.5
    best = None
    for name, segments in waterways.items():
        for segment in segments:
            for point in segment:
                if abs(point[0] - lat0) > box or abs(point[1] - lon0) > box * 1.6:
                    continue
                distance = geo.haversine(lat0, lon0, point[0], point[1])
                if distance <= WATER_RADIUS_M and (best is None or distance < best[0]):
                    best = (distance, name)
    return {"naam": best[1], "afstand_m": best[0]} if best else None


def _foot_proposals(d: dict, request: dict, gazetteer_fn) -> list[dict]:
    km = (d.get("computed") or {}).get("total_km")
    start = d.get("start") or {}
    if not isinstance(km, (int, float)) or "lat" not in start:
        return []
    gazetteer = gazetteer_fn()
    point = (start["lat"], start["lon"])
    target = max(1, round(km))
    out = []
    green = None if request.get("rond_plaats") else _nearest_green(point, gazetteer.get("landmarks", []))
    if green:
        out.append({
            "titel": f"Wandel rond {green['naam']}",
            "uitleg": (
                f"Een groene lus rond {green['naam']}, ongeveer "
                f"{_fmt(green['afstand_m'] / 1000)} km van je start, met dezelfde afstand."
            ),
            "adjust_route": {"rond_plaats": green["naam"], "target_km": target},
        })
    water = None if request.get("langs_water") else _nearest_water(point, gazetteer.get("waterways", {}))
    if water:
        label = water["naam"].title()
        out.append({
            "titel": f"Langs het water: {label}",
            "uitleg": f"Een route die {label} volgt, vlak bij je start.",
            "adjust_route": {"langs_water": water["naam"], "target_km": target},
        })
    return out


def build(
    d: dict,
    climb_db: dict,
    request: dict | None = None,
    *,
    suggest_fn=estimate_climbs,
    gazetteer_fn=None,
    limit: int = MAX_PROPOSALS,
) -> list[dict]:
    """Geef hooguit ``limit`` voorstellen; bij fouten of niets zinnigs een lege lijst."""
    request = request or d.get("route_request") or {}
    if not d.get("computed") or not d.get("loop", True):
        return []
    try:
        if activities.is_foot(request.get("activiteit")):
            if gazetteer_fn is None:
                from . import geocode

                gazetteer_fn = geocode._load
            found = _foot_proposals(d, request, gazetteer_fn)
        else:
            found = _climb_proposals(d, climb_db, request, suggest_fn)
    except Exception:  # voorstellen zijn een extraatje; nooit het resultaat breken
        return []
    return [{k: v for k, v in item.items() if not k.startswith("_")} for item in found[:limit]]
