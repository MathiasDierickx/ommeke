"""Paden, regio-bbox en databronnen."""
import os
from pathlib import Path

HOME = Path(os.environ.get("LUSMAKER_HOME", str(Path.home() / ".lusmaker")))
DATA = HOME / "data"
CACHE = HOME / "cache"
DRAFTS = HOME / "drafts"
GH_DIR = HOME / "gh"

# Regio: Wetteren + Vlaamse Ardennen (minlat, minlon, maxlat, maxlon)
BBOX = (50.68, 3.35, 51.10, 4.20)

PBF_URL = "https://download.geofabrik.de/europe/belgium-latest.osm.pbf"
PBF_PATH = DATA / "belgium-latest.osm.pbf"

# AWS Terrain Tiles (open data, skadi/SRTM-formaat, geen auth) — voor klimprofielen
DEM_URL = "https://elevation-tiles-prod.s3.amazonaws.com/skadi/{ns}/{name}.hgt.gz"
DEM_TILES = ["N50E003", "N50E004", "N51E003", "N51E004"]

HEAT_DIR = HOME / "heat"          # drop hier je eigen GPX-ritten
HEAT_PKL = CACHE / "heat.pkl"
CUSTOM_AREAS = GH_DIR / "custom_areas"

EXTRACT_PKL = CACHE / "extract.pkl"
GAZETTEER_PKL = CACHE / "gazetteer.pkl"
CLIMBS_JSON = CACHE / "climbs.json"

# GraphHopper (docker compose, zie repo-root)
GH_URL = os.environ.get("LUSMAKER_GH_URL", "http://localhost:8989")
GH_PROFILE = "quiet"

# climbs.yaml: override in HOME wint van de meegeleverde lijst
CLIMBS_YAML_BUILTIN = Path(__file__).with_name("climbs.yaml")
CLIMBS_YAML_USER = HOME / "climbs.yaml"


def climbs_yaml_path() -> Path:
    return CLIMBS_YAML_USER if CLIMBS_YAML_USER.exists() else CLIMBS_YAML_BUILTIN


def ensure_dirs() -> None:
    for p in (DATA, CACHE, DRAFTS, GH_DIR, GH_DIR / "custom_models", HEAT_DIR, CUSTOM_AREAS):
        p.mkdir(parents=True, exist_ok=True)
