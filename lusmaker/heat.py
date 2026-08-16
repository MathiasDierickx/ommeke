"""Populariteitslagen uit eigen GPX-ritten en gecureerde open routegegevens.

Drop GPX-bestanden (Strava/Garmin bulk-export, toertocht-parcours) in
~/.lusmaker/heat/. `lus heat build` rastert ze samen met gecachete OSM-traces
en Toerisme Vlaanderen-routes op het ~130 m-celgrid. Het quiet-profiel krijgt
de custom area "popular"; met wandeldata krijgt trail "popular_trail". Via
`lus heat seed` komen daar activiteit-specifieke en onverhard-area's bij.

Let op: de area wordt bij de GRAAF-IMPORT ingebakken; na `heat build` moet de
graph-cache weg en GraphHopper herstarten (instructie in de output).
"""
import json
import math
import pickle
import sys
import xml.etree.ElementTree as ET
from collections import defaultdict
from pathlib import Path
from urllib.parse import urlencode

from . import config, gh_config, geo


# Bron: Toerisme Vlaanderen open data (Modellicentie Gratis Hergebruik).
# Endpoints gevalideerd 2026-08-08 via metadata.vlaanderen.be
# (record c91e9b9d-6465-4dec-beeb-16fdc6d759a0) en GetCapabilities.
TOERISME_VLAANDEREN_WFS = "https://geodata.toerismevlaanderen.be/geoserver/wfs"
VLAANDEREN_CACHE_VERSION = 2

ACTIVITIES = (
    "koersfiets",
    "stadsfiets",
    "gravel",
    "mtb",
    "trail",
    "wegloop",
    "wandelen",
)
PAVED_PREFERENCE_ACTIVITIES = frozenset(
    {"koersfiets", "stadsfiets", "wegloop"}
)
UNPAVED_SIGNAL_ACTIVITIES = frozenset({"mtb", "trail"})


def _wfs_url(layer: str) -> str:
    return (
        f"{TOERISME_VLAANDEREN_WFS}?service=WFS&version=2.0.0"
        f"&request=GetFeature&typeNames={layer}"
        "&outputFormat=application%2Fjson&srsName=EPSG%3A4326"
    )


CYCLING_NODE_NETWORK_WFS_URL = _wfs_url("routes%3Atraject_fiets")
HIKING_NODE_NETWORK_WFS_URL = _wfs_url("routes%3Atraject_wandel")
LF_ROUTES_WFS_URL = _wfs_url("routes%3Aicoonroute_trajecten")

VLAANDEREN_ROUTE_LAYERS = {
    "fietsnetwerk": ("fiets", "routes:traject_fiets", CYCLING_NODE_NETWORK_WFS_URL),
    "wandelnetwerken": ("wandel", "routes:traject_wandel", HIKING_NODE_NETWORK_WFS_URL),
    "icoonroutes": ("fiets", "routes:icoonroute_trajecten", LF_ROUTES_WFS_URL),
}

VLAANDEREN_SURFACE_LAYERS = {
    "wegdek fiets": ("routes:wegdek_fiets", _wfs_url("routes%3Awegdek_fiets")),
    "wegdek wandel": ("routes:wegdek_wandel", _wfs_url("routes%3Awegdek_wandel")),
}

VLAANDEREN_TRAFFIC_LAYERS = {
    "verkeersintensiteit fiets": (
        "routes:verkeersintensiteit_fiets",
        _wfs_url("routes%3Averkeersintensiteit_fiets"),
    ),
    "verkeersintensiteit wandel": (
        "routes:verkeersintensiteit_wandel",
        _wfs_url("routes%3Averkeersintensiteit_wandel"),
    ),
}

VLAANDEREN_POI_LAYERS = {
    poi_type: (f"poi:{poi_type}", _wfs_url(f"poi%3A{poi_type}"))
    for poi_type in (
        "picknickbank",
        "zitbank",
        "toilet",
        "uitkijktoren",
        "fietspomp_en_fietsherstel",
        "fietsverhuur",
        "speeltuin",
        "ebike",
    )
}

