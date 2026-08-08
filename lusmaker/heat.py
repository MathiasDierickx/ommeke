"""Persoonlijke heatmap uit eigen GPX-ritten.

Drop GPX-bestanden (Strava/Garmin bulk-export, toertocht-parcours) in
~/.lusmaker/heat/. `lus heat build` rastert ze op het ~130 m-celgrid, bouwt
corridor-polygonen en schrijft die als GraphHopper custom area ("popular").
Het quiet-profiel geeft bereden wegen dan een relatieve boost.

Let op: de area wordt bij de GRAAF-IMPORT ingebakken; na `heat build` moet de
graph-cache weg en GraphHopper herstarten (instructie in de output).
"""
import json
import math
import pickle
import sys
import xml.etree.ElementTree as ET
from collections import defaultdict
from urllib.parse import urlencode

from . import config, gh_config, geo


# Bron: https://data.toerismevlaanderen.be, datasets
# cycling_node_network_v2, hiking_node_network_v2 en lf_routes uit workspace
# geoservices_v2. Licentie: Modellicentie Gratis Hergebruik.
TOERISME_VLAANDEREN_WFS = (
    "https://data.toerismevlaanderen.be/geoserver/geoservices_v2/ows"
)
CYCLING_NODE_NETWORK_WFS_URL = (
    f"{TOERISME_VLAANDEREN_WFS}?service=WFS&version=2.0.0"
    "&request=GetFeature&typeNames=geoservices_v2%3Acycling_node_network_v2"
    "&outputFormat=application%2Fjson&srsName=EPSG%3A4326"
)
HIKING_NODE_NETWORK_WFS_URL = (
    f"{TOERISME_VLAANDEREN_WFS}?service=WFS&version=2.0.0"
    "&request=GetFeature&typeNames=geoservices_v2%3Ahiking_node_network_v2"
    "&outputFormat=application%2Fjson&srsName=EPSG%3A4326"
)
LF_ROUTES_WFS_URL = (
    f"{TOERISME_VLAANDEREN_WFS}?service=WFS&version=2.0.0"
    "&request=GetFeature&typeNames=geoservices_v2%3Alf_routes"
    "&outputFormat=application%2Fjson&srsName=EPSG%3A4326"
)
VLAANDEREN_ROUTE_LAYERS = {
    "fietsnetwerk": (
        "fiets",
        "cycling_node_network_v2",
        CYCLING_NODE_NETWORK_WFS_URL,
    ),
    "wandelnetwerken": (
        "wandel",
        "hiking_node_network_v2",
        HIKING_NODE_NETWORK_WFS_URL,
    ),
    "LF- en icoonroutes": ("fiets", "lf_routes", LF_ROUTES_WFS_URL),
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


def fetch_vlaanderen(fetcher=_fetch_url) -> dict:
    """Download en cache de fiets- en wandelroutelagen voor de regio-bbox."""
    config.ensure_dirs()
    routes = {"fiets": set(), "wandel": set()}
    layer_counts = {}
    for label, (kind, layer, base_url) in VLAANDEREN_ROUTE_LAYERS.items():
        print(f"[heat] Toerisme Vlaanderen: {label} downloaden", file=sys.stderr)
        url = _vlaanderen_wfs_url(base_url, config.BBOX)
        try:
            payload = fetcher(url)
        except Exception as exc:
            code = getattr(exc, "code", None)
            detail = f"HTTP {code}" if code is not None else str(exc)
            raise RuntimeError(f"{label}: WFS-download mislukt ({detail})") from exc
        document = _geojson_document(payload, label)
        cells = _geojson_cells(document)
        routes[kind].update(cells)
        layer_counts[layer] = len(cells)
        print(
            f"[heat] Toerisme Vlaanderen: {label} — {len(cells)} cellen",
            file=sys.stderr,
        )

    with open(config.VLAANDEREN_ROUTES_PKL, "wb") as handle:
        pickle.dump(routes, handle)
    return {
        "regio": config.current_region().slug,
        "fiets_cellen": len(routes["fiets"]),
        "wandel_cellen": len(routes["wandel"]),
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


def build(min_passes: int = 1, osm_min_points: int = 30) -> dict:
    config.ensure_dirs()
    files = sorted(config.HEAT_DIR.glob("*.gpx"))

    cell_sources = defaultdict(set)
    for fi, f in enumerate(files):
        pts = _parse_gpx(f)
        if len(pts) < 10:
            continue
        for c in _track_cells(pts):
            cell_sources[c].add(fi)

    own = {c for c, srcs in cell_sources.items() if len(srcs) >= min_passes}
    osm = _osm_cells(osm_min_points)
    popular = own | osm
    if not popular:
        raise RuntimeError(
            f"geen data: drop GPX-ritten in {config.HEAT_DIR} en/of draai `lus heat fetch-osm`"
        )
    rects = _rects(popular)

    geojson = {
        "type": "FeatureCollection",
        "features": [
            {
                "type": "Feature",
                "id": "popular",
                "properties": {},
                "geometry": {
                    "type": "MultiPolygon",
                    "coordinates": [[[[round(x, 6), round(y, 6)] for x, y in ring]] for ring in rects],
                },
            }
        ],
    }
    (config.CUSTOM_AREAS / "popular.geojson").write_text(json.dumps(geojson))
    with open(config.HEAT_PKL, "wb") as f:
        pickle.dump({"cells": popular, "files": len(files), "min_passes": min_passes,
                     "own_cells": len(own), "osm_cells": len(osm),
                     "osm_min_points": osm_min_points}, f)
    gh_config.write_gh_files()  # quiet.json krijgt nu de !in_popular-regel

    return {
        "gpx_bestanden": len(files),
        "eigen_cellen": len(own),
        "osm_cellen": len(osm),
        "cellen": len(popular),
        "polygonen": len(rects),
        "km_corridor": round(len(popular) * 0.13 * 0.13 / 0.13, 1),
        "toepassen": "rm -rf ~/.lusmaker/gh/graph-cache && docker compose restart graphhopper (herimport ~5 min)",
    }


def status() -> dict:
    files = sorted(config.HEAT_DIR.glob("*.gpx"))
    out = {"heat_dir": str(config.HEAT_DIR), "gpx_bestanden": [f.name for f in files]}
    if config.HEAT_PKL.exists():
        with open(config.HEAT_PKL, "rb") as f:
            h = pickle.load(f)
        out["actief"] = {"cellen": len(h["cells"]), "min_passes": h["min_passes"]}
    else:
        out["actief"] = None
    return out


def popular_cells() -> set | None:
    if not config.HEAT_PKL.exists():
        return None
    with open(config.HEAT_PKL, "rb") as f:
        return pickle.load(f)["cells"]
