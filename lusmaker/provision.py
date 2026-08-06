"""Ad-hoc regioprovisioning, voortgang en herbruikbare regiopacks."""
from __future__ import annotations

import argparse
import io
import json
import os
import shutil
import subprocess
import sys
import tarfile
import tempfile
import time
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable
from urllib.parse import urlparse

from . import __version__, config
from .discover import geofabrik_path_from_url


GH_IMAGE = "israelhikingmap/graphhopper:latest"
PHASES = ("downloaden", "bouwen", "gh-import", "klaar")


def provision_path(slug: str, *, home: Path | None = None) -> Path:
    return (home or config.home_path()) / "regions" / slug / "provision.json"


def write_provision_state(
    slug: str,
    phase: str,
    progress: int,
    *,
    home: Path | None = None,
    state: str = "bezig",
    message: str | None = None,
    warnings: list[str] | None = None,
) -> dict:
    """Atomically persist pollable provisioning progress."""
    if phase not in PHASES:
        raise ValueError(f"onbekende provisioningsfase: {phase}")
    if not 0 <= int(progress) <= 100:
        raise ValueError("voortgang moet tussen 0 en 100 liggen")
    value = {
        "slug": slug,
        "fase": phase,
        "voortgang": int(progress),
        "status": state,
        "bijgewerkt": datetime.now(timezone.utc).isoformat(),
    }
    if message:
        value["melding"] = message
    if warnings:
        value["waarschuwingen"] = list(warnings)
    path = provision_path(slug, home=home)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(".json.tmp")
    temporary.write_text(
        json.dumps(value, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    temporary.replace(path)
    return value


def read_provision_state(slug: str, *, home: Path | None = None) -> dict:
    path = provision_path(slug, home=home)
    if not path.exists():
        raise RuntimeError(f"geen provisioning gevonden voor regio '{slug}'")
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"ongeldige provisioningstatus voor regio '{slug}'") from exc
    if (
        not isinstance(value, dict)
        or value.get("slug") != slug
        or value.get("fase") not in PHASES
    ):
        raise RuntimeError(f"ongeldige provisioningstatus voor regio '{slug}'")
    return value


def region_status(slug: str, *, home: Path | None = None) -> dict:
    """Return provisioning state, or a stable ready state for older regions."""
    path = provision_path(slug, home=home)
    if path.exists():
        return read_provision_state(slug, home=home)
    try:
        region = config.get_region(slug, home=home)
    except RuntimeError:
        raise RuntimeError(f"onbekende regio '{slug}'") from None
    return {
        "slug": region.slug,
        "fase": "klaar",
        "voortgang": 100,
        "status": "klaar",
        "melding": "regio is geregistreerd",
    }


def escape_slug(slug: str) -> str:
    return slug.strip("/").replace("/", "__")


def pack_location(base: str | Path, slug: str) -> str:
    """Build ``<base>/<escaped-slug>.tar.gz`` for URLs, S3 and paths."""
    filename = f"{escape_slug(slug)}.tar.gz"
    value = str(base)
    if "://" in value:
        return f"{value.rstrip('/')}/{filename}"
    return str(Path(value) / filename)


def _tar_add_path(archive: tarfile.TarFile, source: Path, arcname: str) -> None:
    if source.exists():
        archive.add(source, arcname=arcname, recursive=True)


def create_pack(
    slug: str,
    output: str | Path | None = None,
    *,
    home: Path | None = None,
) -> dict:
    """Create a rebuildable pack without the large source PBF."""
    region = config.get_region(slug, home=home)
    destination = Path(output or f"{escape_slug(slug)}.tar.gz")
    destination.parent.mkdir(parents=True, exist_ok=True)
    manifest = {
        "slug": region.slug,
        "bbox": list(region.bbox),
        "geofabrik": region.geofabrik,
        "lusmaker_version": __version__,
        "gh_image": GH_IMAGE,
    }
    with tarfile.open(destination, "w:gz") as archive:
        _tar_add_path(archive, region.cache, "cache")
        for tile in sorted(region.data.glob("*.hgt")):
            archive.add(tile, arcname=f"data/{tile.name}")
        _tar_add_path(archive, region.gh_dir / "graph-cache", "gh/graph-cache")
        _tar_add_path(archive, region.gh_dir / "config.yml", "gh/config.yml")
        _tar_add_path(
            archive, region.gh_dir / "custom_models", "gh/custom_models"
        )
        payload = (
            json.dumps(manifest, ensure_ascii=False, indent=2) + "\n"
        ).encode("utf-8")
        info = tarfile.TarInfo("pack.json")
        info.size = len(payload)
        info.mtime = int(time.time())
        archive.addfile(info, io.BytesIO(payload))
    return {
        "slug": slug,
        "pack": str(destination),
        "bytes": destination.stat().st_size,
        "manifest": manifest,
    }


def _safe_members(archive: tarfile.TarFile):
    for member in archive.getmembers():
        path = Path(member.name)
        if path.is_absolute() or ".." in path.parts or member.issym() or member.islnk():
            raise RuntimeError(f"onveilig pad in regiopack: {member.name}")
        yield member


def _unpack(pack: Path, target: Path, expected_slug: str) -> dict:
    target.mkdir(parents=True, exist_ok=True)
    with tarfile.open(pack, "r:gz") as archive:
        try:
            manifest_file = archive.extractfile("pack.json")
        except KeyError as exc:
            raise RuntimeError("regiopack mist pack.json") from exc
        if manifest_file is None:
            raise RuntimeError("regiopack mist pack.json")
        manifest = json.load(manifest_file)
        if manifest.get("slug") != expected_slug:
            raise RuntimeError(
                f"regiopack is voor '{manifest.get('slug')}', niet '{expected_slug}'"
            )
        archive.extractall(target, members=_safe_members(archive))
    return manifest


def _download_file(url: str, destination: Path) -> None:
    request = urllib.request.Request(url, headers={"User-Agent": "lusmaker/0.1"})
    with urllib.request.urlopen(request, timeout=120) as response, open(
        destination, "wb"
    ) as output:
        shutil.copyfileobj(response, output)


def _copy_pack_source(
    source: str,
    destination: Path,
    *,
    fetch_file: Callable[[str, Path], None],
    exec_func: Callable = subprocess.run,
) -> None:
    if source.startswith(("http://", "https://")):
        fetch_file(source, destination)
    elif source.startswith("s3://"):
        exec_func(["aws", "s3", "cp", source, str(destination)], check=True)
    else:
        shutil.copyfile(source, destination)


def restore_cached_pack(
    slug: str,
    target: Path,
    *,
    cache_bases: str | None = None,
    fetch_file: Callable[[str, Path], None] = _download_file,
    exec_func: Callable = subprocess.run,
) -> dict | None:
    """Try cache bases in order. Missing/unreachable entries are cache misses."""
    configured = (
        cache_bases
        if cache_bases is not None
        else os.environ.get("LUSMAKER_PACK_CACHE", "")
    )
    bases = [item.strip() for item in configured.split(",") if item.strip()]
    if not bases:
        return None
    with tempfile.TemporaryDirectory(prefix="lusmaker-pack-") as temporary:
        pack = Path(temporary) / f"{escape_slug(slug)}.tar.gz"
        for base in bases:
            source = pack_location(base, slug)
            try:
                _copy_pack_source(
                    source, pack, fetch_file=fetch_file, exec_func=exec_func
                )
                manifest = _unpack(pack, target, slug)
                return {"bron": source, "manifest": manifest}
            except (
                OSError,
                RuntimeError,
                ValueError,
                tarfile.TarError,
                subprocess.SubprocessError,
            ):
                if pack.exists():
                    pack.unlink()
    return None


def _registered(slug: str, home: Path) -> config.Region | None:
    registry = config.load_registry(home)
    if registry is None or slug not in registry["regions"]:
        return None
    return config.get_region(slug, home=home)


def _default_build(region: config.Region, pbf_url: str) -> dict:
    from . import climbs, data, gh_config, osm

    with config.use_region(region.slug):
        setup_result = data.setup(pbf_url=pbf_url)
        extract = osm.build_extract(force=True)
        osm.build_gazetteer(extract, force=True)
        config.ensure_dirs()
        config.CLIMBS_JSON.write_text(
            json.dumps({"climbs": {}, "failed": []}), encoding="utf-8"
        )
        detected = climbs.detect_auto(extract)
        gh_files = gh_config.write_gh_files()
    return {
        "setup": setup_result,
        "wegen_in_regio": len(extract["ways"]),
        "plaatsen": len(extract["places"]),
        "auto_klimmen": len(detected["auto"]),
        "gh_files": gh_files,
    }


def _wait_for_health(
    url: str,
    *,
    health_check: Callable[[str], bool] | None = None,
    timeout: float = 20 * 60,
    interval: float = 5,
    clock: Callable[[], float] = time.monotonic,
    sleep: Callable[[float], None] = time.sleep,
) -> None:
    if health_check is None:
        def health_check(candidate: str) -> bool:
            try:
                with urllib.request.urlopen(candidate, timeout=5) as response:
                    return 200 <= response.status < 300
            except OSError:
                return False

    deadline = clock() + timeout
    while clock() < deadline:
        if health_check(url):
            return
        sleep(interval)
    raise RuntimeError("GraphHopper werd niet gezond binnen 20 minuten")


def _upload_pack(
    pack: Path,
    destination_base: str,
    slug: str,
    *,
    exec_func: Callable = subprocess.run,
) -> str:
    destination = pack_location(destination_base, slug)
    if destination.startswith("s3://"):
        exec_func(["aws", "s3", "cp", str(pack), destination], check=True)
    else:
        target = Path(destination)
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(pack, target)
    return destination


def provision(
    slug: str,
    pbf_url: str,
    bbox,
    background: bool = True,
    *,
    home: Path | None = None,
    popen: Callable = subprocess.Popen,
    exec_func: Callable = subprocess.run,
    fetch_file: Callable[[str, Path], None] = _download_file,
    build_func: Callable[[config.Region, str], dict] = _default_build,
    health_check: Callable[[str], bool] | None = None,
    compose_path: Path | None = None,
    port_available: Callable[[int], bool] | None = None,
) -> dict:
    """Provision a region in a child process, or synchronously for the worker."""
    from . import regions

    home = home or config.home_path()
    existing = _registered(slug, home)
    if existing is not None:
        try:
            status = region_status(slug, home=home)
        except RuntimeError:
            status = None
        # alleen kortsluiten als de vorige provisioning niet mislukt is;
        # een 'fout'-status (bv. transiente 502 upstream) mag opnieuw
        if status is not None and status.get("status") != "fout":
            return {
                "region": existing.as_dict(),
                "bestaand": True,
                "provisioning": status,
            }

    bbox = config._validate_bbox(bbox)
    if background:
        state = write_provision_state(
            slug,
            "downloaden",
            0,
            home=home,
            message="provisioning wordt gestart",
        )
        command = [
            sys.executable,
            "-m",
            "lusmaker.provision",
            slug,
            "--pbf-url",
            pbf_url,
            "--bbox",
            ",".join(str(value) for value in bbox),
        ]
        try:
            popen(command, start_new_session=True)
        except Exception as exc:
            write_provision_state(
                slug,
                "downloaden",
                0,
                home=home,
                state="fout",
                message=f"achtergrondproces kon niet starten: {exc}",
            )
            raise
        return {
            "slug": slug,
            "gestart": True,
            "achtergrond": True,
            "provisioning": state,
        }

    warnings = []
    try:
        write_provision_state(slug, "downloaden", 5, home=home)
        target = home / "regions" / slug
        cached = restore_cached_pack(
            slug,
            target,
            fetch_file=fetch_file,
            exec_func=exec_func,
        )
        geofabrik = geofabrik_path_from_url(pbf_url)
        if existing is not None:
            # herprovisioning: registratie (incl. poort) hergebruiken
            region = existing
        else:
            add_kwargs = {"home": home}
            if port_available is not None:
                add_kwargs["available"] = port_available
            region = regions.add(slug, geofabrik, bbox, **add_kwargs)
        if cached is None:
            write_provision_state(slug, "bouwen", 30, home=home)
            build_result = build_func(region, pbf_url)
        else:
            manifest = cached["manifest"]
            if (
                tuple(float(value) for value in manifest.get("bbox", [])) != bbox
                or manifest.get("geofabrik") != geofabrik
            ):
                raise RuntimeError("regiopack-metadata komt niet overeen met de regio")
            from . import gh_config

            with config.use_region(region.slug):
                gh_config.write_gh_files()
            build_result = {"pack_cache": cached["bron"]}

        write_provision_state(slug, "gh-import", 80, home=home)
        compose = regions.write_compose(home=home, output_path=compose_path)
        exec_func(
            [
                "docker",
                "compose",
                "-f",
                compose,
                "up",
                "-d",
                f"graphhopper-{slug}",
            ],
            check=True,
        )
        _wait_for_health(
            f"{region.gh_url}/health", health_check=health_check
        )

        upload = os.environ.get("LUSMAKER_PACK_UPLOAD")
        uploaded_to = None
        if cached is None and upload:
            try:
                with tempfile.TemporaryDirectory(
                    prefix="lusmaker-pack-upload-"
                ) as temporary:
                    packed = create_pack(
                        slug,
                        Path(temporary) / f"{escape_slug(slug)}.tar.gz",
                        home=home,
                    )
                    uploaded_to = _upload_pack(
                        Path(packed["pack"]),
                        upload,
                        slug,
                        exec_func=exec_func,
                    )
            except (OSError, RuntimeError, subprocess.SubprocessError) as exc:
                warnings.append(f"pack-upload mislukt: {exc}")

        state = write_provision_state(
            slug,
            "klaar",
            100,
            home=home,
            state="klaar",
            message="regio is klaar voor gebruik",
            warnings=warnings,
        )
        return {
            "region": region.as_dict(),
            "build": build_result,
            "compose": compose,
            "pack_upload": uploaded_to,
            "provisioning": state,
        }
    except Exception as exc:
        current = provision_path(slug, home=home)
        phase = "downloaden"
        progress = 0
        if current.exists():
            try:
                previous = read_provision_state(slug, home=home)
                phase = previous["fase"]
                progress = previous["voortgang"]
            except RuntimeError:
                pass
        write_provision_state(
            slug,
            phase,
            progress,
            home=home,
            state="fout",
            message=str(exc),
        )
        raise


def ensure_region(
    place: str,
    *,
    background: bool = True,
    home: Path | None = None,
    discover_func: Callable[[str], dict] | None = None,
    **provision_kwargs,
) -> dict:
    """Ensure an exact registered slug or discover a region for a place."""
    home = home or config.home_path()
    existing = _registered(place, home)
    if existing is not None:
        status = region_status(existing.slug, home=home)
        if status.get("status") == "fout":
            # eerdere poging mislukt (bv. transiente 502 upstream): herstart
            pbf_url = f"https://download.geofabrik.de/{existing.geofabrik}-latest.osm.pbf"
            result = provision(
                existing.slug, pbf_url, list(existing.bbox),
                background=background, home=home, **provision_kwargs,
            )
            result["herstart"] = True
            return result
        return {
            "region": existing.as_dict(),
            "bestaand": True,
            "provisioning": status,
        }
    if discover_func is None:
        from .discover import region_for_query

        discovered = region_for_query(place, home=home)
    else:
        discovered = discover_func(place)
    result = provision(
        discovered["slug"],
        discovered["pbf_url"],
        discovered["bbox"],
        background=background,
        home=home,
        **provision_kwargs,
    )
    if "place" in discovered:
        result["plaats"] = discovered["place"]
    return result


def _main(argv=None) -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("slug")
    parser.add_argument("--pbf-url", required=True)
    parser.add_argument("--bbox", required=True)
    args = parser.parse_args(argv)
    bbox = config._validate_bbox(args.bbox.split(","))
    try:
        result = provision(
            args.slug, args.pbf_url, bbox, background=False
        )
        print(json.dumps(result, ensure_ascii=False, indent=2))
    except Exception as exc:
        print(json.dumps({"error": str(exc)}, ensure_ascii=False, indent=2))
        raise SystemExit(1)


if __name__ == "__main__":
    _main()
