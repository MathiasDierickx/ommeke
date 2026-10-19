"""Controleer een gedownloade GPX of FIT uit de webapp: lengte, punten, aanwijzingen, sluiting.

    .venv/bin/python scripts/inspect_download.py ~/Downloads/*.gpx ~/Downloads/*.fit

Output is JSON per bestand; een onleesbaar bestand geeft {"error": ...} en exitcode 1.
"""
import json
import sys
import xml.etree.ElementTree as ET
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from lusmaker import geo  # noqa: E402
from lusmaker.fit_course import decode  # noqa: E402

GPX_NS = "{http://www.topografix.com/GPX/1/1}"
FIT_SPORT = {2: "cycling", 11: "walking"}


def inspect_gpx(data: bytes) -> dict:
    root = ET.fromstring(data)
    points = [(float(p.get("lat")), float(p.get("lon"))) for p in root.iter(GPX_NS + "trkpt")]
    if len(points) < 2:
        raise ValueError("GPX bevat geen track")
    return {
        "formaat": "gpx",
        "naam": (root.findtext(f"{GPX_NS}metadata/{GPX_NS}name") or "").strip(),
        "trackpunten": len(points),
        "lengte_m": round(geo.path_length(points), 1),
        "sluiting_m": round(geo.haversine(*points[0], *points[-1]), 1),
        "aanwijzingen": len(list(root.iter(GPX_NS + "rtept"))),
        "waypoints": len(list(root.iter(GPX_NS + "wpt"))),
    }


def inspect_fit(data: bytes) -> dict:
    records = decode(data)  # controleert header- en bestands-CRC
    course = next(r for n, r in records if n == 31)
    lap = next(r for n, r in records if n == 19)
    points = [r for n, r in records if n == 20]
    semi = lambda v: v * 180 / 2**31  # noqa: E731
    first, last = (semi(points[0][0]), semi(points[0][1])), (semi(points[-1][0]), semi(points[-1][1]))
    return {
        "formaat": "fit",
        "naam": course.get(5, ""),
        "sport": FIT_SPORT.get(course.get(4), course.get(4)),
        "trackpunten": len(points),
        "lengte_m": round(lap[9] / 100, 1),
        "sluiting_m": round(geo.haversine(*first, *last), 1),
        "aanwijzingen": sum(1 for n, _ in records if n == 32),
        "crc_ok": True,
    }


def inspect(path: Path) -> dict:
    data = path.read_bytes()
    result = inspect_fit(data) if data[8:12] == b".FIT" else inspect_gpx(data)
    return {"bestand": str(path), **result}


def main(argv: list[str]) -> int:
    if not argv:
        print(json.dumps({"error": "geef minstens één .gpx of .fit"}, ensure_ascii=False))
        return 1
    code = 0
    for arg in argv:
        try:
            print(json.dumps(inspect(Path(arg).expanduser()), ensure_ascii=False, indent=2))
        except Exception as exc:  # noqa: BLE001 - rapporteer per bestand
            print(json.dumps({"bestand": arg, "error": str(exc)}, ensure_ascii=False, indent=2))
            code = 1
    return code


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