VLAANDEREN_KNOT_LAYERS = {
    "fietsknooppunten": (
        "fiets",
        "routes:knoop_fiets",
        _wfs_url("routes%3Aknoop_fiets"),
    ),
    "wandelknooppunten": (
        "wandel",
        "routes:knoop_wandel",
        _wfs_url("routes%3Aknoop_wandel"),
    ),
}


def _parse_gpx(path) -> list[tuple[float, float]]:
    pts = []
    try:
        for _ev, el in ET.iterparse(str(path)):
            if el.tag.endswith("trkpt") or el.tag.endswith("rtept"):
                try:
                    pts.append((float(el.get("lat")), float(el.get("lon"))))
                except (TypeError, ValueError):
                    pass
                el.clear()
    except ET.ParseError as e:
        print(f"[heat] {path.name}: parse-fout ({e}), overgeslagen", file=sys.stderr)
    return pts


def _track_cells(pts) -> set:
    cells = set()
    for i in range(len(pts)):
        if i and geo.haversine(*pts[i - 1], *pts[i]) > 80:
            for p in geo.resample([pts[i - 1], pts[i]], 60.0):
                cells.add(geo.cell(*p))
        cells.add(geo.cell(*pts[i]))
    return cells


def _load_heat() -> dict:
    if not config.HEAT_PKL.exists():
        return {}
    with open(config.HEAT_PKL, "rb") as handle:
        data = pickle.load(handle)
    return data if isinstance(data, dict) else {}


def seed(
    source: str | Path, activity: str, *, min_passes: int = 1
) -> dict:
    """Voeg GPX-routes toe aan de ruwe teller voor één activiteit."""
    if activity not in ACTIVITIES:
        raise ValueError(
            f"activiteit moet een van deze waarden zijn: {', '.join(ACTIVITIES)}"
        )
    if min_passes < 1:
        raise ValueError("min-passes moet minstens 1 zijn")
    source = Path(source)
    if not source.is_dir():
        raise ValueError(f"seed-bron is geen map: {source}")

    config.ensure_dirs()
    data = _load_heat()
    activity_cells = data.get("activity_cells")
    if not isinstance(activity_cells, dict):
        activity_cells = {}
    counts = activity_cells.setdefault(activity, {})

    tracks = 0
    for path in sorted(source.glob("*.gpx")):
        points = _parse_gpx(path)
        if len(points) < 10:
            continue
        tracks += 1
        for cell in _track_cells(points):
            counts[cell] = counts.get(cell, 0) + 1

    data["activity_cells"] = activity_cells
    with open(config.HEAT_PKL, "wb") as handle:
        pickle.dump(data, handle)
    return {
        "tracks": tracks,
        "activiteit": activity,
        "min_passes": min_passes,
        "cellen_per_activiteit": {
            name: len(activity_cells[name])
            for name in ACTIVITIES
            if activity_cells.get(name)
        },
    }


def _rects(cells) -> list[list[list[float]]]:
    """Popular cellen -> per rij samengevoegde rechthoeken (GeoJSON-ringen)."""
    rows = defaultdict(list)
    for i, j in cells:
        rows[i].append(j)
    rects = []
    for i, js in rows.items():
        js.sort()
        run_start = prev = js[0]
        for j in js[1:] + [None]:
            if j is not None and j == prev + 1:
                prev = j
                continue
            lat0, lat1 = i * geo.CELL_LAT, (i + 1) * geo.CELL_LAT
            lon0, lon1 = run_start * geo.CELL_LON, (prev + 1) * geo.CELL_LON
            rects.append([[lon0, lat0], [lon1, lat0], [lon1, lat1], [lon0, lat1], [lon0, lat0]])
            if j is not None:
                run_start = prev = j
    return rects


def _vlaanderen_wfs_url(base_url: str, bbox) -> str:
    """WFS GetFeature-URL met server-side bbox-filter en GeoJSON-output."""
    minlat, minlon, maxlat, maxlon = bbox
    query = urlencode(
        {"bbox": f"{minlon},{minlat},{maxlon},{maxlat},EPSG:4326"}
    )
    return f"{base_url}&{query}"


