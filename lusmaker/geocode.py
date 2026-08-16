"""Lokale geocoder op basis van OSM-plaatsen en straatnamen."""
import pickle
import re
import unicodedata
import warnings

from . import config, geo, google_geocode

PLACE_PRIO = {"city": 0, "town": 1, "municipality": 2, "village": 3, "suburb": 4, "hamlet": 5}


def _load():
    if not config.GAZETTEER_PKL.exists():
        raise RuntimeError("gazetteer ontbreekt — draai eerst `lus build`")
    with open(config.GAZETTEER_PKL, "rb") as f:
        gazetteer = pickle.load(f)
    if "landmarks" not in gazetteer:
        warnings.warn(
            "gazetteer bevat nog geen landmarks — draai `lus build --force`",
            RuntimeWarning,
            stacklevel=2,
        )
        gazetteer["landmarks"] = []
    if "waterways" not in gazetteer:
        warnings.warn(
            "gazetteer bevat nog geen waterlopen — draai `lus build --force`",
            RuntimeWarning,
            stacklevel=2,
        )
        gazetteer["waterways"] = {}
    return gazetteer


def _normalise(value: str) -> str:
    value = unicodedata.normalize("NFKD", value.casefold())
    value = "".join(char for char in value if not unicodedata.combining(char))
    return " ".join(re.findall(r"[a-z0-9]+", value))


def _match_places(places, q):
    ql = _normalise(q)
    out = []
    for name, ptype, lat, lon in places:
        nl = _normalise(name)
        if nl == ql:
            rank = 0
        elif nl.startswith(ql):
            rank = 1
        elif ql in nl:
            rank = 2
        else:
            continue
        out.append((rank, PLACE_PRIO.get(ptype, 9), name, ptype, lat, lon))
    out.sort()
    return [{"label": n, "type": t, "lat": la, "lon": lo} for _r, _p, n, t, la, lo in out]


def _match_landmarks(landmarks, q):
    ql = _normalise(q)
    out = []
    for name, kind, lat, lon in landmarks:
        nl = _normalise(name)
        if nl == ql:
            rank = 0
        elif nl.startswith(ql):
            rank = 1
        elif ql in nl:
            rank = 2
        else:
            continue
        out.append((rank, name.casefold(), name, kind, lat, lon))
    out.sort()
    return [
        {"label": name, "type": "landmark", "kind": kind, "lat": lat, "lon": lon}
        for _rank, _sort_name, name, kind, lat, lon in out
    ]


def _cluster(points, radius_m=1200.0):
    clusters = []
    for lat, lon, name in points:
        placed = False
        for c in clusters:
            if geo.haversine(lat, lon, c["lat"], c["lon"]) < radius_m:
                c["n"] += 1
                placed = True
                break
        if not placed:
            clusters.append({"lat": lat, "lon": lon, "name": name, "n": 1})
    return clusters


def _nearest_place(places, lat, lon):
    best = None
    for name, ptype, plat, plon in places:
        if PLACE_PRIO.get(ptype, 9) > 3:
            continue
        d = geo.haversine(lat, lon, plat, plon)
        if best is None or d < best[0]:
            best = (d, name)
    return best[1] if best else None


def waterway_segments(
    name: str, gazetteer=None
) -> list[list[tuple[float, float]]]:
    """Geef alle OSM-segmenten van een exact benoemde waterloop."""
    gaz = _load() if gazetteer is None else gazetteer
    return gaz.get("waterways", {}).get(_normalise(name), [])


def places_near_route(route_coords, radius_m: float = 400.0, gazetteer=None) -> list[dict]:
    """Geef plaatsnodes die binnen ``radius_m`` van een route liggen.

    ``gazetteer`` is injecteerbaar zodat readiness-detectie volledig offline
    met synthetische data getest kan worden.
    """
    if radius_m < 0:
        raise ValueError("radius_m mag niet negatief zijn")
    gaz = _load() if gazetteer is None else gazetteer
    route = [(point[0], point[1]) for point in route_coords]
    if not route:
        return []
    sampled = geo.resample(route, 50.0)
    nearby = []
    for name, ptype, lat, lon in gaz.get("places", []):
        distance_m = min(
            geo.haversine(lat, lon, route_lat, route_lon)
            for route_lat, route_lon in sampled
        )
        if distance_m <= radius_m:
            nearby.append(
                {
                    "label": name,
                    "type": ptype,
                    "lat": lat,
                    "lon": lon,
                    "afstand_m": round(distance_m),
                }
            )
    return sorted(
        nearby,
        key=lambda place: (place["afstand_m"], place["label"].casefold(), place["type"]),
    )


