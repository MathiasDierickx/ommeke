"""Lengtegewogen routekwaliteit uit bronlijnen, met afstand- en richtingstoets.

Dit is geometrische matching, geen claim over GraphHopper-edge-identiteit of
toegankelijkheid. Ontbrekende of tegenstrijdige attributen blijven onbekend.
"""
from __future__ import annotations

import json
import math
import os
import sqlite3
from pathlib import Path

from . import config, geo

MATCH_RADIUS_M = 12.0
SAMPLE_STEP_M = 20.0


def pack_cache() -> Path | None:
    """Los een expliciet pack of een atomisch geactiveerde versie op."""
    override = os.environ.get("LUSMAKER_ROUTE_PACK")
    if override:
        root = Path(override).expanduser()
    else:
        pointer = config.CACHE / "route_sources" / "current.json"
        if not pointer.exists():
            return None
        name = json.loads(pointer.read_text())["build"]
        if len(name) != 20 or any(c not in "0123456789abcdef" for c in name):
            raise ValueError("ongeldige actieve routedataversie")
        root = pointer.parent / name
    cache = root / "home/regions/vlaanderen/cache"
    if not (cache / "route_sources.sqlite").is_file():
        raise ValueError(f"routedatapack ontbreekt of is onvolledig: {root}")
    return cache


def cache_file(name: str) -> Path:
    # Packs zijn regiogebonden. Een globale opt-in mag Zeeland niet veranderen.
    pack = pack_cache() if config.current_region().slug == "vlaanderen" else None
    return (pack or config.CACHE) / name


def database_path() -> Path | None:
    override = os.environ.get("LUSMAKER_ROUTE_DB")
    path = Path(override).expanduser() if override else cache_file("route_sources.sqlite")
    if override and not path.is_file():
        raise ValueError(f"ingestelde segmentdatabase ontbreekt: {path}")
    return path if path.is_file() else None


def pack_status() -> dict | None:
    """Publieke versie-informatie zonder lokale paden of gebruikersgegevens."""
    if config.current_region().slug != "vlaanderen":
        return None
    cache = pack_cache()
    if cache is None:
        return None
    manifest = json.loads((cache.parents[3] / "manifest.json").read_text())
    return {"build_id": manifest["build_id"],
            "features": sum(layer["features"] for layer in manifest["layers"].values()),
            "layers": len(manifest["sources"])}


def _matches(point, direction, line, radius):
    scale = 111320.0 * math.cos(math.radians(point[0]))
    dx, dy = direction
    norm = math.hypot(dx, dy)
    if not norm:
        return False
    for a, b in zip(line, line[1:]):
        ax, ay = (a[0] - point[1]) * scale, (a[1] - point[0]) * 111320.0
        bx, by = (b[0] - point[1]) * scale, (b[1] - point[0]) * 111320.0
        vx, vy = bx - ax, by - ay
        length = math.hypot(vx, vy)
        if not length or abs((vx * dx + vy * dy) / (length * norm)) < math.cos(math.radians(30)):
            continue
        fraction = max(0.0, min(1.0, -(ax * vx + ay * vy) / length ** 2))
        if math.hypot(ax + fraction * vx, ay + fraction * vy) <= radius:
            return True
    return False