def _fetch_url(url: str) -> bytes:
    import urllib.request

    request = urllib.request.Request(
        url, headers={"User-Agent": "lusmaker/0.1 (hobby routeplanner)"}
    )
    with urllib.request.urlopen(request, timeout=90) as response:
        return response.read()


def _geojson_document(payload, label: str) -> dict:
    if isinstance(payload, dict):
        document = payload
    else:
        if isinstance(payload, bytes):
            payload = payload.decode("utf-8", errors="replace")
        if not isinstance(payload, str):
            raise RuntimeError(f"{label}: onverwacht antwoordtype")
        if payload.lstrip().startswith("<"):
            raise RuntimeError(
                f"{label}: WFS gaf een HTML/XML-antwoord in plaats van GeoJSON"
            )
        try:
            document = json.loads(payload)
        except json.JSONDecodeError as exc:
            raise RuntimeError(f"{label}: WFS-antwoord is geen geldige GeoJSON") from exc
    if document.get("type") != "FeatureCollection" or not isinstance(
        document.get("features"), list
    ):
        raise RuntimeError(f"{label}: WFS-antwoord is geen GeoJSON FeatureCollection")
    return document


def _geometry_lines(geometry: dict | None):
    if not geometry:
        return
    geometry_type = geometry.get("type")
    coordinates = geometry.get("coordinates")
    if geometry_type == "LineString":
        yield coordinates
    elif geometry_type == "MultiLineString":
        yield from coordinates or []
    elif geometry_type == "GeometryCollection":
        for child in geometry.get("geometries") or []:
            yield from _geometry_lines(child)


def _geojson_cells(document: dict) -> set:
    """Raster lijngeometrieën uit een GeoJSON FeatureCollection op het heatgrid."""
    cells = set()
    for feature in document.get("features", []):
        if not isinstance(feature, dict):
            continue
        for line in _geometry_lines(feature.get("geometry")):
            points = []
            for coordinate in line or []:
                if not isinstance(coordinate, (list, tuple)) or len(coordinate) < 2:
                    continue
                try:
                    lon, lat = float(coordinate[0]), float(coordinate[1])
                except (TypeError, ValueError):
                    continue
                if math.isfinite(lat) and math.isfinite(lon):
                    points.append((lat, lon))
            cells.update(_track_cells(points))
    return cells


def _geojson_cells_by_property(document: dict, property_name: str) -> dict[str, set]:
    """Raster lijnfeatures per niet-lege, genormaliseerde attribuutwaarde."""
    grouped = defaultdict(set)
    for feature in document.get("features", []):
        if not isinstance(feature, dict):
            continue
        value = (feature.get("properties") or {}).get(property_name)
        if value is None or not str(value).strip():
            continue
        key = str(value).strip().casefold()
        grouped[key].update(_geojson_cells({"features": [feature]}))
    return dict(grouped)


def _geometry_points(geometry: dict | None):
    if not geometry:
        return
    geometry_type = geometry.get("type")
    coordinates = geometry.get("coordinates")
    if geometry_type == "Point":
        coordinates = [coordinates]
    elif geometry_type != "MultiPoint":
        if geometry_type == "GeometryCollection":
            for child in geometry.get("geometries") or []:
                yield from _geometry_points(child)
        return
    for coordinate in coordinates or []:
        if not isinstance(coordinate, (list, tuple)) or len(coordinate) < 2:
            continue
        try:
            lon, lat = float(coordinate[0]), float(coordinate[1])
        except (TypeError, ValueError):
            continue
        if math.isfinite(lat) and math.isfinite(lon):
            yield lat, lon


def _point_in_bbox(point, bbox) -> bool:
    lat, lon = point
    minlat, minlon, maxlat, maxlon = bbox
    return minlat <= lat <= maxlat and minlon <= lon <= maxlon


