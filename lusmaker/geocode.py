"""Lokale geocoder op basis van OSM-plaatsen en straatnamen."""
import pickle
import re

from . import config, geo

PLACE_PRIO = {"city": 0, "town": 1, "municipality": 2, "village": 3, "suburb": 4, "hamlet": 5}


def _load():
    if not config.GAZETTEER_PKL.exists():
        raise RuntimeError("gazetteer ontbreekt — draai eerst `lus build`")
    with open(config.GAZETTEER_PKL, "rb") as f:
        return pickle.load(f)


def _match_places(places, q):
    ql = q.lower()
    out = []
    for name, ptype, lat, lon in places:
        nl = name.lower()
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


def geocode(query: str, limit: int = 5) -> list[dict]:
    gaz = _load()
    parts = [p.strip() for p in query.split(",") if p.strip()]
    # huisnummers wegstrippen
    street_q = re.sub(r"\b\d+[a-zA-Z]?\b", "", parts[0]).strip() if parts else ""

    if len(parts) == 1:
        hits = _match_places(gaz["places"], parts[0])
        if hits:
            return hits[:limit]
        pts = gaz["streets"].get(street_q.lower(), [])
        out = []
        for c in _cluster(pts):
            place = _nearest_place(gaz["places"], c["lat"], c["lon"])
            out.append({"label": f"{c['name']}, {place}" if place else c["name"],
                        "type": "street", "lat": c["lat"], "lon": c["lon"]})
        return out[:limit]

    # "straat, plaats"
    place_hits = _match_places(gaz["places"], parts[-1])
    if not place_hits:
        return []
    p0 = place_hits[0]
    pts = gaz["streets"].get(street_q.lower(), [])
    near = [(la, lo, nm) for la, lo, nm in pts if geo.haversine(la, lo, p0["lat"], p0["lon"]) < 6000]
    out = []
    for c in _cluster(near):
        out.append({"label": f"{c['name']}, {p0['label']}", "type": "street",
                    "lat": c["lat"], "lon": c["lon"]})
    if not out:
        out = [dict(p0, note=f"straat '{street_q}' niet gevonden, plaats zelf gebruikt")]
    return out[:limit]


def resolve(query: str) -> tuple[dict, list[dict]]:
    """Los een plaatsnaam of ``lat,lon`` op tot één punt en alternatieven."""
    parts = query.split(",")
    if len(parts) == 2:
        try:
            lat, lon = float(parts[0]), float(parts[1])
            return {"lat": lat, "lon": lon, "label": query}, []
        except ValueError:
            pass

    hits = geocode(query, limit=5)
    if not hits:
        raise RuntimeError(
            f"'{query}' niet gevonden — probeer 'straat, plaats' of 'lat,lon'"
        )
    best = hits[0]
    return (
        {"lat": best["lat"], "lon": best["lon"], "label": best["label"]},
        hits[1:],
    )
