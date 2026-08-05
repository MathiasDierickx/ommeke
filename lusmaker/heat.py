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


def build(min_passes: int = 1) -> dict:
    config.ensure_dirs()
    files = sorted(config.HEAT_DIR.glob("*.gpx"))
    if not files:
        raise RuntimeError(f"geen GPX-bestanden in {config.HEAT_DIR} — drop daar je ritten")

    cell_sources = defaultdict(set)
    for fi, f in enumerate(files):
        pts = _parse_gpx(f)
        if len(pts) < 10:
            continue
        for c in _track_cells(pts):
            cell_sources[c].add(fi)

    popular = {c for c, srcs in cell_sources.items() if len(srcs) >= min_passes}
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
        pickle.dump({"cells": popular, "files": len(files), "min_passes": min_passes}, f)
    gh_config.write_gh_files()  # quiet.json krijgt nu de !in_popular-regel

    return {
        "gpx_bestanden": len(files),
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
