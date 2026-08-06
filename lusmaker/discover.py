"""Globale plaats- en Geofabrik-regioresolutie met lokale caches."""
from __future__ import annotations

import json
import os
import time
import urllib.request
from pathlib import Path
from typing import Callable
from urllib.parse import urlencode, urlparse

from . import config, geo


NOMINATIM_URL = "https://nominatim.openstreetmap.org/search"
GEOFABRIK_INDEX_URL = "https://download.geofabrik.de/index-v1.json"
USER_AGENT = "lusmaker/0.1"
DEFAULT_MAX_PBF_MB = 700

_last_nominatim_request = 0.0


def _cache_path(filename: str, home: Path | None = None) -> Path:
    return (home or config.home_path()) / "cache" / filename


def _read_json(path: Path, default):
    if not path.exists():
        return default
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise RuntimeError(f"ongeldige cache: {path}") from exc


def _write_json(path: Path, value) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(
        json.dumps(value, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    temporary.replace(path)


def _fetch_json(url: str, headers: dict[str, str] | None = None):
    request = urllib.request.Request(url, headers=headers or {})
    with urllib.request.urlopen(request, timeout=30) as response:
        return json.load(response)


def _fetch_size(url: str) -> int | None:
    """Bestandsgrootte opvragen; Geofabriks squid weigert soms HEAD, dus val
    terug op een Range-GET en desnoods op 'onbekend' (None)."""
    request = urllib.request.Request(
        url, method="HEAD", headers={"User-Agent": USER_AGENT}
    )
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            value = response.headers.get("Content-Length")
        if value:
            return int(value)
    except OSError:
        pass
    request = urllib.request.Request(
        url, headers={"User-Agent": USER_AGENT, "Range": "bytes=0-0"}
    )
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            content_range = response.headers.get("Content-Range", "")
        if "/" in content_range:
            total = content_range.rsplit("/", 1)[1]
            if total.isdigit():
                return int(total)
    except OSError:
        pass
    return None


def _call_fetch(fetch: Callable, url: str):
    """Call a test-friendly fetcher and normalize JSON bytes/strings."""
    try:
        value = fetch(url, {"User-Agent": USER_AGENT})
    except TypeError:
        value = fetch(url)
    if isinstance(value, bytes):
        return json.loads(value.decode("utf-8"))
    if isinstance(value, str):
        return json.loads(value)
    return value


def find_place(
    query: str,
    *,
    home: Path | None = None,
    fetch: Callable = _fetch_json,
    clock: Callable[[], float] = time.monotonic,
    sleep: Callable[[float], None] = time.sleep,
) -> dict:
    """Resolve a worldwide place through Nominatim and cache the first hit."""
    global _last_nominatim_request

    query = query.strip()
    if not query:
        raise ValueError("plaats mag niet leeg zijn")
    cache_path = _cache_path("nominatim.json", home)
    cache = _read_json(cache_path, {})
    cache_key = query.casefold()
    if cache_key in cache:
        return cache[cache_key]

    wait = 1.0 - (clock() - _last_nominatim_request)
    if _last_nominatim_request and wait > 0:
        sleep(wait)
    url = f"{NOMINATIM_URL}?{urlencode({
        'q': query,
        'format': 'jsonv2',
        'limit': 3,
        'addressdetails': 1,
    })}"
    results = _call_fetch(fetch, url)
    _last_nominatim_request = clock()
    if not isinstance(results, list) or not results:
        raise RuntimeError(f"plaats niet gevonden: '{query}'")
    first = results[0]
    address = first.get("address") or {}
    result = {
        "lat": float(first["lat"]),
        "lon": float(first["lon"]),
        "label": first.get("display_name") or first.get("name") or query,
        "country": address.get("country")
        or first.get("country")
        or address.get("country_code"),
    }
    cache[cache_key] = result
    _write_json(cache_path, cache)
    return result


def load_geofabrik_index(
    *,
    home: Path | None = None,
    fetch: Callable = _fetch_json,
) -> dict:
    """Load the Geofabrik index, downloading it only when absent."""
    path = _cache_path("geofabrik-index.json", home)
    if path.exists():
        index = _read_json(path, None)
    else:
        index = _call_fetch(fetch, GEOFABRIK_INDEX_URL)
        _write_json(path, index)
    if not isinstance(index, dict) or not isinstance(index.get("features"), list):
        raise RuntimeError("ongeldige Geofabrik-index")
    return index


def _geometry_contains(geometry: dict, lat: float, lon: float) -> bool:
    kind = geometry.get("type")
    coordinates = geometry.get("coordinates") or []
    if kind == "Polygon":
        return geo.point_in_polygon(lat, lon, coordinates)
    if kind == "MultiPolygon":
        return any(geo.point_in_polygon(lat, lon, polygon) for polygon in coordinates)
    return False


def _iter_points(coordinates):
    if (
        isinstance(coordinates, (list, tuple))
        and len(coordinates) >= 2
        and isinstance(coordinates[0], (int, float))
        and isinstance(coordinates[1], (int, float))
    ):
        yield float(coordinates[0]), float(coordinates[1])
        return
    for child in coordinates or []:
        yield from _iter_points(child)


