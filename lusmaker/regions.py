"""Regiopacks registreren, installeren en migreren."""
from __future__ import annotations

import json
import shutil
import socket
from pathlib import Path

import yaml

from . import config


def parse_bbox(value: str) -> tuple[float, float, float, float]:
    try:
        return config._validate_bbox(value.split(","))
    except ValueError as exc:
        raise ValueError(
            "bbox verwacht minlat,minlon,maxlat,maxlon"
        ) from exc


def _port_available(port: int) -> bool:
    with socket.socket() as sock:
        try:
            sock.bind(("127.0.0.1", port))
        except OSError:
            return False
    return True


def next_port(
    used_ports=(),
    *,
    start: int = 8989,
    available=_port_available,
) -> int:
    used = set(used_ports)
    port = start
    while port in used or not available(port):
        port += 1
    return port


def add(
    slug: str,
    geofabrik: str,
    bbox,
    *,
    home: Path | None = None,
    available=_port_available,
) -> config.Region:
    selected_home = home or config.home_path()
    if config.load_registry(selected_home) is None:
        legacy_data = any(
            (selected_home / name).exists()
            for name in ("data", "cache", "gh", "heat")
        )
        legacy_drafts = any((selected_home / "drafts").glob("*.json"))
        if legacy_data or legacy_drafts:
            raise RuntimeError(
                "legacy-installatie gevonden — draai eerst "
                "`lus region migrate-legacy`"
            )
    used = [region.gh_port for region in config.registered_regions(home)]
    port = next_port(used, available=available)
    return config.register_region(
        slug, geofabrik, bbox, port, home=home
    )


def list_all(*, home: Path | None = None, checker=None) -> dict:
    registry = config.load_registry(home)
    if registry is None:
        return {"default": None, "regions": [], "legacy": True}
    results = []
    for region in config.registered_regions(home):
        data_ok = (
            (region.data / region.pbf_name).exists()
            and all(
                (region.data / f"{tile}.hgt").exists()
                for tile in config.dem_tiles_for_bbox(region.bbox)
            )
            and (region.cache / "extract.pkl").exists()
            and (region.cache / "gazetteer.pkl").exists()
            and (region.cache / "climbs.json").exists()
        )
        if checker is None:
            from . import gh

            try:
                with config.use_region(region.slug):
                    gh.info()
                gh_ok = True
            except Exception:
                gh_ok = False
        else:
            gh_ok = bool(checker(region))
        results.append(
            {
                **region.as_dict(),
                "default": region.slug == registry["default"],
                "data_aanwezig": data_ok,
                "graphhopper_bereikbaar": gh_ok,
            }
        )
    return {"default": registry["default"], "regions": results}


def set_default(slug: str, *, home: Path | None = None) -> dict:
    region = config.set_default_region(slug, home=home)
    return {"default": region.slug}


def write_compose(
    *,
    home: Path | None = None,
    output_path: Path | None = None,
) -> str:
    services = {}
    for region in config.registered_regions(home):
        root = f"${{LUSMAKER_HOME:-~/.lusmaker}}/regions/{region.slug}"
        services[f"graphhopper-{region.slug}"] = {
            "image": config.GRAPH_HOPPER_IMAGE,
            "container_name": f"lusmaker-gh-{region.slug}",
            "command": ["-c", "/lus/gh/config.yml"],
            "environment": {"JAVA_OPTS": "-Xmx6g -Xms1g"},
            "ports": [f"{region.gh_port}:{region.gh_port}"],
            "volumes": [
                f"{root}:/lus",
                f"{root}/gh/graph-cache:/data/default-gh",
            ],
            "restart": "unless-stopped",
        }
    path = output_path or (
        Path(__file__).resolve().parent.parent / "docker-compose.regions.yml"
    )
    path.write_text(
        yaml.safe_dump(
            {"services": services}, sort_keys=False, allow_unicode=True
        ),
        encoding="utf-8",
    )
    return str(path)


def install(slug: str, geofabrik: str, bbox) -> dict:
    """Registreer en bouw een regiopack; de downloads zitten in data.setup."""
    from . import climbs, data, gh_config, osm

    region = add(slug, geofabrik, bbox)
    with config.use_region(region.slug):
        setup_result = data.setup()
        extract = osm.build_extract(force=True)
        osm.build_gazetteer(extract, force=True)
        if region.slug == config.LEGACY_SLUG:
            climbs.resolve_all(extract, force=True)
        else:
            config.ensure_dirs()
            config.CLIMBS_JSON.write_text(
                json.dumps({"climbs": {}, "failed": []}),
                encoding="utf-8",
            )
        detected = climbs.detect_auto(extract)
        gh_files = gh_config.write_gh_files()
    compose = write_compose()
    return {
        "region": region.as_dict(),
        "setup": setup_result,
        "wegen_in_regio": len(extract["ways"]),
        "plaatsen": len(extract["places"]),
        "auto_klimmen": len(detected["auto"]),
        "gh_files": gh_files,
        "compose": compose,
    }


def migrate_legacy(
    *,
    home: Path | None = None,
    compose_path: Path | None = None,
) -> dict:
    home = home or config.home_path()
    if config.load_registry(home) is not None:
        raise RuntimeError("regions.json bestaat al; legacy-migratie is niet nodig")
    target = home / "regions" / config.LEGACY_SLUG
    moves = []
    for name in ("data", "cache", "gh", "heat"):
        source = home / name
        destination = target / name
        if source.exists() and destination.exists():
            raise RuntimeError(f"doel bestaat al: {destination}")
        if source.exists():
            moves.append((source, destination))

    target.mkdir(parents=True, exist_ok=True)
    for source, destination in moves:
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.move(str(source), str(destination))

    config.register_region(
        config.LEGACY_SLUG,
        config.LEGACY_GEOFABRIK,
        config.LEGACY_BBOX,
        8989,
        home=home,
    )
    compose = write_compose(home=home, output_path=compose_path)
    return {
        "region": config.LEGACY_SLUG,
        "verplaatst": [source.name for source, _destination in moves],
        "compose": compose,
    }
