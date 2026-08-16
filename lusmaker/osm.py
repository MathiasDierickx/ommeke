"""OSM-extractie: benoemde wegen (voor klimmen + gazetteer) en plaatsnamen.

Routing zelf gebeurt in GraphHopper; hier halen we alleen op wat de
klim-database en de geocoder nodig hebben.
"""
import pickle
import re
import sys
import unicodedata
from itertools import islice

from . import config, geo

PLACE_TYPES = {"city", "town", "village", "municipality", "hamlet", "suburb", "borough", "quarter"}
KEEP_TAGS = ("highway", "name", "surface")
LANDMARK_VALUES = {
    "leisure": {
        "park", "nature_reserve", "recreation_ground", "sports_centre",
        "garden", "common", "pitch", "stadium", "marina", "water_park",
    },
    "natural": {"water", "wood", "beach", "heath", "scrub", "wetland"},
    "landuse": {
        "recreation_ground", "forest", "meadow", "village_green", "cemetery",
    },
    "tourism": {"attraction", "theme_park", "zoo", "viewpoint", "museum", "park"},
}
LANDMARK_KEYS = (*LANDMARK_VALUES, "water", "boundary")
WATERWAY_VALUES = {"river", "canal"}
MAX_LANDMARK_POINTS = 2_000
MAX_LANDMARKS = 100_000
EXTRACT_FORMAT_VERSION = 4


def _in_bbox(lat: float, lon: float) -> bool:
    b = config.BBOX
    return b[0] <= lat <= b[2] and b[1] <= lon <= b[3]


def _record_way_refs(owner: dict[int, int], junctions: set[int], way_id: int, refs) -> None:
    for ref in set(refs):
        previous = owner.setdefault(ref, way_id)
        if previous != way_id:
            junctions.add(ref)


def _junction_refs(ways) -> set[int]:
    """Node-refs die door minstens twee verschillende ways gebruikt worden."""
    owner: dict[int, int] = {}
    junctions: set[int] = set()
    for way_id, refs, *_rest in ways:
        _record_way_refs(owner, junctions, way_id, refs)
    return junctions


def _landmark_kind(tags) -> str | None:
    """Geef de eerste relevante OSM-brontag voor een benoemd landmark."""
    for key, allowed in LANDMARK_VALUES.items():
        value = tags.get(key, "")
        if value in allowed:
            return f"{key}:{value}"
    water = tags.get("water", "")
    if water:
        return f"water:{water}"
    if tags.get("boundary", "") == "protected_area":
        return "boundary:protected_area"
    return None


def _centroid(coords) -> tuple[float, float] | None:
    """Bereken een polygon-centroid, met een gemiddelde als veilige fallback."""
    points = list(islice(coords, MAX_LANDMARK_POINTS))
    if not points:
        return None
    if len(points) < 3:
        return (
            sum(point[0] for point in points) / len(points),
            sum(point[1] for point in points) / len(points),
        )

    # De kleine OSM-gebieden in deze gazetteer kunnen als vlak in lat/lon
    # behandeld worden. Bij open of degenererende geometrie valt dit terug op
    # het gemiddelde, wat ook voor lineaire waterfeatures bruikbaar blijft.
    ring = points if points[0] == points[-1] else [*points, points[0]]
    twice_area = centroid_lat = centroid_lon = 0.0
    for (lat1, lon1), (lat2, lon2) in zip(ring, ring[1:]):
        cross = lon1 * lat2 - lon2 * lat1
        twice_area += cross
        centroid_lon += (lon1 + lon2) * cross
        centroid_lat += (lat1 + lat2) * cross
    if abs(twice_area) < 1e-12:
        return (
            sum(point[0] for point in points) / len(points),
            sum(point[1] for point in points) / len(points),
        )
    return (
        centroid_lat / (3.0 * twice_area),
        centroid_lon / (3.0 * twice_area),
    )


def _normalise_name(value: str) -> str:
    value = unicodedata.normalize("NFKD", value.casefold())
    value = "".join(char for char in value if not unicodedata.combining(char))
    return " ".join(re.findall(r"[a-z0-9]+", value))


def _dedupe_landmarks(landmarks, radius_m: float = 100.0) -> list[tuple]:
    """Dedupeer gelijknamige node/way/area-varianten binnen circa 100 meter."""
    by_name: dict[str, list[tuple]] = {}
    kept = []
    for landmark in landmarks:
        name, _kind, lat, lon = landmark
        normalised = _normalise_name(name)
        nearby = by_name.setdefault(normalised, [])
        if any(
            geo.haversine(lat, lon, other[2], other[3]) <= radius_m
            for other in nearby
        ):
            continue
        nearby.append(landmark)
        kept.append(landmark)
    return kept