def _geojson_pois(document: dict, bbox) -> list[tuple[float, float, str | None]]:
    points = []
    for feature in document.get("features", []):
        if not isinstance(feature, dict):
            continue
        properties = feature.get("properties") or {}
        name = properties.get("naam") or properties.get("name")
        name = str(name).strip() if name is not None and str(name).strip() else None
        points.extend(
            (lat, lon, name)
            for lat, lon in _geometry_points(feature.get("geometry"))
            if _point_in_bbox((lat, lon), bbox)
        )
    return points


def _knot_number(value):
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    if not math.isfinite(number) or number < 0:
        return None
    return int(number) if number.is_integer() else number


def _geojson_knots(document: dict, bbox, kind: str) -> list[tuple]:
    points = []
    for feature in document.get("features", []):
        if not isinstance(feature, dict):
            continue
        number = _knot_number((feature.get("properties") or {}).get("knoopnr"))
        if number is None:
            continue
        points.extend(
            (lat, lon, number, kind)
            for lat, lon in _geometry_points(feature.get("geometry"))
            if _point_in_bbox((lat, lon), bbox)
        )
    return points


def _fetch_vlaanderen_document(label: str, base_url: str, fetcher) -> dict:
    print(f"[heat] Toerisme Vlaanderen: {label} downloaden", file=sys.stderr)
    url = _vlaanderen_wfs_url(base_url, config.BBOX)
    try:
        payload = fetcher(url)
    except Exception as exc:
        code = getattr(exc, "code", None)
        detail = f"HTTP {code}" if code is not None else str(exc)
        raise RuntimeError(f"{label}: WFS-download mislukt ({detail})") from exc
    return _geojson_document(payload, label)


def fetch_vlaanderen(fetcher=_fetch_url) -> dict:
    """Download en cache alle bruikbare Toerisme Vlaanderen-lagen."""
    config.ensure_dirs()
    data = {
        "version": VLAANDEREN_CACHE_VERSION,
        "fiets": set(),
        "wandel": set(),
        "wegdek": {},
        "druk": set(),
        "pois": {},
        "knopen": [],
    }
    layer_counts = {}
    for label, (kind, layer, base_url) in VLAANDEREN_ROUTE_LAYERS.items():
        document = _fetch_vlaanderen_document(label, base_url, fetcher)
        cells = _geojson_cells(document)
        data[kind].update(cells)
        layer_counts[layer] = len(cells)
        print(
            f"[heat] Toerisme Vlaanderen: {label} — {len(cells)} cellen",
            file=sys.stderr,
        )

    for label, (layer, base_url) in VLAANDEREN_SURFACE_LAYERS.items():
        document = _fetch_vlaanderen_document(label, base_url, fetcher)
        grouped = _geojson_cells_by_property(document, "ground")
        for ground, cells in grouped.items():
            data["wegdek"].setdefault(ground, set()).update(cells)
        layer_cells = set().union(*grouped.values()) if grouped else set()
        layer_counts[layer] = len(layer_cells)
        print(
            f"[heat] Toerisme Vlaanderen: {label} — {len(layer_cells)} cellen",
            file=sys.stderr,
        )

    for label, (layer, base_url) in VLAANDEREN_TRAFFIC_LAYERS.items():
        document = _fetch_vlaanderen_document(label, base_url, fetcher)
        grouped = _geojson_cells_by_property(document, "traffic")
        cells = set().union(*grouped.values()) if grouped else set()
        data["druk"].update(cells)
        layer_counts[layer] = len(cells)
        print(
            f"[heat] Toerisme Vlaanderen: {label} — {len(cells)} cellen",
            file=sys.stderr,
        )

    for poi_type, (layer, base_url) in VLAANDEREN_POI_LAYERS.items():
        document = _fetch_vlaanderen_document(poi_type, base_url, fetcher)
        points = _geojson_pois(document, config.BBOX)
        data["pois"][poi_type] = points
        layer_counts[layer] = len(points)
        print(
            f"[heat] Toerisme Vlaanderen: {poi_type} — {len(points)} punten",
            file=sys.stderr,
        )

    for label, (kind, layer, base_url) in VLAANDEREN_KNOT_LAYERS.items():
        document = _fetch_vlaanderen_document(label, base_url, fetcher)
        points = _geojson_knots(document, config.BBOX, kind)
        data["knopen"].extend(points)
        layer_counts[layer] = len(points)
        print(
            f"[heat] Toerisme Vlaanderen: {label} — {len(points)} punten",
            file=sys.stderr,
        )

    with open(config.VLAANDEREN_ROUTES_PKL, "wb") as handle:
        pickle.dump(data, handle)
    return {
        "regio": config.current_region().slug,
        "fiets_cellen": len(data["fiets"]),
        "wandel_cellen": len(data["wandel"]),
        "wegdek_cellen": {
            ground: len(cells) for ground, cells in sorted(data["wegdek"].items())
        },
        "druk_cellen": len(data["druk"]),
        "pois": {poi_type: len(points) for poi_type, points in data["pois"].items()},
        "knopen": len(data["knopen"]),
        "lagen": layer_counts,
        "cache": str(config.VLAANDEREN_ROUTES_PKL),
    }


