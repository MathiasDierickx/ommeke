"""Vlaanderen-grens: bbox van een regiopack afleiden uit een GeoJSON-polygoon.

De grens zelf (`lusmaker/data/flanders_boundary.geojson`) is een vereenvoudigde
afgeleide van OpenStreetMap (relatie 53134, admin_level 4 "Vlaanderen",
(c) OpenStreetMap-bijdragers, ODbL). Ze wordt eenmalig opgehaald met
`scripts/flanders_boundary.py` en daarna ingecheckt. Deze module gebruikt enkel
stdlib en doet geen netwerkverkeer.

Let op: de dekkingscontrole in productie (`coverage.py`) gebruikt de gemeten
GraphHopper-`/info`-bbox en niet deze afgeleide bbox.
"""
from __future__ import annotations

import json
import math
from pathlib import Path

from . import config

BOUNDARY_PATH = Path(__file__).with_name("data") / "flanders_boundary.geojson"
BOUNDARY_TOKEN = "boundary"  # `--bbox boundary` = afleiden uit de grens
DEFAULT_BUFFER_KM = 2.0
_KM_PER_DEG_LAT = 111.32


def _rings(geometry: dict):
    kind = geometry.get("type")
    coords = geometry.get("coordinates")
    if kind == "Polygon":
        yield from coords
    elif kind == "MultiPolygon":
        for polygon in coords:
            yield from polygon
    elif kind == "GeometryCollection":
        for part in geometry.get("geometries", []):
            yield from _rings(part)
    else:
        raise ValueError(f"geometrietype {kind!r} wordt niet ondersteund")


def geometries(geojson: dict):
    """Alle geometrieën van een Feature, FeatureCollection of kale geometrie."""
    kind = geojson.get("type")
    if kind == "FeatureCollection":
        for feature in geojson.get("features", []):
            yield from geometries(feature)
    elif kind == "Feature":
        yield geojson["geometry"]
    else:
        yield geojson


def load_boundary(path: Path | str | None = None) -> dict | None:
    """Laad de grens; `None` wanneer het bestand niet bestaat."""
    path = Path(path) if path else BOUNDARY_PATH
    if not path.is_file():
        return None
    return json.loads(path.read_text(encoding="utf-8"))


def raw_bbox(geojson: dict) -> tuple[float, float, float, float]:
    """(minlat, minlon, maxlat, maxlon) van alle ringen (GeoJSON is lon,lat)."""
    lats, lons = [], []
    for geometry in geometries(geojson):
        for ring in _rings(geometry):
            for point in ring:
                lons.append(float(point[0]))
                lats.append(float(point[1]))
    if not lats:
        raise ValueError("de grens bevat geen coördinaten")
    return min(lats), min(lons), max(lats), max(lons)


def buffered_bbox(
    geojson: dict, buffer_km: float = DEFAULT_BUFFER_KM
) -> tuple[float, float, float, float]:
    """Bbox van de grens plus een buffer, afgerond op 4 decimalen (~10 m)."""
    if buffer_km < 0:
        raise ValueError("buffer_km mag niet negatief zijn")
    minlat, minlon, maxlat, maxlon = raw_bbox(geojson)
    dlat = buffer_km / _KM_PER_DEG_LAT
    mid = math.radians((minlat + maxlat) / 2)
    dlon = buffer_km / (_KM_PER_DEG_LAT * max(math.cos(mid), 0.01))
    return config._validate_bbox(
        (
            round(max(minlat - dlat, -90), 4),
            round(max(minlon - dlon, -180), 4),
            round(min(maxlat + dlat, 90), 4),
            round(min(maxlon + dlon, 180), 4),
        )
    )


