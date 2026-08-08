"""Paden, regioregister en databronnen."""
from __future__ import annotations

import json
import math
import os
import re
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass
from pathlib import Path


LEGACY_SLUG = "vlaanderen"
LEGACY_BBOX = (50.68, 3.35, 51.10, 4.20)
LEGACY_GEOFABRIK = "europe/belgium"
REGISTRY_FILENAME = "regions.json"
REGION_ENV = "LUSMAKER_REGION"

# AWS Terrain Tiles (open data, skadi/SRTM-formaat, geen auth)
DEM_URL = "https://elevation-tiles-prod.s3.amazonaws.com/skadi/{ns}/{name}.hgt.gz"
GH_PROFILE = "quiet"
GRAPH_HOPPER_IMAGE = os.environ.get(
    "LUSMAKER_GH_IMAGE", "israelhikingmap/graphhopper:11.0"
)
CLIMBS_YAML_BUILTIN = Path(__file__).with_name("climbs.yaml")

_active_region: ContextVar[str | None] = ContextVar(
    "lusmaker_active_region", default=None
)
_active_user: ContextVar[str] = ContextVar(
    "lusmaker_active_user", default="local"
)
_SLUG_RE = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")


def home_path() -> Path:
    return Path(os.environ.get("LUSMAKER_HOME", str(Path.home() / ".lusmaker")))


def validate_user_id(uid: str) -> str:
    """Valideer een opaque OAuth-subject voordat het een padcomponent wordt."""
    if (
        not isinstance(uid, str)
        or not uid
        or len(uid) > 256
        or uid in {".", ".."}
        or "/" in uid
        or "\\" in uid
        or any(ord(char) < 32 or ord(char) == 127 for char in uid)
    ):
        raise ValueError("ongeldige user-id voor opslagpad")
    return uid


def current_user_id() -> str:
    return _active_user.get()


def user_home_path(home: Path | None = None) -> Path:
    """Geef de gebruikersroot; ``local`` behoudt de historische HOME-layout."""
    base = home or home_path()
    uid = current_user_id()
    if uid == "local":
        return base
    users_root = base / "users"
    scoped = users_root / validate_user_id(uid)
    if scoped.resolve(strict=False).parent != users_root.resolve(strict=False):
        raise ValueError("user-id wijst buiten de gebruikersmap")
    return scoped


def drafts_path(home: Path | None = None) -> Path:
    return user_home_path(home) / "drafts"


def profiles_path(home: Path | None = None) -> Path:
    return user_home_path(home) / "profiles"


def exports_path(home: Path | None = None) -> Path:
    return user_home_path(home) / "exports"


@contextmanager
def user_scope(uid: str):
    """Scopeer persoonlijke opslag request-lokaal op een gevalideerd subject."""
    token = _active_user.set(validate_user_id(uid))
    try:
        yield current_user_id()
    finally:
        _active_user.reset(token)


@dataclass(frozen=True)
class Region:
    slug: str
    geofabrik: str
    bbox: tuple[float, float, float, float]
    gh_port: int
    home: Path
    legacy: bool = False

    @property
    def root(self) -> Path:
        return self.home if self.legacy else self.home / "regions" / self.slug

    @property
    def data(self) -> Path:
        return self.root / "data"

    @property
    def cache(self) -> Path:
        return self.root / "cache"

    @property
    def gh_dir(self) -> Path:
        return self.root / "gh"

    @property
    def heat_dir(self) -> Path:
        return self.root / "heat"

    @property
    def pbf_name(self) -> str:
        return f"{self.geofabrik.rsplit('/', 1)[-1]}-latest.osm.pbf"

    @property
    def pbf_url(self) -> str:
        return f"https://download.geofabrik.de/{self.geofabrik}-latest.osm.pbf"

    @property
    def gh_url(self) -> str:
        override = os.environ.get("LUSMAKER_GH_URL")
        return override or f"http://localhost:{self.gh_port}"

    def as_dict(self) -> dict:
        return {
            "slug": self.slug,
            "geofabrik": self.geofabrik,
            "bbox": list(self.bbox),
            "gh_port": self.gh_port,
        }


