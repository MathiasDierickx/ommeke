#!/usr/bin/env python3
"""Haal de Vlaanderen-grens eenmalig op en sla ze vereenvoudigd op.

Bron: OpenStreetMap relatie 53134 (admin_level 4, "Vlaanderen") via Nominatim.
(c) OpenStreetMap-bijdragers, ODbL 1.0; vermeld die attributie bij gebruik.
Resultaat: lusmaker/data/flanders_boundary.geojson (inchecken). Draai dit enkel
bij een bewuste grensupdate; de tests en de pack-build doen zelf geen netwerk.

    .venv/bin/python scripts/flanders_boundary.py [--tolerance 0.005]
"""
import argparse
import json
import sys
import urllib.request
from pathlib import Path

root = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(root))

from lusmaker import boundary, config  # noqa: E402

URL = (
    "https://nominatim.openstreetmap.org/lookup?osm_ids=R53134"
    "&format=geojson&polygon_geojson=1&polygon_threshold=0.001"
)


def main(argv=None) -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--tolerance", type=float, default=0.005,
                        help="Douglas-Peucker-tolerantie in graden (~500 m)")
    parser.add_argument("--output", type=Path, default=boundary.BOUNDARY_PATH)
    args = parser.parse_args(argv)
    request = urllib.request.Request(URL, headers={"User-Agent": config.USER_AGENT})
    with urllib.request.urlopen(request, timeout=60) as response:
        raw = json.load(response)
    simple = boundary.simplify_geojson(raw, args.tolerance)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(simple, separators=(",", ":")), encoding="utf-8")
    print(json.dumps({"output": str(args.output),
                      "bbox": boundary.buffered_bbox(simple)}, indent=2))


if __name__ == "__main__":
    main()
