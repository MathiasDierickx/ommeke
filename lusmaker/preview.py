"""Zelfstandige HTML-kaartpreview van een gerouteerde draft."""
import html
import json
import math

from . import geo, heat
from .draft import DraftError


ROUTE_COLORS = ("#2563eb", "#f97316")
CLIMB_COLOR = "#dc2626"
MAX_ROUTE_POINTS = 1500
MAX_POI_MARKERS = 40
POI_ICONS = {
    "picknickbank": "🧺",
    "zitbank": "🪑",
    "toilet": "🚻",
    "uitkijktoren": "🔭",
    "fietspomp_en_fietsherstel": "🔧",
    "fietsverhuur": "🚲",
    "speeltuin": "🛝",
    "ebike": "⚡",
}
POI_LABELS = {
    "picknickbank": "Picknickbank",
    "zitbank": "Zitbank",
    "toilet": "Toilet",
    "uitkijktoren": "Uitkijktoren",
    "fietspomp_en_fietsherstel": "Fietspomp of fietsherstel",
    "fietsverhuur": "Fietsverhuur",
    "speeltuin": "Speeltuin",
    "ebike": "E-bikepunt",
}


def _json(value) -> str:
    """JSON voor een scriptblok, zonder dat data het blok kan afsluiten."""
    return (
        json.dumps(value, ensure_ascii=False)
        .replace("&", "\\u0026")
        .replace("<", "\\u003c")
        .replace(">", "\\u003e")
    )


def _sample(coords: list, limit: int) -> list:
    if len(coords) <= limit:
        return coords
    if limit <= 1:
        return coords[:limit]
    indexes = [round(i * (len(coords) - 1) / (limit - 1)) for i in range(limit)]
    return [coords[i] for i in indexes]


def _downsample(legs: list[list], limit: int = MAX_ROUTE_POINTS) -> list[list]:
    """Verdeel een globale puntenlimiet proportioneel over alle legs."""
    total = sum(len(leg) for leg in legs)
    if total <= limit:
        return legs
    nonempty = [i for i, leg in enumerate(legs) if leg]
    base = 2 * len(nonempty)
    budget = max(0, limit - base)
    variable = sum(max(0, len(legs[i]) - 2) for i in nonempty)
    quotas = {i: min(2, len(legs[i])) for i in nonempty}
    fractions = []
    for i in nonempty:
        share = budget * max(0, len(legs[i]) - 2) / max(variable, 1)
        extra = math.floor(share)
        quotas[i] += extra
        fractions.append((share - extra, i))
    left = limit - sum(quotas.values())
    for _fraction, i in sorted(fractions, reverse=True):
        if left <= 0:
            break
        if quotas[i] < len(legs[i]):
            quotas[i] += 1
            left -= 1
    return [_sample(leg, quotas.get(i, 0)) for i, leg in enumerate(legs)]


def _profile(legs: list[list], leg_meta: list[dict]) -> str:
    width, height = 1000, 220
    left, right, top, bottom = 52, 18, 18, 36
    distance = 0.0
    points = []
    zones = []
    previous = None
    for i, coords in enumerate(legs):
        start = distance
        for point in coords:
            if previous is not None:
                distance += geo.haversine(previous[0], previous[1], point[0], point[1])
            previous = point
            if len(point) > 2 and point[2] is not None:
                points.append((distance, float(point[2])))
        if i < len(leg_meta) and leg_meta[i].get("climb"):
            zones.append((start, distance))

    if not points:
        return (
            f'<svg class="profile" viewBox="0 0 {width} {height}" role="img" '
            'aria-label="Hoogteprofiel zonder hoogtegegevens">'
            '<text x="500" y="110" text-anchor="middle">Geen hoogtegegevens beschikbaar</text>'
            '</svg>'
        )

    min_ele = min(ele for _dist, ele in points)
    max_ele = max(ele for _dist, ele in points)
    ele_span = max(max_ele - min_ele, 1.0)
    route_span = max(distance, 1.0)
    plot_w, plot_h = width - left - right, height - top - bottom

    def x(value):
        return left + value / route_span * plot_w

    def y(value):
        return top + (max_ele - value) / ele_span * plot_h

    zone_html = "".join(
        f'<rect x="{x(start):.1f}" y="{top}" width="{max(1, x(end) - x(start)):.1f}" '
        f'height="{plot_h}" fill="{CLIMB_COLOR}" fill-opacity="0.14" />'
        for start, end in zones
    )
    line_points = " ".join(f"{x(dist):.1f},{y(ele):.1f}" for dist, ele in points)
    return f'''<svg class="profile" viewBox="0 0 {width} {height}" role="img" aria-label="Hoogteprofiel">
  {zone_html}
  <line x1="{left}" y1="{top + plot_h}" x2="{width - right}" y2="{top + plot_h}" class="axis" />
  <polyline points="{line_points}" class="elevation" />
  <text x="{left}" y="{height - 10}">0 km</text>
  <text x="{width - right}" y="{height - 10}" text-anchor="end">{distance / 1000:.1f} km</text>
  <text x="{left - 8}" y="{top + 5}" text-anchor="end">{max_ele:.0f} m</text>
  <text x="{left - 8}" y="{top + plot_h}" text-anchor="end">{min_ele:.0f} m</text>
</svg>'''


