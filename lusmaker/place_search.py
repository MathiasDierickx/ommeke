"""Begrensde OSM-zoekopdracht voor plaatsen rond een bekend punt."""
from functools import lru_cache
import json
import math
import os
import time
from urllib.request import Request, urlopen
from urllib.parse import urlencode

from . import geo, config, geocode

FILTERS = {"parking": '["amenity"="parking"]', "hotel": '["tourism"="hotel"]',
           "beach": '["natural"="beach"]', "crossing": '["highway"="crossing"]'}


@lru_cache(maxsize=128)
def _fetch(query, hour):
    endpoint = os.environ.get("LUSMAKER_OVERPASS_URL", "https://overpass-api.de/api/interpreter")
    request = Request(endpoint, data=urlencode({"data": query}).encode(),
                      headers={"User-Agent": "Ommeke/0.1 (https://github.com/MathiasDierickx/ommeke; contact: mathias.dierickx@gmail.com)"})
    with urlopen(request, timeout=30) as response:
        payload = response.read(2_000_001)
    if len(payload) > 2_000_000:
        raise ValueError("plaatsresultaat is te groot; verklein de straal")
    result = json.loads(payload)
    if result.get("remark"):
        raise RuntimeError("OSM-zoekdienst gaf een onvolledig resultaat")
    return result


def nearby_places(lat, lon, kind, radius_m=500, *, fetch=None, local_places=None, source_places=None):
    if (any(isinstance(v, bool) or not isinstance(v, (int, float)) or not math.isfinite(v)
            for v in (lat, lon, radius_m)) or not -90 <= lat <= 90 or not -180 <= lon <= 180
            or not 1 <= radius_m <= 2000 or kind not in FILTERS):
        raise ValueError("ongeldig zoekpunt, soort of straal (1–2000 meter)")
    query = f'[out:json][timeout:20];nwr(around:{radius_m},{lat},{lon}){FILTERS[kind]};out tags center;'
    if source_places is None:
        source_places = []
        if kind == "hotel" and fetch is None and local_places is None:
            from . import tvl_places
            source_places = tvl_places.nearby(lat, lon, radius_m, kinds={"hotel"})
    if local_places is None:
        local_places = geocode._load().get("nearby_places", []) if fetch is None and config.GAZETTEER_PKL.exists() else []
    tag, value = {"parking": ("amenity", "parking"), "hotel": ("tourism", "hotel"),
                  "beach": ("natural", "beach"), "crossing": ("highway", "crossing")}[kind]
    local = [item for item in local_places if item.get("tags", {}).get(tag) == value
             and geo.haversine(lat, lon, item.get("center", item)["lat"], item.get("center", item)["lon"]) <= radius_m]
    payload = {"elements": local} if local or source_places else (fetch(query) if fetch else _fetch(query, int(time.time() // 3600)))
    candidates = [{**item, "tags": {"name": item["name"], "tourism": "hotel"}} for item in source_places]
    for item in payload.get("elements", []):
        position = item.get("center", item)
        if "lat" not in position or "lon" not in position:
            continue
        tags = item.get("tags", {})
        if any(geo.haversine(p['lat'], p['lon'], position['lat'], position['lon']) < 30
               and p.get('label', '').casefold() == tags.get('name', '').casefold() for p in candidates):
            continue
        candidates.append({"lat": position["lat"], "lon": position["lon"],
                           "label": tags.get("name", f"{kind} (OSM {item['type']} {item['id']})"),
                           "distance_m": round(geo.haversine(lat, lon, position["lat"], position["lon"])),
                           "tags": tags, "source": f"https://www.openstreetmap.org/{item['type']}/{item['id']}",
                           "coordinate_kind": "node" if item["type"] == "node" else "area_center"})
    candidates.sort(key=lambda item: item["distance_m"])
    return {"candidates": candidates[:10], "total": len(candidates),
            "data_mode": "local_tvl_and_osm" if source_places else ("local_osm_snapshot" if local else "overpass"),
            "attribution": "Toerisme Vlaanderen; © OpenStreetMap contributors (ODbL)" if source_places else "© OpenStreetMap contributors (ODbL)",
            "data_timestamp": payload.get("osm3s", {}).get("timestamp_osm_base"),
            "warning": "Kaartgegevens, geen actuele terreincontrole. Gebiedscentra zijn geen geverifieerde ingangen. Nabijheid bewijst geen verbinding; verifieer de route en oversteek apart."}
