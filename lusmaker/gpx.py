"""GPX-export van een gerouteerde draft."""
from xml.sax.saxutils import escape


def export(d: dict, climb_db: dict, path: str) -> dict:
    if not d.get("_geometry"):
        raise RuntimeError("routeer eerst: `lus draft route <id>`")

    lines = [
        '<?xml version="1.0" encoding="UTF-8"?>',
        '<gpx version="1.1" creator="lusmaker" xmlns="http://www.topografix.com/GPX/1/1">',
        f"  <metadata><name>{escape(d['name'])}</name></metadata>",
    ]
    for cid in d["climbs"]:
        c = climb_db.get(cid)
        if c:
            lines.append(
                f'  <wpt lat="{c["top"][0]}" lon="{c["top"][1]}">'
                f"<ele>{c['ele_top']}</ele><name>{escape(c['name'])}</name>"
                f"<desc>{c['length_m']} m @ {c['avg_pct']}% (max {c['max_pct']}%)</desc></wpt>"
            )
    from .route_pois import for_draft
    for poi in for_draft(d):
        lines.append(f'<wpt lat="{poi["lat"]}" lon="{poi["lon"]}"><name>{escape(poi["name"])}</name><type>{poi["kind"]}</type><desc>{poi["at_km"]} km; openingstijden niet geverifieerd</desc></wpt>')
    if d.get("cues"):
        lines.append(f'<rte><name>{escape(d["name"])}</name>')
        for cue in d["cues"]:
            lines.append(f'<rtept lat="{cue["lat"]}" lon="{cue["lon"]}"><name>{escape(cue["text"])}</name></rtept>')
        lines.append('</rte>')
    lines.append(f"  <trk><name>{escape(d['name'])}</name><trkseg>")
    n = 0
    for leg in d["_geometry"]:
        for pt in leg:
            lat, lon = pt[0], pt[1]
            ele = pt[2] if len(pt) > 2 and pt[2] is not None else None
            if ele is not None:
                lines.append(f'    <trkpt lat="{lat}" lon="{lon}"><ele>{ele}</ele></trkpt>')
            else:
                lines.append(f'    <trkpt lat="{lat}" lon="{lon}"/>')
            n += 1
    lines.append("  </trkseg></trk>")
    lines.append("</gpx>")

    with open(path, "w") as f:
        f.write("\n".join(lines))
    return {"file": path, "points": n, "total_km": d["computed"]["total_km"]}
