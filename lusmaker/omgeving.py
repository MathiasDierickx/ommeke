"""OSM-celcache voor bos/shaduw en verlichte wegen."""
import json
from pathlib import Path

from . import config, geo


def cache_path():
    return config.CACHE / "omgeving_cells.json"


def _point_in_ring(point, ring):
    lat, lon = point
    inside = False
    for (y1, x1), (y2, x2) in zip(ring, ring[1:]):
        if (y1 > lat) != (y2 > lat) and lon < (x2 - x1) * (lat - y1) / (y2 - y1) + x1:
            inside = not inside
    return inside


def polygon_cells(ring):
    """Rasteriseer een (lat, lon)-ring, inclusief cellen binnen of rakend aan het vlak."""
    ring = list(ring)
    if len(ring) < 3:
        return set()
    if ring[0] != ring[-1]:
        ring.append(ring[0])
    boundary = set()
    for a, b in zip(ring, ring[1:]):
        boundary.update(geo.cell(*point) for point in geo.resample([a, b], 40.0))
    cells = set(boundary)
    for i in range(min(c[0] for c in boundary), max(c[0] for c in boundary) + 1):
        for j in range(min(c[1] for c in boundary), max(c[1] for c in boundary) + 1):
            cell = (i, j)
            if _point_in_ring(((i + 0.5) * geo.CELL_LAT, (j + 0.5) * geo.CELL_LON), ring):
                cells.add(cell)
    return cells


def line_cells(coords):
    return {geo.cell(*point) for point in geo.resample(coords, 40.0)} if len(coords) >= 2 else set()


def load(path=None):
    path = cache_path() if path is None else Path(path)
    if not path.is_file():
        return None
    data = json.loads(path.read_text(encoding="utf-8"))
    return {name: {tuple(cell) for cell in data.get(name, [])} for name in ("bos", "verlicht")}


def build(*, pbf=None, output=None):
    """Maak de celcache uit actieve regio-PBF."""
    import osmium

    pbf = str(pbf or config.PBF_PATH)
    woods, lit = set(), set()
    processor = osmium.FileProcessor(pbf).with_locations().with_areas(
        osmium.filter.KeyFilter("landuse", "natural")
    ).with_filter(osmium.filter.EntityFilter(osmium.osm.WAY | osmium.osm.AREA)).with_filter(
        osmium.filter.KeyFilter("highway", "landuse", "natural")
    )
    for obj in processor:
        tags = obj.tags
        if obj.is_way():
            coords = [(node.location.lat, node.location.lon) for node in obj.nodes if node.location.valid()]
            if len(coords) < 2:
                continue
            if tags.get("highway") and tags.get("lit") == "yes":
                lit.update(line_cells(coords))
        else:
            if tags.get("landuse") != "forest" and tags.get("natural") != "wood":
                continue
            for ring in obj.outer_rings():
                coords = [(node.location.lat, node.location.lon) for node in ring if node.location.valid()]
                woods.update(polygon_cells(coords))
    path = cache_path() if output is None else Path(output)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"version": 1, "bos": sorted(map(list, woods)), "verlicht": sorted(map(list, lit))}), encoding="utf-8")
    return {"bestand": str(path), "bos_cellen": len(woods), "verlicht_cellen": len(lit)}


def info():
    data = load()
    return {"beschikbaar": data is not None, "bos_cellen": len(data["bos"]) if data else 0,
            "verlicht_cellen": len(data["verlicht"]) if data else 0, "bestand": str(cache_path())}
