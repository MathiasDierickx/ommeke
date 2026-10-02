"""Publieke Toerisme Vlaanderen-plaatsen uit het actieve bronpack, zonder netwerk."""
from __future__ import annotations

import json
import math
import sqlite3

from . import config, geo, route_evidence

ATTRIBUTES = ("access", "wheelchair", "opening_hours", "fee", "charge",
              "changing_table", "changing_tablelocation", "toiletshandwashing",
              "drinking_water", "covered", "backrest", "operator")
KINDS = {"HOTEL": "hotel", "BED_AND_BREAKFAST": "bed_and_breakfast",
         "CAMPING": "camping", "HOLIDAY_COTTAGE": "vakantiewoning",
         "CAMPER_TERRAIN": "camperterrein", "HOSTEL": "hostel",
         "YOUTH_ACCOMMODATION": "jeugdverblijf", "HOLIDAY_PARK": "vakantiepark"}


def _records(bbox, *, database=None):
    if database is None and config.current_region().slug != "vlaanderen":
        return []
    path = database or route_evidence.database_path()
    if path is None:
        return []
    from pathlib import Path
    south, west, north, east = bbox
    with sqlite3.connect(Path(path).resolve().as_uri() + "?mode=ro", uri=True) as db:
        sources = {layer: json.loads(metadata) for layer, metadata in db.execute("SELECT layer,metadata FROM source")}
        rows = db.execute("""SELECT f.layer,f.source_id,f.geometry,f.properties
            FROM bounds b CROSS JOIN feature f ON f.id=b.id
            WHERE b.minlon<=? AND b.maxlon>=? AND b.minlat<=? AND b.maxlat>=?
              AND f.role IN ('poi','lodging') ORDER BY f.layer,f.source_id""", (east, west, north, south))
        found = {}
        for layer, source_id, geometry, properties in rows:
            geometry, props, source = json.loads(geometry), json.loads(properties), sources[layer]
            if geometry["type"] != "Point" or props.get("access") in {"private", "no"}:
                continue
            lon, lat = geometry["coordinates"][:2]
            lodging = layer.startswith("lodging:")
            kind = KINDS.get(props.get("discriminator"), "logies") if lodging else layer.split(":", 1)[1]
            identifier = (f"tvl:logies:{props['business_product_id']}" if lodging else f"tvl:{layer}:{source_id}")
            cycle = layer == "lodging:lodging_to_iconic_cycle_routes"
            item = {"id": identifier, "kind": kind, "name": props.get("name") or kind,
                    "lat": lat, "lon": lon, "source": source["source_url"],
                    "attribution": source["attribution"], "license": source["license"],
                    "source_layer": layer, "coordinate_kind": "mapped_point",
                    "data_timestamp": source.get("downloaded_at"),
                    **{key: props.get(key) for key in ATTRIBUTES}}
            if lodging:
                item.update(city=props.get("city_name"), category=props.get("discriminator"),
                            registration_status=props.get("status"), website=props.get("website"),
                            cycle_route_lodging=cycle, near_to=props.get("near_to"))
            # De icoonrouteselectie verrijkt hetzelfde basisregisterrecord.
            if identifier not in found or cycle:
                found[identifier] = item
        return list(found.values())


def nearby(lat, lon, radius_m=500, *, kinds=None, database=None):
    padlat = radius_m / 110000
    padlon = padlat / max(.01, math.cos(math.radians(lat)))
    result = []
    for item in _records((lat-padlat, lon-padlon, lat+padlat, lon+padlon), database=database):
        distance = geo.haversine(lat, lon, item["lat"], item["lon"])
        if distance <= radius_m and (kinds is None or item["kind"] in kinds):
            result.append({**item, "label": item["name"], "distance_m": round(distance)})
    return sorted(result, key=lambda p: (p["distance_m"], p["id"]))


def icon_nodes(*, database=None):
    """Knooplabels bij icoonroutes; dezelfde knoop kan in meerdere routes zitten."""
    if database is None and config.current_region().slug != "vlaanderen":
        return []
    path = database or route_evidence.database_path()
    if path is None:
        return []
    from pathlib import Path
    with sqlite3.connect(Path(path).resolve().as_uri() + "?mode=ro", uri=True) as db:
        result = []
        for geometry, properties in db.execute("SELECT geometry,properties FROM feature WHERE layer='routes:icoonroute_knooppunten'"):
            geometry, props = json.loads(geometry), json.loads(properties)
            if geometry['type'] == 'Point' and props.get('knoopnr') is not None:
                try:
                    number = float(props['knoopnr'])
                except (TypeError, ValueError):
                    continue
                if not math.isfinite(number) or number < 0:
                    continue
                number = int(number) if number.is_integer() else number
                lon, lat = geometry['coordinates'][:2]
                result.append({'lat': lat, 'lon': lon, 'nummer': number,
                               'type': 'fiets', 'icoonroute': props.get('icoonroute'),
                               'beheerder': props.get('eigenaar'), 'meldpunt': props.get('meldpunt')})
        return result


def along_route(legs, *, radius_m=150, limit=100, database=None):
    from .route_pois import project
    legs = [leg for leg in legs if len(leg) >= 2]
    if not legs:
        return []
    points = [point for leg in legs for point in leg]
    padlat = radius_m / 110000
    padlon = padlat / math.cos(math.radians(max(p[0] for p in points)))
    bbox = (min(p[0] for p in points)-padlat, min(p[1] for p in points)-padlon,
            max(p[0] for p in points)+padlat, max(p[1] for p in points)+padlon)
    cells = set().union(*(geo.cells_for_geom([p[:2] for p in leg], expand=max(1, math.ceil(radius_m/120))) for leg in legs))
    starts, distance = [], 0
    for leg in legs:
        starts.append(distance)
        distance += geo.path_length(leg)
    result = []
    for item in _records(bbox, database=database):
        if item["source_layer"].startswith("lodging:") and not item.get("cycle_route_lodging"):
            continue  # geen duizenden vakantiewoningen als standaard route-stops
        if geo.cell(item["lat"], item["lon"]) not in cells:
            continue
        matches = []
        for start, leg in zip(starts, legs):
            offset, along, _, _ = project((item["lat"], item["lon"]), leg)
            matches.append((offset, start+along))
        offset, along = min(matches)
        if offset <= radius_m:
            result.append({**item, "offset_m": round(offset), "at_km": round(along/1000, 3)})
    return sorted(result, key=lambda p: (p["at_km"], p["id"]))[:limit]