def flanders_bbox(
    path: Path | str | None = None, buffer_km: float = DEFAULT_BUFFER_KM
) -> tuple[float, float, float, float]:
    """Bbox uit de ingecheckte grens; duidelijke fout als die ontbreekt."""
    geojson = load_boundary(path)
    if geojson is None:
        raise ValueError(
            "geen Vlaanderen-grens gevonden "
            f"({Path(path) if path else BOUNDARY_PATH}); haal ze eenmalig op "
            "met `python scripts/flanders_boundary.py` of geef --bbox expliciet mee"
        )
    return buffered_bbox(geojson, buffer_km)


def resolve_bbox(value: str, path: Path | str | None = None):
    """`boundary` -> afgeleid uit de grens, anders `minlat,minlon,maxlat,maxlon`."""
    if value.strip().lower() == BOUNDARY_TOKEN:
        return flanders_bbox(path)
    try:
        return config._validate_bbox(value.split(","))
    except ValueError as exc:
        raise ValueError(
            "bbox verwacht minlat,minlon,maxlat,maxlon of `boundary`"
        ) from exc


def _perp_distance(point, start, end) -> float:
    (x, y), (x1, y1), (x2, y2) = point, start, end
    dx, dy = x2 - x1, y2 - y1
    if dx == 0 and dy == 0:
        return math.hypot(x - x1, y - y1)
    t = ((x - x1) * dx + (y - y1) * dy) / (dx * dx + dy * dy)
    t = max(0.0, min(1.0, t))
    return math.hypot(x - (x1 + t * dx), y - (y1 + t * dy))


def _douglas_peucker(seq: list, tolerance: float) -> list:
    if len(seq) < 3:
        return seq
    idx, dmax = 0, 0.0
    for i in range(1, len(seq) - 1):
        d = _perp_distance(seq[i], seq[0], seq[-1])
        if d > dmax:
            idx, dmax = i, d
    if dmax <= tolerance:
        return [seq[0], seq[-1]]
    return _douglas_peucker(seq[: idx + 1], tolerance)[:-1] + _douglas_peucker(
        seq[idx:], tolerance
    )


def simplify_ring(ring: list, tolerance: float) -> list:
    """Douglas-Peucker op een gesloten ring (tolerantie in graden)."""
    pts = [tuple(p[:2]) for p in ring]
    if len(pts) <= 4:
        return [list(p) for p in pts]
    open_pts = pts[:-1] if pts[0] == pts[-1] else pts
    # Splits bij het verste punt zodat de gesloten ring stabiel blijft.
    far = max(
        range(1, len(open_pts)),
        key=lambda i: math.hypot(
            open_pts[i][0] - open_pts[0][0], open_pts[i][1] - open_pts[0][1]
        ),
    )
    first = _douglas_peucker(open_pts[: far + 1], tolerance)
    second = _douglas_peucker(open_pts[far:] + [open_pts[0]], tolerance)
    simplified = first[:-1] + second
    if len(simplified) < 4:
        return [list(p) for p in pts]
    return [list(p) for p in simplified]


def simplify_geojson(geojson: dict, tolerance: float = 0.005) -> dict:
    """Vereenvoudigde MultiPolygon-Feature; ringen die instorten vallen weg."""
    polygons = []
    for geometry in geometries(geojson):
        if geometry["type"] == "Polygon":
            sources = [geometry["coordinates"]]
        elif geometry["type"] == "MultiPolygon":
            sources = geometry["coordinates"]
        else:
            continue
        for polygon in sources:
            rings = [simplify_ring(ring, tolerance) for ring in polygon]
            rings = [r for r in rings if len(r) >= 4]
            if rings:
                polygons.append(rings)
    if not polygons:
        raise ValueError("vereenvoudiging leverde geen geldige polygoon op")
    return {
        "type": "Feature",
        "properties": {
            "name": "Vlaanderen",
            "source": "OpenStreetMap relation 53134 (admin_level 4)",
            "license": "ODbL 1.0, (c) OpenStreetMap contributors",
            "simplified_tolerance_deg": tolerance,
        },
        "geometry": {"type": "MultiPolygon", "coordinates": polygons},
    }