def _bounds(geometry: dict) -> tuple[float, float, float, float]:
    points = list(_iter_points(geometry.get("coordinates") or []))
    if not points:
        raise RuntimeError("Geofabrik-regio heeft geen polygon")
    lons, lats = zip(*points)
    return min(lats), min(lons), max(lats), max(lons)


def _feature_depth(feature: dict, by_id: dict[str, dict]) -> int:
    depth = 0
    seen = set()
    parent = feature.get("properties", {}).get("parent")
    while parent and parent not in seen:
        seen.add(parent)
        depth += 1
        parent = by_id.get(parent, {}).get("properties", {}).get("parent")
    return depth


def _feature_area(feature: dict) -> float:
    minlat, minlon, maxlat, maxlon = _bounds(feature["geometry"])
    return (maxlat - minlat) * (maxlon - minlon)


def _pbf_size_from_properties(properties: dict) -> int | None:
    for key in ("pbf_size_bytes", "pbf_size", "size"):
        value = properties.get(key)
        if isinstance(value, (int, float)):
            return int(value)
    return None


def _feature_result(
    feature: dict,
    *,
    size_fetch: Callable[[str], int | None] | None,
) -> dict:
    properties = feature.get("properties") or {}
    slug = properties.get("id") or feature.get("id")
    pbf_url = (properties.get("urls") or {}).get("pbf")
    if not slug or not pbf_url:
        raise RuntimeError("Geofabrik-regio mist id of PBF-URL")
    size = _pbf_size_from_properties(properties)
    if size is None and size_fetch is not None:
        size = size_fetch(pbf_url)
    try:
        maximum_mb = int(os.environ.get("LUSMAKER_MAX_PBF_MB", DEFAULT_MAX_PBF_MB))
    except ValueError as exc:
        raise ValueError("LUSMAKER_MAX_PBF_MB moet een geheel getal zijn") from exc
    if size is not None and size > maximum_mb * 1_000_000:
        actual_mb = round(size / 1_000_000)
        raise RuntimeError(
            f"Geofabrik-regio '{slug}' is {actual_mb} MB, groter dan de limiet "
            f"van {maximum_mb} MB; kies een kleinere subregio of verhoog "
            "LUSMAKER_MAX_PBF_MB"
        )
    return {
        "slug": str(slug),
        "pbf_url": str(pbf_url),
        "bbox": list(_bounds(feature["geometry"])),
    }


def region_slug_for(
    lat: float,
    lon: float,
    *,
    home: Path | None = None,
    index: dict | None = None,
    fetch: Callable = _fetch_json,
    size_fetch: Callable[[str], int | None] | None = _fetch_size,
) -> dict:
    """Choose the deepest, then geographically smallest containing region."""
    index = index or load_geofabrik_index(home=home, fetch=fetch)
    features = index["features"]
    by_id = {
        str((feature.get("properties") or {}).get("id") or feature.get("id")): feature
        for feature in features
    }
    matches = [
        feature
        for feature in features
        if _geometry_contains(feature.get("geometry") or {}, lat, lon)
        and ((feature.get("properties") or {}).get("urls") or {}).get("pbf")
    ]
    if not matches:
        raise RuntimeError(f"geen Geofabrik-regio gevonden voor {lat},{lon}")
    selected = min(
        matches,
        key=lambda feature: (-_feature_depth(feature, by_id), _feature_area(feature)),
    )
    return _feature_result(selected, size_fetch=size_fetch)


def region_for_query(
    query: str,
    *,
    home: Path | None = None,
    fetch: Callable = _fetch_json,
    size_fetch: Callable[[str], int | None] | None = _fetch_size,
) -> dict:
    """Resolve an exact Geofabrik id/name, or fall back to place lookup."""
    index = load_geofabrik_index(home=home, fetch=fetch)
    normalized = query.strip().casefold()
    exact = [
        feature
        for feature in index["features"]
        if normalized
        in {
            str((feature.get("properties") or {}).get("id", "")).casefold(),
            str((feature.get("properties") or {}).get("name", "")).casefold(),
        }
        and ((feature.get("properties") or {}).get("urls") or {}).get("pbf")
    ]
    if exact:
        selected = min(exact, key=_feature_area)
        return _feature_result(selected, size_fetch=size_fetch)
    place = find_place(query, home=home, fetch=fetch)
    result = region_slug_for(
        place["lat"],
        place["lon"],
        home=home,
        index=index,
        size_fetch=size_fetch,
    )
    result["place"] = place
    return result


def geofabrik_path_from_url(pbf_url: str) -> str:
    path = urlparse(pbf_url).path.strip("/")
    suffix = "-latest.osm.pbf"
    if not path.endswith(suffix):
        raise ValueError(f"ongeldige Geofabrik PBF-URL: {pbf_url}")
    return path[: -len(suffix)]
