"""Pak een gevalideerd Lusmaker-regiopack uit in de Docker buildcontext."""

from __future__ import annotations

import argparse
import json
import os
import re
from pathlib import Path

import yaml

from lusmaker.provision import _unpack

REQUIRED_BASE_MODEL_VALUES = {"country"}


def _validate_graph_compatibility(region_root: Path) -> None:
    config_path = region_root / "gh" / "config.yml"
    properties_path = region_root / "gh" / "graph-cache" / "properties"
    try:
        document = yaml.safe_load(config_path.read_text(encoding="utf-8"))
        graphhopper = document["graphhopper"]
        encoded_values = graphhopper["graph.encoded_values"]
    except (KeyError, TypeError, yaml.YAMLError) as exc:
        raise RuntimeError("regiopack bevat geen geldige GraphHopper-config") from exc
    if not isinstance(encoded_values, str):
        raise RuntimeError("graph.encoded_values moet een kommagescheiden string zijn")
    configured = {
        value.strip() for value in encoded_values.split(",") if value.strip()
    }
    missing_from_config = sorted(REQUIRED_BASE_MODEL_VALUES - configured)
    if missing_from_config:
        raise RuntimeError(
            "GraphHopper config.yml mist encoded values voor de basismodellen: "
            + ", ".join(missing_from_config)
        )
    stored = {
        value.decode("ascii")
        for value in re.findall(
            rb'\\"name\\":\\"([a-z0-9_]+)\\"', properties_path.read_bytes()
        )
    }
    missing = sorted((configured | REQUIRED_BASE_MODEL_VALUES) - stored)
    if missing:
        raise RuntimeError(
            "GraphHopper graph-cache mist encoded values uit config.yml: "
            + ", ".join(missing)
        )


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
        region_root / "gh" / "graph-cache" / "properties",
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
    _validate_graph_compatibility(region_root)
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
