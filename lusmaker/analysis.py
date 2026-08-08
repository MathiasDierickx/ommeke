"""Route-kwaliteitsmetrieken: kasseien, steenweg-meters, kruisingen met drukke wegen."""
import math
import pickle
from functools import lru_cache

from . import config, geo

BIG_ROADS = {"primary", "primary_link", "secondary", "secondary_link"}
OFFROAD_CLASSES = {"path", "track", "footway", "pedestrian", "bridleway", "cycleway"}
COBBLE_SURFACES = {"cobblestone", "sett", "unhewn_cobblestone", "cobblestone:flattened"}
CONCRETE_SURFACES = {"concrete", "concrete:lanes", "concrete:plates"}


def detail_meters(coords, detail_intervals, wanted) -> float:
    """Meters van een route waar een GH-detail (bv. surface) in `wanted` zit."""
    total = 0.0
    for frm, to, value in detail_intervals:
        if str(value).lower() not in wanted:
            continue
        for i in range(frm, min(to, len(coords) - 1)):
            a, b = coords[i], coords[i + 1]
            total += geo.haversine(a[0], a[1], b[0], b[1])
    return total


def _detail_values(coords, detail_intervals) -> list[str | None]:
    """Vouw GH-detailintervallen uit tot één genormaliseerde waarde per segment."""
    values = [None] * max(0, len(coords) - 1)
    for frm, to, value in detail_intervals:
        for index in range(max(0, frm), min(to, len(values))):
            values[index] = str(value).lower()
    return values


def _fallback_meters(
    coords,
    detail_intervals,
    cells: set,
    *,
    already_counted_intervals=(),
    already_counted_values=frozenset(),
) -> float:
    """Meet segmenten met ontbrekende GH-surface via het Vlaanderen-grid."""
    if not cells:
        return 0.0
    values = _detail_values(coords, detail_intervals)
    counted = _detail_values(coords, already_counted_intervals)
    return sum(
        geo.haversine(coords[index][0], coords[index][1],
                      coords[index + 1][0], coords[index + 1][1])
        for index, value in enumerate(values)
        if (
            value == "missing"
            and counted[index] not in already_counted_values
            and geo.cell(coords[index][0], coords[index][1]) in cells
        )
    )


@lru_cache(maxsize=8)
def _big_road_grid(region_slug: str):
    """Gridindex van primaire/secundaire wegsegmenten uit het OSM-extract."""
    with open(config.EXTRACT_PKL, "rb") as f:
        extract = pickle.load(f)
    segs = []
    grid = {}
    for _wid, _refs, coords, tags in extract["ways"]:
        if tags.get("highway") not in BIG_ROADS:
            continue
        for i in range(len(coords) - 1):
            k = len(segs)
            segs.append((coords[i], coords[i + 1]))
            for pt in (coords[i], coords[i + 1]):
                grid.setdefault(geo.cell(*pt), []).append(k)
    return segs, grid


def _seg_intersect(p1, p2, p3, p4):
    """2D-segmentsnijding (vlakke benadering, ok op deze schaal)."""
    d1x, d1y = p2[0] - p1[0], p2[1] - p1[1]
    d2x, d2y = p4[0] - p3[0], p4[1] - p3[1]
    denom = d1x * d2y - d1y * d2x
    if abs(denom) < 1e-15:
        return None
    t = ((p3[0] - p1[0]) * d2y - (p3[1] - p1[1]) * d2x) / denom
    u = ((p3[0] - p1[0]) * d1y - (p3[1] - p1[1]) * d1x) / denom
    if 0 <= t <= 1 and 0 <= u <= 1:
        return (p1[0] + t * d1x, p1[1] + t * d1y)
    return None


def _angle_deg(a1, a2, b1, b2):
    v1 = (a2[0] - a1[0], (a2[1] - a1[1]) * math.cos(math.radians(a1[0])))
    v2 = (b2[0] - b1[0], (b2[1] - b1[1]) * math.cos(math.radians(b1[0])))
    n1 = math.hypot(*v1) or 1e-12
    n2 = math.hypot(*v2) or 1e-12
    cos = abs((v1[0] * v2[0] + v1[1] * v2[1]) / (n1 * n2))
    return math.degrees(math.acos(min(1.0, cos)))


