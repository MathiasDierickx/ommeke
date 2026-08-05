"""Persoonlijke heatmap uit eigen GPX-ritten.

Drop GPX-bestanden (Strava/Garmin bulk-export, toertocht-parcours) in
~/.lusmaker/heat/. `lus heat build` rastert ze op het ~130 m-celgrid, bouwt
corridor-polygonen en schrijft die als GraphHopper custom area ("popular").
Het quiet-profiel geeft bereden wegen dan een relatieve boost.

Let op: de area wordt bij de GRAAF-IMPORT ingebakken; na `heat build` moet de
graph-cache weg en GraphHopper herstarten (instructie in de output).
"""
import json
import pickle
import sys
import xml.etree.ElementTree as ET
from collections import defaultdict

from . import config, gh_config, geo


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

    counts: dict = defaultdict(int)
    total = 0
    for t, (l, b, r, tp) in enumerate(tiles):
        for page in range(max_pages_per_tile):
            url = (f"https://api.openstreetmap.org/api/0.6/trackpoints"
                   f"?bbox={l:.4f},{b:.4f},{r:.4f},{tp:.4f}&page={page}")
            req = urllib.request.Request(url, headers={"User-Agent": "lusmaker/0.1 (hobby routeplanner)"})
            try:
                with urllib.request.urlopen(req, timeout=60) as resp:
                    data = resp.read()
            except OSError as e:
                print(f"[heat] tegel {t} pagina {page}: {e} — stop deze tegel", file=sys.stderr)
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

    with open(config.OSM_TRACES_PKL, "wb") as f:
        pickle.dump({"counts": dict(counts), "points": total}, f)
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
