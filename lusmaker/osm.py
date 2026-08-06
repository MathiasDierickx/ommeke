"""OSM-extractie: benoemde wegen (voor klimmen + gazetteer) en plaatsnamen.

Routing zelf gebeurt in GraphHopper; hier halen we alleen op wat de
klim-database en de geocoder nodig hebben.
"""
import pickle
import sys

from . import config

PLACE_TYPES = {"city", "town", "village", "municipality", "hamlet", "suburb", "borough", "quarter"}
KEEP_TAGS = ("highway", "name", "surface")
EXTRACT_FORMAT_VERSION = 2


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


def build_extract(force: bool = False) -> dict:
    """Parse de Belgium-PBF en cache benoemde wegen + plaatsen in de regio-bbox."""
    if config.EXTRACT_PKL.exists() and not force:
        with open(config.EXTRACT_PKL, "rb") as f:
            extract = pickle.load(f)
        if extract.get("format_version") != EXTRACT_FORMAT_VERSION:
            raise RuntimeError("extract-cache is verouderd — draai `lus build --force`")
        return extract

    import osmium

    pbf = str(config.PBF_PATH)

    print("[build] pass 1/2: plaatsnamen ...", file=sys.stderr)
    places = []
    fp = osmium.FileProcessor(pbf, osmium.osm.NODE).with_filter(osmium.filter.KeyFilter("place"))
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
    print(f"[build]   {len(places)} plaatsen", file=sys.stderr)

    print("[build] pass 2/2: wegen en kruispunten (dit duurt een paar minuten) ...", file=sys.stderr)
    ways = []
    ref_owner: dict[int, int] = {}
    junction_refs: set[int] = set()
    fp = (
        osmium.FileProcessor(pbf, osmium.osm.NODE | osmium.osm.WAY)
        .with_locations()
        .with_filter(osmium.filter.EntityFilter(osmium.osm.WAY))
        .with_filter(osmium.filter.KeyFilter("highway"))
    )
    n_seen = 0
    for w in fp:
        n_seen += 1
        if n_seen % 200_000 == 0:
            print(f"[build]   {n_seen} wegen gezien, {len(ways)} benoemd in regio", file=sys.stderr)
        refs = []
        coords = []
        for node in w.nodes:
            if node.location.valid():
                refs.append(node.ref)
                coords.append((node.location.lat, node.location.lon))
        if len(coords) < 2 or not _in_bbox(*coords[0]):
            continue
        _record_way_refs(ref_owner, junction_refs, w.id, refs)
        if not w.tags.get("name"):
            continue
        tags = {k: w.tags[k] for k in KEEP_TAGS if k in w.tags}
        ways.append((w.id, refs, coords, tags))
    print(
        f"[build]   {len(ways)} benoemde wegen en {len(junction_refs)} kruispunten in regio",
        file=sys.stderr,
    )

    extract = {
        "format_version": EXTRACT_FORMAT_VERSION,
        "ways": ways,
        "places": places,
        "junction_refs": junction_refs,
    }
    config.ensure_dirs()
    with open(config.EXTRACT_PKL, "wb") as f:
        pickle.dump(extract, f, protocol=pickle.HIGHEST_PROTOCOL)
    return extract


def build_gazetteer(extract: dict, force: bool = False) -> dict:
    """Kleine lokale geocoder-index: plaatsen + straatnaam -> puntenlijst."""
    if config.GAZETTEER_PKL.exists() and not force:
        with open(config.GAZETTEER_PKL, "rb") as f:
            return pickle.load(f)

    streets: dict[str, list] = {}
    for _wid, _refs, coords, tags in extract["ways"]:
        name = tags.get("name")
        if not name or tags.get("highway") in ("motorway", "trunk", "motorway_link", "trunk_link"):
            continue
        pts = streets.setdefault(name.lower(), [])
        if len(pts) < 60:
            pts.append((round(coords[0][0], 5), round(coords[0][1], 5), name))

    gaz = {"places": extract["places"], "streets": streets}
    with open(config.GAZETTEER_PKL, "wb") as f:
        pickle.dump(gaz, f, protocol=pickle.HIGHEST_PROTOCOL)
    return gaz
