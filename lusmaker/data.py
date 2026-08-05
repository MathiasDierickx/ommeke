"""Eenmalige downloads: Geofabrik-extract + DEM-tegels."""
import gzip
import sys
import urllib.request

from . import config


def _download(url: str, dest, label: str) -> None:
    if dest.exists() and dest.stat().st_size > 0:
        print(f"[setup] {label}: al aanwezig ({dest.stat().st_size // 1_000_000} MB)", file=sys.stderr)
        return
    print(f"[setup] download {label} ...", file=sys.stderr)
    tmp = dest.with_suffix(dest.suffix + ".part")
    req = urllib.request.Request(url, headers={"User-Agent": "lusmaker/0.1"})
    with urllib.request.urlopen(req) as resp, open(tmp, "wb") as f:
        total = int(resp.headers.get("Content-Length") or 0)
        done = 0
        next_pct = 10
        while True:
            chunk = resp.read(1 << 20)
            if not chunk:
                break
            f.write(chunk)
            done += len(chunk)
            if total and done * 100 // total >= next_pct:
                print(f"[setup]   {label}: {done * 100 // total}%", file=sys.stderr)
                next_pct += 10
    tmp.rename(dest)
    print(f"[setup] {label}: klaar ({done // 1_000_000} MB)", file=sys.stderr)


def setup() -> dict:
    config.ensure_dirs()
    _download(config.PBF_URL, config.PBF_PATH, "belgium-latest.osm.pbf")
    for name in config.DEM_TILES:
        url = config.DEM_URL.format(ns=name[:3], name=name)
        gz = config.DATA / f"{name}.hgt.gz"
        hgt = config.DATA / f"{name}.hgt"
        if not hgt.exists():
            _download(url, gz, f"DEM {name}")
            hgt.write_bytes(gzip.decompress(gz.read_bytes()))
            gz.unlink()
    return {
        "ok": True,
        "pbf": str(config.PBF_PATH),
        "dem_tiles": [str(config.DATA / f"{n}.hgt") for n in config.DEM_TILES],
    }