def geocode(query: str, limit: int = 5, gazetteer=None) -> list[dict]:
    gaz = _load() if gazetteer is None else gazetteer
    landmarks = gaz.get("landmarks", [])
    parts = [p.strip() for p in query.split(",") if p.strip()]
    # huisnummers wegstrippen
    street_q = re.sub(r"\b\d+[a-zA-Z]?\b", "", parts[0]).strip() if parts else ""

    if len(parts) == 1:
        landmark_hits = _match_landmarks(landmarks, parts[0])
        exact_landmarks = [
            hit
            for hit in landmark_hits
            if _normalise(hit["label"]) == _normalise(parts[0])
        ]
        if exact_landmarks:
            return exact_landmarks[:limit]
        pts = gaz["streets"].get(street_q.lower(), [])
        out = []
        for c in _cluster(pts):
            place = _nearest_place(gaz["places"], c["lat"], c["lon"])
            out.append({"label": f"{c['name']}, {place}" if place else c["name"],
                        "type": "street", "lat": c["lat"], "lon": c["lon"]})
        if out:
            return out[:limit]
        place_hits = _match_places(gaz["places"], parts[0])
        if place_hits:
            return place_hits[:limit]
        return landmark_hits[:limit]

    # "straat, plaats"
    place_hits = _match_places(gaz["places"], parts[-1])
    if not place_hits:
        return []
    p0 = place_hits[0]
    landmark_hits = _match_landmarks(landmarks, parts[0])
    exact_landmarks = [
        hit
        for hit in landmark_hits
        if _normalise(hit["label"]) == _normalise(parts[0])
    ]
    if exact_landmarks:
        landmark_hits = exact_landmarks
    nearby_landmarks = [
        hit
        for hit in landmark_hits
        if geo.haversine(hit["lat"], hit["lon"], p0["lat"], p0["lon"]) < 8000
    ]
    if nearby_landmarks:
        return nearby_landmarks[:limit]
    pts = gaz["streets"].get(street_q.lower(), [])
    near = [(la, lo, nm) for la, lo, nm in pts if geo.haversine(la, lo, p0["lat"], p0["lon"]) < 6000]
    out = []
    for c in _cluster(near):
        out.append({"label": f"{c['name']}, {p0['label']}", "type": "street",
                    "lat": c["lat"], "lon": c["lon"]})
    if not out:
        out = [dict(p0, note=f"straat '{street_q}' niet gevonden, plaats zelf gebruikt")]
    return out[:limit]


_DEFAULT_GOOGLE_RESOLVER = object()


def _is_generic_place_fallback(query: str, hits: list[dict]) -> bool:
    """Herken ``straat/POI niet gevonden, plaats zelf gebruikt`` als zwak."""
    if len(hits) != 1 or "note" not in hits[0]:
        return False
    parts = [part.strip() for part in query.split(",") if part.strip()]
    return (
        len(parts) > 1
        and hits[0].get("type") in PLACE_PRIO
        and _normalise(parts[0]) != _normalise(hits[0].get("label", ""))
    )


def resolve(
    query: str,
    *,
    gazetteer=None,
    google_resolver=_DEFAULT_GOOGLE_RESOLVER,
) -> tuple[dict, list[dict]]:
    """Los een plaatsnaam of ``lat,lon`` op tot één punt en alternatieven."""
    parts = query.split(",")
    if len(parts) == 2:
        try:
            lat, lon = float(parts[0]), float(parts[1])
            return {"lat": lat, "lon": lon, "label": query}, []
        except ValueError:
            pass

    hits = geocode(query, limit=5, gazetteer=gazetteer)
    if not hits or _is_generic_place_fallback(query, hits):
        resolver = (
            google_geocode.resolve
            if google_resolver is _DEFAULT_GOOGLE_RESOLVER
            else google_resolver
        )
        google_hit = resolver(query) if resolver is not None else None
        if google_hit is not None:
            return google_hit, hits[1:]
    if not hits:
        raise RuntimeError(
            f"'{query}' niet gevonden — probeer 'straat, plaats' of 'lat,lon'"
        )
    best = hits[0]
    return (
        {"lat": best["lat"], "lon": best["lon"], "label": best["label"]},
        hits[1:],
    )