class Evidence:
    def __init__(self, path):
        self.db = sqlite3.connect(Path(path).resolve().as_uri() + "?mode=ro", uri=True)
        self.parsed = {}
        self.cells = {}

    def close(self):
        self.db.close()

    def candidates(self, point, mode):
        cell = geo.cell(*point)
        key = (*cell, mode)
        if key not in self.cells:
            lat0, lon0 = cell[0] * geo.CELL_LAT, cell[1] * geo.CELL_LON
            padlat = MATCH_RADIUS_M / 111320.0
            padlon = MATCH_RADIUS_M / (111320.0 * math.cos(math.radians(point[0] + geo.CELL_LAT)))
            rows = self.db.execute("""SELECT f.id,f.layer,f.source_id,f.role,f.geometry,f.properties
                FROM bounds b CROSS JOIN feature f ON f.id=b.id
                WHERE b.minlon<=? AND b.maxlon>=? AND b.minlat<=? AND b.maxlat>=?
                  AND f.mode=? AND f.role IN ('network','surface','traffic')""",
                (lon0 + geo.CELL_LON + padlon, lon0 - padlon,
                 lat0 + geo.CELL_LAT + padlat, lat0 - padlat, mode))
            identifiers = []
            for identifier, layer, source_id, role, geometry, properties in rows:
                if identifier not in self.parsed:
                    geometry = json.loads(geometry)
                    lines = [geometry["coordinates"]] if geometry["type"] == "LineString" else geometry["coordinates"]
                    self.parsed[identifier] = (layer, source_id, role, lines, json.loads(properties))
                identifiers.append(identifier)
            self.cells[key] = identifiers
        return (self.parsed[identifier] for identifier in self.cells[key])

    def stats(self, legs, *, profile="quiet"):
        mode = "wandel" if profile in {"trail", "wandelen"} else "fiets"
        totals = dict(total=0.0, curated=0.0, score=0.0, paved=0.0,
                      unpaved=0.0, cobble=0.0, surface_known=0.0,
                      not_car_free=0.0, car_free=0.0)
        sources = set()
        for leg in legs:
            for a, b in zip(leg, leg[1:]):
                distance = geo.haversine(*a[:2], *b[:2])
                if not distance:
                    continue
                parts = max(1, math.ceil(distance / SAMPLE_STEP_M))
                length = distance / parts
                direction = ((b[1] - a[1]) * math.cos(math.radians((a[0] + b[0]) / 2)), b[0] - a[0])
                for part in range(parts):
                    t = (part + 0.5) / parts
                    point = (a[0] + t * (b[0] - a[0]), a[1] + t * (b[1] - a[1]))
                    curated, surfaces, traffic = 0.0, set(), set()
                    for layer, source_id, role, lines, properties in self.candidates(point, mode):
                        if not any(_matches(point, direction, line, MATCH_RADIUS_M) for line in lines):
                            continue
                        sources.add(layer)
                        if role == "network":
                            # Een traject in meerdere bronnen krijgt hoogstens
                            # de sterkste curatiebonus, nooit een som van stemmen.
                            curated = max(curated, 0.8 if "icoonroute" in layer else 0.6)
                        elif role == "surface":
                            value = str(properties.get("ground") or "").strip().casefold()
                            if value:
                                surfaces.add(value)
                        elif role == "traffic":
                            value = str(properties.get("traffic") or "").strip().casefold()
                            if value:
                                traffic.add(value)
                    totals["total"] += length
                    totals["curated"] += length if curated else 0
                    totals["score"] += length * curated
                    if len(surfaces) == 1:
                        key = {"verhard": "paved", "onverhard": "unpaved", "kassei": "cobble"}.get(next(iter(surfaces)))
                        if key:
                            totals[key] += length
                            totals["surface_known"] += length
                    if "niet-autovrij" in traffic:
                        totals["not_car_free"] += length
                    elif traffic == {"autovrij"}:
                        totals["car_free"] += length
        total = max(totals["total"], 1.0)
        traffic_known = totals["not_car_free"] + totals["car_free"]
        return {
            "bron": "Toerisme Vlaanderen / provinciale toeristische organisaties",
            "activiteit": mode, "matching": "afstand_en_richting", "tolerantie_m": MATCH_RADIUS_M,
            "lengte_m": round(totals["total"]),
            "gecureerd_pct": round(100 * totals["curated"] / total, 1),
            "curatie_score": round(totals["score"] / total, 4),
            "wegdek_bekend_pct": round(100 * totals["surface_known"] / total, 1),
            "verhard_m": round(totals["paved"]), "onverhard_m": round(totals["unpaved"]),
            "kassei_m": round(totals["cobble"]),
            "niet_autovrij_pct": round(100 * totals["not_car_free"] / total, 1),
            "bevestigd_autovrij_pct": round(100 * totals["car_free"] / total, 1),
            "verkeer_onbekend_pct": round(100 * (totals["total"] - traffic_known) / total, 1),
            "lagen": sorted(sources), "buggygeschiktheid": "onbekend",
        }


def route_stats(legs, profile="quiet", *, database=None):
    path = Path(database) if database is not None else database_path()
    if path is None:
        return None
    evidence = Evidence(path)
    try:
        return evidence.stats(legs, profile=profile)
    finally:
        evidence.close()