def count_crossings(route_coords) -> int:
    """Aantal keer dat de route een drukke steenweg dwars oversteekt.

    Parallelle stukken (oprijden/afslaan, kort meerijden) tellen niet mee:
    enkel snijdingen met een hoek > 30 graden, samengevoegd binnen 60 m.
    """
    segs, grid = _big_road_grid(config.current_region().slug)
    pts = [(c[0], c[1]) for c in route_coords]
    events = []
    for i in range(len(pts) - 1):
        a, b = pts[i], pts[i + 1]
        cand = set()
        for pt in (a, b):
            c = geo.cell(*pt)
            for di in (-1, 0, 1):
                for dj in (-1, 0, 1):
                    cand.update(grid.get((c[0] + di, c[1] + dj), ()))
        for k in cand:
            s1, s2 = segs[k]
            hit = _seg_intersect(a, b, s1, s2)
            if hit and _angle_deg(a, b, s1, s2) > 30:
                events.append(hit)
    # events op dezelfde kruising samenvoegen
    merged = []
    for e in events:
        if all(geo.haversine(e[0], e[1], m[0], m[1]) > 60 for m in merged):
            merged.append(e)
    return len(merged)


def route_stats(legs_geometry, legs_details, profile: str = "quiet") -> dict:
    """Kwaliteitsrapport over een volledige (gerouteerde) draft."""
    all_coords = [pt for leg in legs_geometry for pt in leg]
    from . import heat

    vlaanderen = heat.vlaanderen_data()
    cobble_cells = vlaanderen["wegdek"].get("kassei", set())
    unpaved_cells = vlaanderen["wegdek"].get("onverhard", set())
    kassei = beton = steenweg = offroad = onverhard = 0.0
    for leg, det in zip(legs_geometry, legs_details):
        if not det:
            continue
        surface_details = det.get("surface", [])
        road_details = det.get("road_class", [])
        kassei += detail_meters(leg, surface_details, COBBLE_SURFACES)
        kassei += _fallback_meters(leg, surface_details, cobble_cells)
        beton += detail_meters(leg, surface_details, CONCRETE_SURFACES)
        steenweg += detail_meters(leg, road_details, BIG_ROADS)
        leg_offroad = detail_meters(leg, road_details, OFFROAD_CLASSES)
        offroad += leg_offroad
        onverhard += leg_offroad
        onverhard += _fallback_meters(
            leg,
            surface_details,
            unpaved_cells,
            already_counted_intervals=road_details,
            already_counted_values=OFFROAD_CLASSES,
        )
    try:
        crossings = count_crossings(all_coords)
    except FileNotFoundError:
        # Cassette-replay bevat alle GH-details maar bewust geen regiocache.
        crossings = None
    out = {
        "kassei_m": round(kassei),
        "onverhard_m": round(onverhard),
        "beton_m": round(beton),
        "steenweg_m": round(steenweg),
        "steenweg_kruisingen": crossings,
        "heen_en_weer_m": round(geo.self_retrace_m(legs_geometry)),
        "offroad_pct": round(offroad / max(geo.path_length([(c[0], c[1]) for leg in legs_geometry for c in leg]), 1) * 100, 1),
    }
    cells = heat.popular_cells(profile)
    if cells is not None:
        pts = geo.resample([(c[0], c[1]) for c in all_coords], 60.0)
        hits = sum(1 for p in pts if geo.cell(*p) in cells)
        out["populair_pct"] = round(hits / max(len(pts), 1) * 100, 1)
    network_cells = vlaanderen["fiets"] | vlaanderen["wandel"]
    if network_cells:
        pts = [(coordinate[0], coordinate[1]) for coordinate in all_coords]
        network_points = [point for point in pts if geo.cell(*point) in network_cells]
        if network_points:
            free = sum(
                1 for point in network_points
                if geo.cell(*point) not in vlaanderen["druk"]
            )
            out["autovrij_pct"] = round(free / len(network_points) * 100, 1)
    return out