def build_extract(force: bool = False) -> dict:
    """Parse de PBF en cache wegen, plaatsen, landmarks en waterlopen."""
    if config.EXTRACT_PKL.exists() and not force:
        with open(config.EXTRACT_PKL, "rb") as f:
            extract = pickle.load(f)
        if extract.get("format_version") != EXTRACT_FORMAT_VERSION:
            raise RuntimeError("extract-cache is verouderd — draai `lus build --force`")
        return extract

    import osmium

    pbf = str(config.PBF_PATH)

    print("[build] pass 1/2: plaatsnamen en landmark-nodes ...", file=sys.stderr)
    places = []
    landmarks = []
    fp = osmium.FileProcessor(pbf, osmium.osm.NODE).with_filter(
        osmium.filter.KeyFilter("place", *LANDMARK_KEYS)
    )
    for n in fp:
        if not n.location.valid():
            continue
        lat, lon = n.location.lat, n.location.lon
        if not _in_bbox(lat, lon):
            continue
        ptype = n.tags.get("place", "")
        name = n.tags.get("name")
        if ptype in PLACE_TYPES and name:
            places.append((name, ptype, lat, lon))
        kind = _landmark_kind(n.tags)
        if name and kind and len(landmarks) < MAX_LANDMARKS:
            landmarks.append((name, kind, lat, lon))
    print(
        f"[build]   {len(places)} plaatsen en {len(landmarks)} landmark-nodes",
        file=sys.stderr,
    )

    print(
        "[build] pass 2/2: wegen, gebieden en kruispunten "
        "(dit duurt een paar minuten) ...",
        file=sys.stderr,
    )
    ways = []
    waterways = []
    ref_owner: dict[int, int] = {}
    junction_refs: set[int] = set()
    fp = (
        osmium.FileProcessor(pbf)
        .with_locations()
        .with_areas(osmium.filter.KeyFilter(*LANDMARK_KEYS))
        .with_filter(osmium.filter.EntityFilter(osmium.osm.WAY | osmium.osm.AREA))
        .with_filter(osmium.filter.KeyFilter("highway", "waterway", *LANDMARK_KEYS))
    )
    n_seen = 0
    for obj in fp:
        if obj.is_way():
            n_seen += 1
            if n_seen % 200_000 == 0:
                print(
                    f"[build]   {n_seen} wegen gezien, {len(ways)} benoemd in regio",
                    file=sys.stderr,
                )
            refs = []
            coords = []
            for node in obj.nodes:
                if node.location.valid():
                    refs.append(node.ref)
                    coords.append((node.location.lat, node.location.lon))
            if len(coords) < 2:
                continue
            if obj.tags.get("highway") and _in_bbox(*coords[0]):
                _record_way_refs(ref_owner, junction_refs, obj.id, refs)
                if obj.tags.get("name"):
                    tags = {k: obj.tags[k] for k in KEEP_TAGS if k in obj.tags}
                    ways.append((obj.id, refs, coords, tags))
            waterway = obj.tags.get("waterway")
            if (
                waterway in WATERWAY_VALUES
                and obj.tags.get("name")
                and any(_in_bbox(*point) for point in coords)
            ):
                waterways.append(
                    (obj.tags["name"], waterway, coords[:MAX_LANDMARK_POINTS])
                )
            kind = _landmark_kind(obj.tags)
            centre = _centroid(coords) if kind and obj.tags.get("name") else None
        else:
            kind = _landmark_kind(obj.tags)
            area_coords = (
                (node.location.lat, node.location.lon)
                for ring in obj.outer_rings()
                for node in ring
                if node.location.valid()
            )
            centre = _centroid(area_coords) if kind and obj.tags.get("name") else None
        if (
            centre is not None
            and _in_bbox(*centre)
            and len(landmarks) < MAX_LANDMARKS
        ):
            landmarks.append((obj.tags["name"], kind, centre[0], centre[1]))
    print(
        f"[build]   {len(ways)} benoemde wegen, {len(junction_refs)} kruispunten, "
        f"{len(landmarks)} landmarks en {len(waterways)} waterlopen in regio",
        file=sys.stderr,
    )

    extract = {
        "format_version": EXTRACT_FORMAT_VERSION,
        "ways": ways,
        "places": places,
        "landmarks": landmarks,
        "waterways": waterways,
        "junction_refs": junction_refs,
    }
    config.ensure_dirs()
    with open(config.EXTRACT_PKL, "wb") as f:
        pickle.dump(extract, f, protocol=pickle.HIGHEST_PROTOCOL)
    return extract


def build_gazetteer(extract: dict, force: bool = False) -> dict:
    """Kleine lokale index voor plaatsen, straten, landmarks en waterlopen."""
    if config.GAZETTEER_PKL.exists() and not force:
        with open(config.GAZETTEER_PKL, "rb") as f:
            gazetteer = pickle.load(f)
        gazetteer.setdefault("waterways", {})
        return gazetteer

    streets: dict[str, list] = {}
    for _wid, _refs, coords, tags in extract["ways"]:
        name = tags.get("name")
        if not name or tags.get("highway") in ("motorway", "trunk", "motorway_link", "trunk_link"):
            continue
        pts = streets.setdefault(name.lower(), [])
        if len(pts) < 60:
            pts.append((round(coords[0][0], 5), round(coords[0][1], 5), name))

    landmarks = _dedupe_landmarks(extract.get("landmarks", []))
    waterways: dict[str, list] = {}
    for name, _kind, coords in extract.get("waterways", []):
        waterways.setdefault(_normalise_name(name), []).append(coords)
    gaz = {
        "places": extract["places"],
        "streets": streets,
        "landmarks": landmarks,
        "waterways": waterways,
    }
    print(f"[build]   {len(landmarks)} unieke landmarks in gazetteer", file=sys.stderr)
    with open(config.GAZETTEER_PKL, "wb") as f:
        pickle.dump(gaz, f, protocol=pickle.HIGHEST_PROTOCOL)
    return gaz
