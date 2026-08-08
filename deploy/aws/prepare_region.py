"""Pak een gevalideerd Lusmaker-regiopack uit in de Docker buildcontext."""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path

from lusmaker.provision import _unpack


def prepare(pack: Path, slug: str, destination: Path) -> dict:
    region_root = destination / "regions" / slug
    manifest = _unpack(pack, region_root, slug)
    expected_image = os.environ.get(
        "LUSMAKER_GH_IMAGE", "israelhikingmap/graphhopper:11.0"
    )
    if manifest.get("gh_image") != expected_image:
        raise RuntimeError(
            "regiopack gebruikt GraphHopper "
            f"{manifest.get('gh_image')!r}; verwacht {expected_image!r}"
        )
    required = [
        region_root / "cache",
        region_root / "gh" / "config.yml",
        region_root / "gh" / "graph-cache",
        region_root / "gh" / "custom_models",
    ]
    missing = [
        str(path.relative_to(destination)) for path in required if not path.exists()
    ]
    if missing:
        raise RuntimeError(
            "regiopack mist vereiste Lambda-data: " + ", ".join(missing)
        )
    if not any((region_root / "gh" / "graph-cache").iterdir()):
        raise RuntimeError("GraphHopper graph-cache in het regiopack is leeg")
    registry = {
        "default": slug,
        "regions": {
            slug: {
                "slug": slug,
                "geofabrik": manifest["geofabrik"],
                "bbox": manifest["bbox"],
                "gh_port": 8989,
            }
        },
    }
    destination.mkdir(parents=True, exist_ok=True)
    (destination / "regions.json").write_text(
        json.dumps(registry, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    return {
        "slug": slug,
        "destination": str(destination),
        "region_root": str(region_root),
        "manifest": manifest,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("pack", type=Path)
    parser.add_argument("slug")
    parser.add_argument("destination", type=Path)
    args = parser.parse_args()
    result = prepare(args.pack, args.slug, args.destination)
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