def registry_path(home: Path | None = None) -> Path:
    return (home or home_path()) / REGISTRY_FILENAME


def load_registry(home: Path | None = None) -> dict | None:
    path = registry_path(home)
    if not path.exists():
        return None
    with open(path, encoding="utf-8") as handle:
        data = json.load(handle)
    if not isinstance(data, dict) or not isinstance(data.get("regions"), dict):
        raise RuntimeError(f"ongeldig regioregister: {path}")
    return data


def _write_registry(registry: dict, home: Path | None = None) -> None:
    path = registry_path(home)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".json.tmp")
    tmp.write_text(
        json.dumps(registry, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    tmp.replace(path)


def _validate_bbox(bbox) -> tuple[float, float, float, float]:
    try:
        values = tuple(float(value) for value in bbox)
    except (TypeError, ValueError) as exc:
        raise ValueError("bbox moet vier getallen bevatten") from exc
    if len(values) != 4:
        raise ValueError("bbox moet vier getallen bevatten")
    minlat, minlon, maxlat, maxlon = values
    if not (-90 <= minlat < maxlat <= 90 and -180 <= minlon < maxlon <= 180):
        raise ValueError("ongeldige bbox-volgorde of coördinaten")
    return values


def dem_tiles_for_bbox(bbox) -> list[str]:
    """Alle Skadi-tegels die een bbox raakt, deterministisch gesorteerd."""
    minlat, minlon, maxlat, maxlon = _validate_bbox(bbox)
    tiles = []
    for lat in range(math.floor(minlat), math.floor(maxlat) + 1):
        for lon in range(math.floor(minlon), math.floor(maxlon) + 1):
            ns = "N" if lat >= 0 else "S"
            ew = "E" if lon >= 0 else "W"
            tiles.append(f"{ns}{abs(lat):02d}{ew}{abs(lon):03d}")
    return tiles


def _region_from_record(record: dict, home: Path) -> Region:
    return Region(
        slug=record["slug"],
        geofabrik=record["geofabrik"],
        bbox=_validate_bbox(record["bbox"]),
        gh_port=int(record["gh_port"]),
        home=home,
    )


def get_region(slug: str | None = None, home: Path | None = None) -> Region:
    home = home or home_path()
    registry = load_registry(home)
    requested = (
        slug
        or _active_region.get()
        or os.environ.get(REGION_ENV)
        or (registry or {}).get("default")
    )
    if registry is None:
        if requested not in (None, LEGACY_SLUG):
            raise RuntimeError(
                f"onbekende regio '{requested}' — er is nog geen regioregister"
            )
        return Region(
            LEGACY_SLUG,
            LEGACY_GEOFABRIK,
            LEGACY_BBOX,
            8989,
            home,
            legacy=True,
        )
    requested = requested or registry.get("default")
    record = registry["regions"].get(requested)
    if record is None:
        raise RuntimeError(f"onbekende regio '{requested}' — zie `lus region list`")
    return _region_from_record(record, home)


def current_region() -> Region:
    return get_region()


@contextmanager
def use_region(slug: str | None):
    """Activeer een regio alleen binnen de huidige CLI- of MCP-aanroep."""
    region = get_region(slug)
    token = _active_region.set(region.slug)
    try:
        yield region
    finally:
        _active_region.reset(token)


def register_region(
    slug: str,
    geofabrik: str,
    bbox,
    gh_port: int,
    *,
    home: Path | None = None,
) -> Region:
    home = home or home_path()
    if not _SLUG_RE.fullmatch(slug):
        raise ValueError("regioslug gebruikt alleen kleine letters, cijfers en streepjes")
    geofabrik = geofabrik.strip("/")
    if not geofabrik or geofabrik.endswith(".osm.pbf"):
        raise ValueError("geofabrik is een pad zoals 'europe/netherlands/zeeland'")
    bbox = _validate_bbox(bbox)
    registry = load_registry(home) or {"default": slug, "regions": {}}
    if slug in registry["regions"]:
        raise RuntimeError(f"regio '{slug}' bestaat al")
    record = {
        "slug": slug,
        "geofabrik": geofabrik,
        "bbox": list(bbox),
        "gh_port": int(gh_port),
    }
    registry["regions"][slug] = record
    registry.setdefault("default", slug)
    _write_registry(registry, home)
    return _region_from_record(record, home)


def set_default_region(slug: str, *, home: Path | None = None) -> Region:
    home = home or home_path()
    registry = load_registry(home)
    if registry is None or slug not in registry["regions"]:
        raise RuntimeError(f"onbekende regio '{slug}' — zie `lus region list`")
    registry["default"] = slug
    _write_registry(registry, home)
    return _region_from_record(registry["regions"][slug], home)


def registered_regions(home: Path | None = None) -> list[Region]:
    home = home or home_path()
    registry = load_registry(home)
    if registry is None:
        return []
    return [
        _region_from_record(record, home)
        for _slug, record in sorted(registry["regions"].items())
    ]


def climbs_yaml_path() -> Path:
    user = home_path() / "climbs.yaml"
    return user if user.exists() else CLIMBS_YAML_BUILTIN


def ensure_dirs() -> None:
    region = current_region()
    for path in (
        region.data,
        region.cache,
        drafts_path(),
        region.gh_dir,
        region.gh_dir / "custom_models",
        region.heat_dir,
        region.gh_dir / "custom_areas",
    ):
        path.mkdir(parents=True, exist_ok=True)


def status(region: str | None = None) -> dict:
    """Geef de beschikbaarheid van lokale data en GraphHopper terug."""
    with use_region(region) as selected:
        out = {
            "data": {
                "pbf": selected.data.joinpath(selected.pbf_name).exists(),
                "dem_tiles": all(
                    selected.data.joinpath(f"{tile}.hgt").exists()
                    for tile in dem_tiles_for_bbox(selected.bbox)
                ),
                "extract": selected.cache.joinpath("extract.pkl").exists(),
                "gazetteer": selected.cache.joinpath("gazetteer.pkl").exists(),
                "climbs": selected.cache.joinpath("climbs.json").exists(),
            },
        }
        registry = load_registry()
        if registry is not None:
            out["region"] = selected.slug
            out["regions"] = {
                "default": registry["default"],
                "beschikbaar": sorted(registry["regions"]),
            }
        try:
            from . import gh

            info = gh.info()
            out["graphhopper"] = {
                "ok": True,
                "version": info.get("version"),
                "profiles": [
                    profile.get("name") for profile in info.get("profiles", [])
                ],
                "elevation": info.get("elevation"),
            }
        except Exception as exc:
            out["graphhopper"] = {"ok": False, "error": str(exc)}
        return out


_REGION_ATTRS = {
    "DATA": lambda region: region.data,
    "CACHE": lambda region: region.cache,
    "GH_DIR": lambda region: region.gh_dir,
    "BBOX": lambda region: region.bbox,
    "PBF_URL": lambda region: region.pbf_url,
    "PBF_PATH": lambda region: region.data / region.pbf_name,
    "DEM_TILES": lambda region: dem_tiles_for_bbox(region.bbox),
    "HEAT_DIR": lambda region: region.heat_dir,
    "HEAT_PKL": lambda region: region.cache / "heat.pkl",
    "OSM_TRACES_PKL": lambda region: region.cache / "osm_traces.pkl",
    "VLAANDEREN_ROUTES_PKL": (
        lambda region: region.cache / "vlaanderen_routes.pkl"
    ),
    "CUSTOM_AREAS": lambda region: region.gh_dir / "custom_areas",
    "EXTRACT_PKL": lambda region: region.cache / "extract.pkl",
    "GAZETTEER_PKL": lambda region: region.cache / "gazetteer.pkl",
    "CLIMBS_JSON": lambda region: region.cache / "climbs.json",
    "GH_URL": lambda region: region.gh_url,
}


def __getattr__(name: str):
    if name == "HOME":
        return home_path()
    if name == "DRAFTS":
        return drafts_path()
    if name == "CLIMBS_YAML_USER":
        return home_path() / "climbs.yaml"
    try:
        return _REGION_ATTRS[name](current_region())
    except KeyError as exc:
        raise AttributeError(name) from exc