def fetch_osm(max_pages_per_tile: int = 150) -> dict:
    """Publieke GPS-traces van OpenStreetMap binnenhalen voor de regio-bbox.

    De trackpoints-API is open data (ODbL); identificeerbare traces komen als
    geordende tracks, anonieme als losse punten — beide tellen als dichtheid
    per cel. Eenmalige download, daarna gecached.
    """
    import time
    import urllib.request

    minlat, minlon, maxlat, maxlon = config.BBOX
    # API-limiet: 0.25 vierkante graad per bbox -> 2x2 tegels
    tiles = []
    for i in range(2):
        for j in range(2):
            tiles.append((
                minlon + (maxlon - minlon) * j / 2, minlat + (maxlat - minlat) * i / 2,
                minlon + (maxlon - minlon) * (j + 1) / 2, minlat + (maxlat - minlat) * (i + 1) / 2,
            ))

    # incrementeel: per afgewerkte tegel opslaan zodat een afgebroken run
    # hervat kan worden zonder alles opnieuw te downloaden
    counts: dict = defaultdict(int)
    done_tiles: set = set()
    total = 0
    if config.OSM_TRACES_PKL.exists():
        with open(config.OSM_TRACES_PKL, "rb") as f:
            prev = pickle.load(f)
        counts.update(prev.get("counts", {}))
        done_tiles = set(prev.get("done_tiles", []))
        total = prev.get("points", 0)
        if done_tiles:
            print(f"[heat] hervat: tegels {sorted(done_tiles)} al binnen", file=sys.stderr)

    def _save():
        with open(config.OSM_TRACES_PKL, "wb") as f:
            pickle.dump({"counts": dict(counts), "points": total,
                         "done_tiles": sorted(done_tiles)}, f)

    for t, (l, b, r, tp) in enumerate(tiles):
        if t in done_tiles:
            continue
        tile_failed = False
        for page in range(max_pages_per_tile):
            url = (f"https://api.openstreetmap.org/api/0.6/trackpoints"
                   f"?bbox={l:.4f},{b:.4f},{r:.4f},{tp:.4f}&page={page}")
            req = urllib.request.Request(url, headers={"User-Agent": "lusmaker/0.1 (hobby routeplanner)"})
            data = None
            for attempt in range(3):
                try:
                    with urllib.request.urlopen(req, timeout=60) as resp:
                        data = resp.read()
                    break
                except OSError as e:
                    code = getattr(e, "code", None)
                    if code in (429, 503) and attempt < 2:
                        wait = 30 * (attempt + 1)
                        print(f"[heat] tegel {t} pagina {page}: {code}, {wait}s backoff", file=sys.stderr)
                        time.sleep(wait)
                        continue
                    print(f"[heat] tegel {t} pagina {page}: {e} — tegel later hervatten", file=sys.stderr)
                    tile_failed = True
                    break
            if tile_failed:
                break
            pts = []
            for _ev, el in ET.iterparse(__import__("io").BytesIO(data)):
                if el.tag.endswith("trkpt"):
                    try:
                        pts.append((float(el.get("lat")), float(el.get("lon"))))
                    except (TypeError, ValueError):
                        pass
                    el.clear()
            if not pts:
                break
            prev = None
            for p in pts:
                # geordende tracks kort interpoleren; anonieme puntenwolken niet
                if prev and 0 < geo.haversine(*prev, *p) <= 150:
                    for q in geo.resample([prev, p], 60.0):
                        counts[geo.cell(*q)] += 1
                else:
                    counts[geo.cell(*p)] += 1
                prev = p
            total += len(pts)
            if page % 20 == 0:
                print(f"[heat] tegel {t + 1}/4 pagina {page}: {total} punten totaal", file=sys.stderr)
            time.sleep(0.25)
        if not tile_failed:
            done_tiles.add(t)
        _save()

    _save()
    return {"punten": total, "cellen": len(counts)}


