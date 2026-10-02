"""Reproduceerbare openbare routedata: WFS-snapshots en offline builds.

Deze beheerpipeline schrijft uitsluitend in de expliciete uitvoermap. Zij
installeert of herstart geen runtime. Onbekende/persoonlijke GPX-seeds worden
niet opgenomen in de gedeelde dataset.
"""
from __future__ import annotations

import hashlib
import json
import math
import os
import shutil
import sqlite3
import sys
import tempfile
import time
import urllib.error
import urllib.request
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path
from urllib.parse import urlencode

from . import config, heat

FORMAT_VERSION = 4
FLANDERS_BBOX = (50.67, 2.53, 51.51, 5.94)
SOURCE_URL = "https://toerismevlaanderen.be/nl/cijfers/open-data"
ROUTE_LICENSE = "https://data.vlaanderen.be/id/licentie/modellicentie-gratis-hergebruik/v1.0"
OSM_LICENSE = "https://www.openstreetmap.org/copyright"


def layers() -> list[dict]:
    """Expliciete allowlist van openbare Vlaamse route- en plaatsgegevens."""
    result = []
    for _, (mode, layer, _) in heat.VLAANDEREN_ROUTE_LAYERS.items():
        result.append(dict(layer=layer, mode=mode, role="network"))
    for group, role in ((heat.VLAANDEREN_SURFACE_LAYERS, "surface"),
                        (heat.VLAANDEREN_TRAFFIC_LAYERS, "traffic")):
        for _, (layer, _) in group.items():
            result.append(dict(layer=layer, mode="fiets" if layer.endswith("fiets") else "wandel", role=role))
    for kind, (layer, _) in heat.VLAANDEREN_POI_LAYERS.items():
        result.append(dict(layer=layer, mode="all", role="poi", kind=kind))
    for _, (mode, layer, _) in heat.VLAANDEREN_KNOT_LAYERS.items():
        result.append(dict(layer=layer, mode=mode, role="node"))
    # Virtuele netwerken zijn apart herkenbaar en krijgen geen automatische
    # bonus voor bewegwijzering. Wel bewaren voor inspectie en latere curatie.
    result.append(dict(layer="routes:traject_wandel_virtueel", mode="wandel", role="virtual_network"))
    for spec in result:
        spec["license"] = OSM_LICENSE if spec["role"] == "poi" else ROUTE_LICENSE
        spec["attribution"] = ("© OpenStreetMap contributors; ontsloten door Toerisme Vlaanderen"
                               if spec["role"] == "poi" else "Toerisme Vlaanderen en de provinciale toeristische organisaties")
        spec["source_url"] = SOURCE_URL
    result.append(dict(layer="routes:icoonroute_knooppunten", mode="fiets", role="node",
                       license=ROUTE_LICENSE, attribution="Toerisme Vlaanderen en de provinciale toeristische organisaties",
                       source_url=SOURCE_URL))
    for layer in ("lodging:base_registry_all_lodging", "lodging:lodging_to_iconic_cycle_routes"):
        properties = ["geom", "business_product_id", "name", "discriminator", "city_name",
                      "postal_code", "website", "status", "comfort_class", "changed_time"]
        if layer.endswith("iconic_cycle_routes"):
            properties.append("near_to")
        result.append(dict(layer=layer, mode="all", role="lodging", sort_by="business_product_id",
                           property_names=properties, license=SOURCE_URL,
                           attribution="Toerisme Vlaanderen — Basisregister Vlaams Logiesaanbod",
                           source_url=SOURCE_URL))
    return result


def _json_bytes(value) -> bytes:
    return (json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False) + "\n").encode()