def _metric(label: str, value, suffix: str = "") -> str:
    if value is None:
        return ""
    return f'<span><strong>{html.escape(str(value))}{suffix}</strong> {label}</span>'


def render(
    d: dict,
    climb_db: dict,
    *,
    feature_selector=heat.features_near_route,
) -> str:
    """Render een gerouteerde draft als één zelfstandig HTML-document."""
    if not d.get("_geometry"):
        raise DraftError("routeer eerst: `lus draft route <id>`")

    computed = d.get("computed") or {}
    leg_meta = computed.get("legs") or []
    geometry = d["_geometry"]
    route_coords = [
        (point[0], point[1]) for leg in geometry for point in leg
    ]
    route_features = feature_selector(
        route_coords,
        poi_radius_m=150.0,
        knot_radius_m=100.0,
        max_pois=MAX_POI_MARKERS,
    )
    poi_markers = []
    for poi in route_features.get("pois", [])[:MAX_POI_MARKERS]:
        poi_type = str(poi.get("type", "poi"))
        label = POI_LABELS.get(poi_type, poi_type.replace("_", " ").title())
        name = poi.get("naam")
        popup = f"<strong>{html.escape(label)}</strong>"
        if name:
            popup += f"<br>{html.escape(str(name))}"
        poi_markers.append(
            {
                "coords": [poi["lat"], poi["lon"]],
                "icon": POI_ICONS.get(poi_type, "•"),
                "popup": popup,
            }
        )
    knot_markers = [
        {
            "coords": [knot["lat"], knot["lon"]],
            "nummer": str(knot["nummer"]),
            "popup": (
                f"Knooppunt {html.escape(str(knot['nummer']))} "
                f"({html.escape(str(knot['type']))})"
            ),
        }
        for knot in route_features.get("knopen", [])
    ]
    map_legs = _downsample(geometry)
    leg_data = []
    for i, coords in enumerate(map_legs):
        meta = leg_meta[i] if i < len(leg_meta) else {}
        popup = (
            f"<strong>{html.escape(str(meta.get('from', 'start')))}</strong> → "
            f"<strong>{html.escape(str(meta.get('to', 'einde')))}</strong><br>"
            f"{html.escape(str(meta.get('km', '?')))} km · "
            f"{html.escape(str(meta.get('ascend_m', '?')))} hm"
        )
        leg_data.append(
            {
                "coords": [[point[0], point[1]] for point in coords],
                "color": CLIMB_COLOR if meta.get("climb") else ROUTE_COLORS[i % 2],
                "popup": popup,
            }
        )

    climb_markers = []
    for climb_id in d.get("climbs", []):
        climb = climb_db.get(climb_id)
        if not climb or not climb.get("top"):
            continue
        description = (
            f"<strong>{html.escape(str(climb.get('name', climb_id)))}</strong><br>"
            f"{html.escape(str(climb.get('length_m', '?')))} m · "
            f"gem. {html.escape(str(climb.get('avg_pct', '?')))}% · "
            f"max. {html.escape(str(climb.get('max_pct', '?')))}%"
        )
        climb_markers.append({"top": climb["top"][:2], "popup": description})

    quality = computed.get("kwaliteit") or {}
    crossings = quality.get("kruisingen", quality.get("steenweg_kruisingen"))
    metrics = "".join(
        (
            _metric("km", computed.get("total_km")),
            _metric("hoogtemeters", computed.get("ascend_m"), " m"),
            _metric("kassei", quality.get("kassei_m"), " m"),
            _metric("steenweg", quality.get("steenweg_m"), " m"),
            _metric("kruisingen", crossings),
            _metric("populair", quality.get("populair_pct"), "%"),
        )
    )
    start = d.get("start") or {}
    start_point = [start.get("lat"), start.get("lon")]
    title = html.escape(str(d.get("name", "Route")))
    profile = _profile(geometry, leg_meta)
    polyline_js = "\n".join(
        (
            f"    L.polyline({_json(leg['coords'])}, "
            f"{{color: {_json(leg['color'])}, weight: 5, opacity: 0.9}})"
            f".bindPopup({_json(leg['popup'])}).addTo(map);\n"
            f"    bounds.push(...{_json(leg['coords'])});"
        )
        for leg in leg_data
    )

    return f'''<!doctype html>
<html lang="nl">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>{title} — kaartpreview</title>
  <link rel="stylesheet" href="https://unpkg.com/leaflet@1.9.4/dist/leaflet.css">
  <style>
    :root {{ color-scheme: light; font-family: system-ui, sans-serif; color: #172033; background: #f6f7f9; }}
    body {{ margin: 0; }} header, section {{ max-width: 1200px; margin: auto; padding: 18px 24px; }}
    h1 {{ margin: 0 0 10px; font-size: clamp(1.5rem, 4vw, 2.3rem); }}
    .metrics {{ display: flex; flex-wrap: wrap; gap: 8px 20px; color: #526070; }}
    #map {{ height: min(68vh, 680px); min-height: 420px; }}
    h2 {{ margin-bottom: 8px; }} .profile {{ width: 100%; height: auto; background: white; border-radius: 10px; }}
    .profile .axis {{ stroke: #94a3b8; }} .profile .elevation {{ fill: none; stroke: #172033; stroke-width: 3; }}
    .profile text {{ fill: #526070; font-size: 15px; }} .start-marker {{ font-size: 25px; line-height: 30px; text-align: center; }}
    .poi-marker {{ font-size: 16px; line-height: 20px; text-align: center; filter: drop-shadow(0 1px 1px white); }}
    .knot-marker {{ color: #172033; background: white; border: 1px solid #526070; border-radius: 8px; font: 700 11px/16px system-ui, sans-serif; text-align: center; }}
  </style>
</head>
<body>
  <header><h1>{title}</h1><div class="metrics">{metrics}</div></header>
  <main><div id="map" aria-label="Kaart van de route"></div><section><h2>Hoogteprofiel</h2>{profile}</section></main>
  <script src="https://unpkg.com/leaflet@1.9.4/dist/leaflet.js"></script>
  <script>
    const map = L.map('map');
    L.tileLayer('https://{{s}}.tile.openstreetmap.org/{{z}}/{{x}}/{{y}}.png', {{
      maxZoom: 19,
      attribution: '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a>-bijdragers'
    }}).addTo(map);
    const bounds = [];
{polyline_js}
    const start = {_json(start_point)};
    if (start[0] != null && start[1] != null) {{
      L.marker(start, {{icon: L.divIcon({{className: 'start-marker', html: '🏠', iconSize: [30, 30]}})}})
        .bindPopup('Start').addTo(map);
    }}
    {_json(climb_markers)}.forEach(climb => L.circleMarker(climb.top, {{
      radius: 7, color: '{CLIMB_COLOR}', fillColor: '{CLIMB_COLOR}', fillOpacity: 1
    }}).bindPopup(climb.popup).addTo(map));
    {_json(poi_markers)}.forEach(poi => L.marker(poi.coords, {{
      icon: L.divIcon({{className: 'poi-marker', html: poi.icon, iconSize: [20, 20]}})
    }}).bindPopup(poi.popup).addTo(map));
    {_json(knot_markers)}.forEach(knot => L.marker(knot.coords, {{
      icon: L.divIcon({{className: 'knot-marker', html: knot.nummer, iconSize: [22, 16]}})
    }}).bindPopup(knot.popup).addTo(map));
    if (bounds.length) map.fitBounds(bounds, {{padding: [24, 24]}});
  </script>
</body>
</html>'''


def export(
    d: dict,
    climb_db: dict,
    path: str,
    *,
    feature_selector=heat.features_near_route,
) -> dict:
    """Schrijf de preview naar ``path`` en geef het CLI-resultaat terug."""
    document = render(d, climb_db, feature_selector=feature_selector)
    with open(path, "w", encoding="utf-8") as file:
        file.write(document)
    computed = d["computed"]
    return {
        "file": path,
        "total_km": computed["total_km"],
        "ascend_m": computed["ascend_m"],
    }