def _osm_cells(min_points: int) -> set:
    if not config.OSM_TRACES_PKL.exists():
        return set()
    with open(config.OSM_TRACES_PKL, "rb") as f:
        counts = pickle.load(f)["counts"]
    return {c for c, n in counts.items() if n >= min_points}


def vlaanderen_data() -> dict:
    """Lees cacheversie 2, met lege aanvullingen voor een bestaande T14-cache."""
    empty = {
        "version": 1,
        "fiets": set(),
        "wandel": set(),
        "wegdek": {},
        "druk": set(),
        "pois": {},
        "knopen": [],
    }
    if not config.VLAANDEREN_ROUTES_PKL.exists():
        return empty
    with open(config.VLAANDEREN_ROUTES_PKL, "rb") as handle:
        cached = pickle.load(handle)
    if not isinstance(cached, dict):
        return empty
    return {
        "version": cached.get("version", 1),
        "fiets": set(cached.get("fiets", set())),
        "wandel": set(cached.get("wandel", set())),
        "wegdek": {
            str(ground): set(cells)
            for ground, cells in (cached.get("wegdek") or {}).items()
        },
        "druk": set(cached.get("druk", set())),
        "pois": {
            str(poi_type): list(points)
            for poi_type, points in (cached.get("pois") or {}).items()
        },
        "knopen": list(cached.get("knopen") or []),
    }


def _point_to_route_m(point, route_coords) -> float:
    """Kleinste afstand tot een routepolyline, lokaal vlak benaderd."""
    if not route_coords:
        return math.inf
    if len(route_coords) == 1:
        return geo.haversine(*point, *route_coords[0])
    lat, lon = point
    lon_scale = 111_320.0 * math.cos(math.radians(lat))
    best = math.inf
    for start, end in zip(route_coords, route_coords[1:]):
        ax = (start[1] - lon) * lon_scale
        ay = (start[0] - lat) * 111_320.0
        bx = (end[1] - lon) * lon_scale
        by = (end[0] - lat) * 111_320.0
        dx, dy = bx - ax, by - ay
        length_squared = dx * dx + dy * dy
        if length_squared:
            fraction = max(0.0, min(1.0, -(ax * dx + ay * dy) / length_squared))
            x, y = ax + fraction * dx, ay + fraction * dy
        else:
            x, y = ax, ay
        best = min(best, math.hypot(x, y))
    return best