def _sha(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _atomic_json(path: Path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(dir=path.parent, delete=False) as handle:
        temporary = Path(handle.name)
        handle.write(_json_bytes(value))
    try:
        temporary.replace(path)
    finally:
        temporary.unlink(missing_ok=True)


def fetch_url(url: str) -> bytes:
    """Alleen publieke WFS-GET's; begrensde retries buiten de testsuite."""
    request = urllib.request.Request(url, headers={"User-Agent": "Ommeke-Lusmaker/0.1 (open route data import)"})
    for attempt in range(4):
        try:
            with urllib.request.urlopen(request, timeout=90) as response:
                return response.read()
        except urllib.error.HTTPError as exc:
            if exc.code not in {429, 500, 502, 503, 504} or attempt == 3:
                raise RuntimeError(f"WFS-download mislukt: HTTP {exc.code}") from exc
        except OSError as exc:
            if attempt == 3:
                raise RuntimeError(f"WFS-download mislukt: {exc}") from exc
        time.sleep(2 ** attempt)
    raise RuntimeError("WFS-download mislukt")


def _coordinates(geometry):
    if not isinstance(geometry, dict):
        raise ValueError("feature zonder geometrie")
    kind = geometry.get("type")
    coords = geometry.get("coordinates")
    if kind == "Point":
        points = [coords]
    elif kind in {"LineString", "MultiPoint"}:
        points = coords
    elif kind == "MultiLineString":
        points = [point for line in coords for point in line]
    else:
        raise ValueError(f"onverwacht geometrietype: {kind}")
    if not points:
        raise ValueError("lege geometrie")
    for point in points:
        if not isinstance(point, (list, tuple)) or len(point) < 2:
            raise ValueError("ongeldig coördinatenpaar")
        lon, lat = point[:2]
        if not all(isinstance(v, (int, float)) and math.isfinite(v) for v in (lon, lat)):
            raise ValueError("niet-eindige coördinaat")
        # Deze feed hoort Vlaanderen en aansluitende grensroutes te bevatten.
        # Lambert-coördinaten of een verwisselde asvolgorde vallen zo op.
        if not (1 < lon < 9 and 48 < lat < 54):
            raise ValueError("coördinaten buiten Vlaanderen/grensregio; verwacht WGS84 lon,lat")
        yield lon, lat


def download_layer(spec, *, fetcher=fetch_url, page_size=1000) -> tuple[dict, dict]:
    if not 1 <= page_size <= 10000:
        raise ValueError("paginagrootte moet tussen 1 en 10000 liggen")
    features, seen, requests = [], set(), []
    expected = None
    while True:
        parameters = {
            "service": "WFS", "version": "2.0.0", "request": "GetFeature",
            "typeNames": spec["layer"], "outputFormat": "application/json",
            "srsName": "EPSG:4326", "count": page_size,
            "startIndex": len(features), "sortBy": spec.get("sort_by", "objectid") + " A",
        }
        if spec.get("property_names"):
            parameters["propertyName"] = ",".join(spec["property_names"])
        url = heat.TOERISME_VLAANDEREN_WFS + "?" + urlencode(parameters)
        document = heat._geojson_document(fetcher(url), spec["layer"])
        page = document["features"]
        matched = document.get("numberMatched", document.get("totalFeatures"))
        if matched not in (None, "unknown"):
            matched = int(matched)
            if matched < 0 or (expected is not None and matched != expected):
                raise ValueError(f"{spec['layer']}: bronaantal veranderde tijdens downloaden; probeer opnieuw")
            expected = matched
        if document.get("numberReturned") is not None and int(document["numberReturned"]) != len(page):
            raise ValueError(f"{spec['layer']}: onvolledig WFS-antwoord")
        requests.append(url)
        for feature in page:
            identifier = feature.get("id")
            if not identifier or not isinstance(identifier, str) or identifier in seen:
                raise ValueError(f"{spec['layer']}: ontbrekende/dubbele feature-ID; onbetrouwbare paginering")
            list(_coordinates(feature.get("geometry")))
            if not isinstance(feature.get("properties"), dict):
                raise ValueError(f"{identifier}: ontbrekende attributen")
            seen.add(identifier)
            features.append(feature)
        if expected is not None:
            if len(features) > expected or (not page and len(features) < expected):
                raise ValueError(f"{spec['layer']}: onvolledige download ({len(features)}/{expected})")
            if len(features) == expected:
                break
        elif not page:
            break
        if len(requests) >= 10000:
            raise ValueError("WFS-paginering overschrijdt veiligheidslimiet")
    if spec["role"] == "network" and not features:
        raise ValueError(f"{spec['layer']}: lege kernlaag")
    return {"type": "FeatureCollection", "features": features}, {
        **spec, "downloaded_at": datetime.now(UTC).isoformat(),
        "feature_count": len(features), "requests": requests,
    }


def _snapshot(root, spec, fetcher, page_size, offline, refresh):
    name = spec["layer"].replace(":", "_")
    marker = root / "raw" / f"{name}.json"
    if marker.exists() and not refresh:
        metadata = json.loads(marker.read_text())
        digest = metadata["sha256"]
        if len(digest) != 64 or any(c not in "0123456789abcdef" for c in digest):
            raise ValueError(f"ongeldige snapshot-hash: {name}")
        source = root / "raw" / f"{digest}.geojson"
        if _sha(source) != digest or any(metadata.get(k) != v for k, v in spec.items()):
            raise ValueError(f"snapshot gewijzigd: {name}; download opnieuw met --refresh")
        return source, metadata
    if offline:
        raise ValueError(f"snapshot ontbreekt: {name}; voer eerst sync-vlaanderen uit")
    print(f"[routedata] {spec['layer']} downloaden", file=sys.stderr)
    document, metadata = download_layer(spec, fetcher=fetcher, page_size=page_size)
    payload = _json_bytes(document)
    digest = hashlib.sha256(payload).hexdigest()
    source = root / "raw" / f"{digest}.geojson"
    if not source.exists():
        _atomic_json(source, document)
    metadata["sha256"] = digest
    metadata["bytes"] = len(payload)
    _atomic_json(marker, metadata)
    return source, metadata


@contextmanager
def _home(path):
    previous = os.environ.get("LUSMAKER_HOME")
    overrides = {key: os.environ.pop(key, None) for key in ("LUSMAKER_ROUTE_PACK", "LUSMAKER_ROUTE_DB")}
    os.environ["LUSMAKER_HOME"] = str(path)
    try:
        with config.use_region("vlaanderen"):
            yield
    finally:
        if previous is None:
            os.environ.pop("LUSMAKER_HOME", None)
        else:
            os.environ["LUSMAKER_HOME"] = previous
        for key, value in overrides.items():
            if value is not None:
                os.environ[key] = value


def build_database(path: Path, snapshots):
    """Bewaar de volledige bronfeatures; ruimtelijke index zonder extra deps."""
    summaries = {}
    with sqlite3.connect(path) as db:
        db.executescript("""
            CREATE TABLE source(layer TEXT PRIMARY KEY, metadata TEXT NOT NULL);
            CREATE TABLE feature(id INTEGER PRIMARY KEY, layer TEXT NOT NULL,
                source_id TEXT NOT NULL, mode TEXT NOT NULL, role TEXT NOT NULL,
                geometry TEXT NOT NULL, properties TEXT NOT NULL,
                UNIQUE(layer, source_id));
            CREATE VIRTUAL TABLE bounds USING rtree(id, minlon, maxlon, minlat, maxlat);
            CREATE INDEX feature_mode_role ON feature(mode,role);
        """)
        for source, metadata in snapshots:
            document = json.loads(source.read_text())
            layer = metadata["layer"]
            db.execute("INSERT INTO source VALUES (?,?)", (layer, _json_bytes(metadata).decode()))
            values = {}
            for feature in document["features"]:
                points = list(_coordinates(feature["geometry"]))
                role = metadata["role"]
                if role == "network" and "virtual" in str(feature["properties"].get("virtual", "")).casefold():
                    role = "virtual_network"
                cursor = db.execute("INSERT INTO feature(layer,source_id,mode,role,geometry,properties) VALUES (?,?,?,?,?,?)",
                                    (layer, feature["id"], metadata["mode"], role,
                                     _json_bytes(feature["geometry"]).decode(), _json_bytes(feature["properties"]).decode()))
                db.execute("INSERT INTO bounds VALUES (?,?,?,?,?)", (cursor.lastrowid,
                           min(p[0] for p in points), max(p[0] for p in points),
                           min(p[1] for p in points), max(p[1] for p in points)))
                for key in ("ground", "traffic", "virtual", "updatedate"):
                    if key in feature["properties"]:
                        value = feature["properties"][key]
                        value = str(value) if value not in (None, "") else "onbekend"
                        counts = values.setdefault(key, {})
                        counts[value] = counts.get(value, 0) + 1
            summaries[layer] = {"features": len(document["features"]), "attributen": values}
        db.execute(f"PRAGMA user_version={FORMAT_VERSION}")
        if db.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
            raise ValueError("segmentdatabase is beschadigd")
    return summaries


def _build(root: Path, snapshots, digest):
    home = root / "home"
    config.register_region("vlaanderen", "europe/belgium", FLANDERS_BBOX, 8989, home=home)
    cache = home / "regions" / "vlaanderen" / "cache"
    cache.mkdir(parents=True, exist_ok=True)
    database = cache / "route_sources.sqlite"
    summaries = build_database(database, snapshots)
    sources = {metadata["layer"]: source for source, metadata in snapshots}

    def local_fetch(url):
        from urllib.parse import parse_qs, urlparse
        layer = parse_qs(urlparse(url).query)["typeNames"][0]
        return sources[layer].read_bytes()

    with _home(home):
        imported = heat.fetch_vlaanderen(fetcher=local_fetch)
        built = heat.build()
    # Geen bestaande GPX-, OSM-trace- of activiteitentellers kopiëren.
    return {"format_version": FORMAT_VERSION, "build_id": digest,
            "bbox_lat_lon": list(FLANDERS_BBOX), "sources": [meta for _, meta in snapshots],
            "layers": summaries, "import": imported, "heat": built,
            "contains_personal_heat": False,
            "limitations": ["Netwerkdeelname is curatie, geen gemeten populariteit.",
                            "Niet-autovrij is geen verkeersdruktemeting; ontbrekende waarden blijven onbekend.",
                            "Segmentmatching gebruikt afstand en richting, geen GraphHopper-edge-ID.",
                            "Geen garantie voor buggytoegankelijkheid.",
                            "De gegenereerde GH-areas gebruiken nog het bestaande circa 130 m-raster.",
                            "Activering en live routeacceptatie gebeuren afzonderlijk door de beheerder."]}


def sync(output, *, offline=False, refresh=False, page_size=1000, fetcher=fetch_url):
    heat._require_local_admin()
    if offline and refresh:
        raise ValueError("--offline en --refresh kunnen niet samen")
    root = Path(output).expanduser().resolve()
    runtime = config.home_path().resolve()
    if root == runtime or runtime in root.parents:
        raise ValueError("kies een uitvoermap buiten de actieve LUSMAKER_HOME; import wordt eerst gestaged")
    root.mkdir(parents=True, exist_ok=True)
    (root / "raw").mkdir(exist_ok=True)
    lock = root / ".sync.lock"
    try:
        fd = os.open(lock, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
    except FileExistsError as exc:
        raise ValueError("er loopt al een import (of een onderbroken import liet .sync.lock achter)") from exc
    os.close(fd)
    try:
        snapshots = [_snapshot(root, spec, fetcher, page_size, offline, refresh) for spec in layers()]
        digest = hashlib.sha256(_json_bytes({"version": FORMAT_VERSION, "bbox": FLANDERS_BBOX,
                    "sources": [(meta["layer"], meta["sha256"], meta["license"]) for _, meta in snapshots]})).hexdigest()
        builds = root / "builds"
        builds.mkdir(exist_ok=True)
        target = builds / digest[:20]
        if not target.exists():
            temporary = Path(tempfile.mkdtemp(prefix=".build-", dir=builds))
            try:
                manifest = _build(temporary, snapshots, digest)
                # Uitvoerpad in diagnostiek moet ook na de atomische rename kloppen.
                manifest["import"]["cache"] = "home/regions/vlaanderen/cache/vlaanderen_routes.pkl"
                manifest["heat"]["toepassen"] = "Laat de beheerder dit pack beoordelen en de graaf herimporteren."
                _atomic_json(temporary / "manifest.json", manifest)
                hashes = {str(path.relative_to(temporary)): _sha(path)
                          for path in sorted(temporary.rglob("*")) if path.is_file()}
                _atomic_json(temporary / "checksums.json", hashes)
                temporary.rename(target)
            finally:
                if temporary.exists():
                    shutil.rmtree(temporary)
        report = verify(target)
        _atomic_json(root / "current.json", {"build": str(target.relative_to(root)), "build_id": digest})
        return {**report, "build": str(target), "home": str(target / "home"),
                "database": str(target / "home/regions/vlaanderen/cache/route_sources.sqlite"),
                "runtime_geactiveerd": False}
    finally:
        lock.unlink(missing_ok=True)


def verify(build) -> dict:
    root = Path(build).resolve()
    hashes = json.loads((root / "checksums.json").read_text())
    required = {"manifest.json", "home/regions/vlaanderen/cache/route_sources.sqlite",
                "home/regions/vlaanderen/cache/vlaanderen_routes.pkl",
                "home/regions/vlaanderen/cache/heat.pkl",
                "home/regions/vlaanderen/gh/custom_areas/popular.geojson"}
    if not required <= hashes.keys():
        raise ValueError("onvolledig routedatapack: verplichte bestanden ontbreken")
    for name, expected in hashes.items():
        path = (root / name).resolve()
        if root not in path.parents or _sha(path) != expected:
            raise ValueError(f"buildbestand gewijzigd of ongeldig: {name}")
    manifest = json.loads((root / "manifest.json").read_text())
    if manifest["format_version"] not in {3, FORMAT_VERSION}:
        raise ValueError("incompatibel routedatapack; bouw opnieuw uit snapshots")
    return {"ok": True, "build_id": manifest["build_id"], "lagen": len(manifest["sources"]),
            "features": sum(item["features"] for item in manifest["layers"].values()),
            "bronvermelding": sorted({s["attribution"] for s in manifest["sources"]})}


def audit_legacy():
    """Alleen eigen lokale pickle-cache lezen; nooit gedownloade pickles openen."""
    import pickle
    from . import geo

    path = config.HEAT_PKL
    if not path.exists():
        return {"aanwezig": False, "cache": str(path)}
    with path.open("rb") as handle:
        data = pickle.load(handle)
    activities = {}
    for activity, counts in (data.get("activity_cells") or {}).items():
        cells = list(counts)
        if not cells:
            continue
        lats = [cell[0] * geo.CELL_LAT for cell in cells]
        lons = [cell[1] * geo.CELL_LON for cell in cells]
        activities[activity] = {
            "cellen": len(cells), "tellingen": sum(counts.values()),
            "bbox_lat_lon": [min(lats), min(lons), max(lats), max(lons)],
            "bron": "onbekend", "licentie": "onbekend", "opgenomen_in_nieuw_pack": False,
        }
    area_file = config.CUSTOM_AREAS / "popular.geojson"
    areas = ([feature.get("id") for feature in json.loads(area_file.read_text()).get("features", [])]
             if area_file.exists() else [])
    return {"aanwezig": True, "cache": str(path), "sha256": _sha(path),
            "bbox_huidige_regio": list(config.BBOX), "activiteiten": activities,
            "gegenereerde_areas": areas, "eigen_gpx_bestanden": data.get("files", 0),
            "runtime_activatie_gecontroleerd": False,
            "advies": "Bewaar deze seeds apart tot bron en rechten aantoonbaar zijn; importeer geen nieuwe stemmen uit eigen gegenereerde routes."}


def install(build, *, apply=False):
    """Plan standaard; expliciete activatie vervangt alleen een versiepointer.

    De oorspronkelijke caches en GraphHopper-bestanden blijven behouden.
    Routeringsareas vergen nog een bewuste build/herimport door de beheerder.
    """
    heat._require_local_admin()
    if config.current_region().slug != "vlaanderen":
        raise ValueError("dit pack is alleen voor regio vlaanderen")
    source = Path(build).expanduser().resolve()
    report = verify(source)
    name = report["build_id"][:20]
    destination = config.CACHE / "route_sources" / name
    pointer = destination.parent / "current.json"
    previous = json.loads(pointer.read_text()) if pointer.exists() else None
    plan = {"ok": True, "toegepast": False, "bron": str(source),
            "bestemming": str(destination), "vorige_versie": previous,
            "build_id": report["build_id"],
            "direct": ["segmentkwaliteit en gewogen kandidaatselectie", "Vlaamse wegdekdata, knooppunten en voorzieningen"],
            "nog_te_doen": "Gebruik de gegenereerde gh/custom_areas en gh/custom_models van dit pack voor een door de beheerder uitgevoerde graafherimport; er is geen herstart uitgevoerd."}
    if not apply:
        return plan
    destination.parent.mkdir(parents=True, exist_ok=True)
    if not destination.exists():
        temporary = Path(tempfile.mkdtemp(prefix=".install-", dir=destination.parent))
        try:
            shutil.copytree(source, temporary, dirs_exist_ok=True)
            verify(temporary)
            temporary.rename(destination)
        finally:
            if temporary.exists():
                shutil.rmtree(temporary)
    verify(destination)
    _atomic_json(pointer, {"build": name, "build_id": report["build_id"]})
    return {**plan, "toegepast": True}


def evaluate(build, drafts, *, limit=20):
    """Offline heranalyse van bestaande geometrieën; geen nieuwe routeclaims."""
    from . import route_evidence

    if limit < 1:
        raise ValueError("limit moet minstens 1 zijn")
    root = Path(build).expanduser().resolve()
    report = verify(root)
    database = root / "home/regions/vlaanderen/cache/route_sources.sqlite"
    folder = Path(drafts).expanduser()
    if not folder.is_dir():
        raise ValueError(f"draftmap bestaat niet: {folder}")
    rows = []
    for path in sorted(folder.glob("*.json")):
        document = json.loads(path.read_text())
        geometry = document.get("_geometry")
        if not geometry:
            continue
        started = time.monotonic()
        stats = route_evidence.route_stats(geometry, document.get("profile", "quiet"), database=database)
        if not stats["lengte_m"]:
            continue
        rows.append({"draft_id": path.stem, "profile": document.get("profile", "quiet"),
                     "seconds": round(time.monotonic() - started, 3), "routedata": stats})
        if len(rows) >= limit:
            break
    if not rows:
        raise ValueError("geen opgeslagen routegeometrieën gevonden")
    return {"ok": True, "build_id": report["build_id"], "live_router_aanroepen": 0,
            "betekenis": "Heranalyse van bestaande geometrieën; dit meet datadekking, niet de kwaliteit van nieuw geplande routes.",
            "routes": rows}