def features_near_route(
    route_coords,
    *,
    poi_radius_m: float = 150.0,
    knot_radius_m: float = 100.0,
    max_pois: int | None = None,
) -> dict[str, list[dict]]:
    """Selecteer gecachete POI's en knopen binnen afstand van de route."""
    coords = [(float(point[0]), float(point[1])) for point in route_coords]
    if not coords:
        return {"pois": [], "knopen": []}
    max_radius = max(poi_radius_m, knot_radius_m)
    expand = max(1, math.ceil(max_radius / 120.0))
    candidate_cells = geo.cells_for_geom(coords, expand=expand)
    data = vlaanderen_data()

    pois = []
    seen_pois = set()
    for poi_type, points in data["pois"].items():
        for lat, lon, name in points:
            key = (poi_type, lat, lon, name)
            if key in seen_pois or geo.cell(lat, lon) not in candidate_cells:
                continue
            distance = _point_to_route_m((lat, lon), coords)
            if distance <= poi_radius_m:
                seen_pois.add(key)
                pois.append(
                    {
                        "type": poi_type,
                        "lat": lat,
                        "lon": lon,
                        "naam": name,
                        "afstand_m": round(distance),
                    }
                )
    pois.sort(
        key=lambda item: (
            item["afstand_m"], item["type"], item["lat"], item["lon"],
            item["naam"] or "",
        )
    )
    if max_pois is not None:
        pois = pois[:max(0, max_pois)]

    knots = []
    seen_knots = set()
    for lat, lon, number, kind in data["knopen"]:
        key = (lat, lon, number, kind)
        if key in seen_knots or geo.cell(lat, lon) not in candidate_cells:
            continue
        distance = _point_to_route_m((lat, lon), coords)
        if distance <= knot_radius_m:
            seen_knots.add(key)
            knots.append(
                {
                    "lat": lat,
                    "lon": lon,
                    "nummer": number,
                    "type": kind,
                    "afstand_m": round(distance),
                }
            )
    knots.sort(
        key=lambda item: (
            item["afstand_m"], item["nummer"], item["type"],
            item["lat"], item["lon"],
        )
    )
    return {"pois": pois, "knopen": knots}


def _vlaanderen_cells() -> dict[str, set]:
    routes = vlaanderen_data()
    return {
        "fiets": set(routes.get("fiets", set())),
        "wandel": set(routes.get("wandel", set())),
    }


def _area_feature(area_id: str, cells: set) -> dict:
    rects = _rects(cells)
    return {
        "type": "Feature",
        "id": area_id,
        "properties": {},
        "geometry": {
            "type": "MultiPolygon",
            "coordinates": [
                [
                    [[round(x, 6), round(y, 6)] for x, y in ring]
                ]
                for ring in rects
            ],
        },
    }


def build(min_passes: int = 1, osm_min_points: int = 30) -> dict:
    config.ensure_dirs()
    files = sorted(config.HEAT_DIR.glob("*.gpx"))
    previous_heat = _load_heat()
    activity_cells = previous_heat.get("activity_cells")
    if not isinstance(activity_cells, dict):
        activity_cells = {}

    cell_sources = defaultdict(set)
    for fi, f in enumerate(files):
        pts = _parse_gpx(f)
        if len(pts) < 10:
            continue
        for c in _track_cells(pts):
            cell_sources[c].add(fi)

    own = {c for c, srcs in cell_sources.items() if len(srcs) >= min_passes}
    osm = _osm_cells(osm_min_points)
    vlaanderen_data_cached = vlaanderen_data()
    vlaanderen = {
        "fiets": vlaanderen_data_cached["fiets"],
        "wandel": vlaanderen_data_cached["wandel"],
    }
    popular = own | osm | vlaanderen["fiets"]
    # Eigen tracks tellen mee voor trail zodra de gecureerde wandellaag bestaat.
    popular_trail = (own | vlaanderen["wandel"]) if vlaanderen["wandel"] else set()
    cobble_tvl = vlaanderen_data_cached["wegdek"].get("kassei", set())
    busy_tvl = vlaanderen_data_cached["druk"]
    activity_areas = {}
    for activity in ACTIVITIES:
        counts = activity_cells.get(activity)
        if not isinstance(counts, dict):
            continue
        cells = {cell for cell, count in counts.items() if count >= min_passes}
        if cells:
            activity_areas[activity] = cells
    unpaved_used = set().union(
        *(activity_areas.get(activity, set()) for activity in UNPAVED_SIGNAL_ACTIVITIES)
    )
    paved_used = set().union(
        *(
            set((activity_cells.get(activity) or {}).keys())
            for activity in PAVED_PREFERENCE_ACTIVITIES
            if isinstance(activity_cells.get(activity), dict)
        )
    )
    unpaved = unpaved_used - paved_used
    if (
        not popular
        and not popular_trail
        and not cobble_tvl
        and not busy_tvl
        and not activity_areas
    ):
        raise RuntimeError(
            f"geen data: drop GPX-ritten in {config.HEAT_DIR}, draai "
            "`lus heat fetch-osm` en/of `lus heat fetch-vlaanderen`"
        )
    rects = _rects(popular) if popular else []
    trail_rects = _rects(popular_trail) if popular_trail else []

    geojson = {
        "type": "FeatureCollection",
        "features": [],
    }
    if popular:
        geojson["features"].append(_area_feature("popular", popular))
    if popular_trail:
        geojson["features"].append(_area_feature("popular_trail", popular_trail))
    if cobble_tvl:
        geojson["features"].append(_area_feature("kassei_tvl", cobble_tvl))
    if busy_tvl:
        geojson["features"].append(_area_feature("druk_tvl", busy_tvl))
    for activity in ACTIVITIES:
        cells = activity_areas.get(activity)
        if cells:
            geojson["features"].append(
                _area_feature(f"popular_{activity}", cells)
            )
    if unpaved:
        geojson["features"].append(_area_feature("onverhard", unpaved))
    area_ids = [feature["id"] for feature in geojson["features"]]
    (config.CUSTOM_AREAS / "popular.geojson").write_text(json.dumps(geojson))
    with open(config.HEAT_PKL, "wb") as f:
        pickle.dump(
            {
                "cells": popular,
                "trail_cells": popular_trail,
                "activity_cells": activity_cells,
                "areas": area_ids,
                "files": len(files),
                "min_passes": min_passes,
                "own_cells": len(own),
                "osm_cells": len(osm),
                "vlaanderen_fiets_cells": len(vlaanderen["fiets"]),
                "vlaanderen_wandel_cells": len(vlaanderen["wandel"]),
                "osm_min_points": osm_min_points,
            },
            f,
        )
    gh_config.write_gh_files()

    return {
        "gpx_bestanden": len(files),
        "eigen_cellen": len(own),
        "osm_cellen": len(osm),
        "vlaanderen_fiets_cellen": len(vlaanderen["fiets"]),
        "vlaanderen_wandel_cellen": len(vlaanderen["wandel"]),
        "cellen": len(popular),
        "polygonen": len(rects),
        "trail_cellen": len(popular_trail),
        "trail_polygonen": len(trail_rects),
        "kassei_tvl_cellen": len(cobble_tvl),
        "druk_tvl_cellen": len(busy_tvl),
        "activiteit_cellen": {
            activity: len(cells)
            for activity, cells in activity_areas.items()
        },
        "onverhard_cellen": len(unpaved),
        "areas": area_ids,
        "km_corridor": round(len(popular) * 0.13 * 0.13 / 0.13, 1),
        "toepassen": "rm -rf ~/.lusmaker/gh/graph-cache && docker compose restart graphhopper (herimport ~5 min)",
    }


def status() -> dict:
    files = sorted(config.HEAT_DIR.glob("*.gpx"))
    out = {"heat_dir": str(config.HEAT_DIR), "gpx_bestanden": [f.name for f in files]}
    if config.HEAT_PKL.exists():
        h = _load_heat()
        activity_cells = h.get("activity_cells")
        if not isinstance(activity_cells, dict):
            activity_cells = {}
        out["actief"] = {
            "cellen": len(h.get("cells", set())),
            "trail_cellen": len(h.get("trail_cells", set())),
            "min_passes": h.get("min_passes"),
            "activiteit_cellen": {
                activity: len(cells)
                for activity in ACTIVITIES
                for cells in [activity_cells.get(activity)]
                if isinstance(cells, dict) and cells
            },
        }
    else:
        out["actief"] = None
    return out


def popular_cells(profile: str = "quiet", *, fallback: bool = True) -> set | None:
    if not config.HEAT_PKL.exists():
        return None
    heat = _load_heat()
    if profile == "trail":
        trail_cells = heat.get("trail_cells")
        if trail_cells:
            return trail_cells
        if not fallback:
            return None
    return heat.get("cells")
