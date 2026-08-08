"""Client voor de lokale GraphHopper-instantie."""
import json
import urllib.error
import urllib.request
from functools import lru_cache

from . import config


class GhError(RuntimeError):
    pass


def _post(path: str, body: dict) -> dict:
    req = urllib.request.Request(
        config.GH_URL + path,
        data=json.dumps(body).encode(),
        headers={"Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(req, timeout=60) as resp:
            return json.load(resp)
    except urllib.error.HTTPError as e:
        try:
            msg = json.load(e).get("message", str(e))
        except Exception:
            msg = str(e)
        raise GhError(f"GraphHopper: {msg}") from e
    except urllib.error.URLError as e:
        raise GhError(
            f"GraphHopper niet bereikbaar op {config.GH_URL} — draai `docker compose up -d` in de lusmaker-repo"
        ) from e


def info() -> dict:
    try:
        with urllib.request.urlopen(config.GH_URL + "/info", timeout=5) as resp:
            return json.load(resp)
    except OSError as e:
        raise GhError(f"GraphHopper niet bereikbaar op {config.GH_URL}: {e}") from e


@lru_cache(maxsize=8)
def _area_ev_works(name: str, probe_post=None) -> bool:
    """Probeer of een ingebakken ``in_<area>`` encoded value bestaat.

    GH's /info toont area-EV's niet, dus we proben met een minimaal
    routeverzoek: onbekende variabele -> foutmelding met de naam erin.
    """
    post = probe_post or _post
    body = {
        "points": [[3.883, 51.006], [3.8835, 51.0065]],
        "profile": config.GH_PROFILE,
        "points_encoded": False,
        "instructions": False,
        "ch.disable": True,
        "custom_model": {"priority": [{"if": name, "multiply_by": "0.9"}]},
    }
    try:
        post("/route", body)
        return True
    except GhError as e:
        if name in str(e):
            return False
        # andere fout (bv. geen route): variabele zelf werd geaccepteerd
        return True
    except Exception:
        return False


def available_area_evs(probe_post=None) -> frozenset[str]:
    """Welke ingebakken area-EV's bruikbaar zijn (probe-gebaseerd, gecachet)."""
    return frozenset(
        name for name in ("in_kassei_tvl", "in_druk_tvl")
        if _area_ev_works(name, probe_post)
    )


# "zo weinig mogelijk steenwegen": milde extra nudge — het quiet-profiel straft
# grote wegen al; deze factoren stapelen daar multiplicatief bovenop, dus
# te agressieve waarden veroorzaken absurde omwegen.
STRICT_PRIORITY = [
    {"if": "road_class == PRIMARY", "multiply_by": "0.30"},
    {"else_if": "road_class == SECONDARY", "multiply_by": "0.40"},
    {"else_if": "road_class == TERTIARY", "multiply_by": "0.80"},
    {"if": "max_speed >= 70", "multiply_by": "0.50"},
]


# zachte voorkeur, geen verbod: kasseien mijden waar het weinig kost
AVOID_COBBLES_PRIORITY = [
    {"if": "surface == COBBLESTONE", "multiply_by": "0.25"},
]

AVOID_COBBLES_AREA_PRIORITY = {
    "if": "in_kassei_tvl",
    "multiply_by": "0.25",
}

AVOID_BUSY_PRIORITY = {
    "if": "in_druk_tvl",
    "multiply_by": "0.45",
}

# oude betonbanen bollen slecht: milde straf (veel landelijk Vlaanderen is
# beton, dus niet te agressief)
AVOID_CONCRETE_PRIORITY = [
    {"if": "surface == CONCRETE", "multiply_by": "0.60"},
]

# trail-profiel: straten hard afstraffen zodat paden/tracks winnen
# (request-side, geen graafherimport nodig)
TRAIL_OFFROAD_PRIORITY = [
    {"if": "road_class == SECONDARY", "multiply_by": "0.25"},
    {"else_if": "road_class == TERTIARY", "multiply_by": "0.35"},
    {"else_if": "road_class == RESIDENTIAL", "multiply_by": "0.55"},
    {"else_if": "road_class == UNCLASSIFIED", "multiply_by": "0.70"},
]


def _custom_model(avoid_polygons=None, priority_factor: float = 0.30,
                  strict: bool = False, avoid_cobbles: bool = False,
                  avoid_concrete: bool = False, avoid_busy: bool = False,
                  profile: str = "", area_evs: set[str] | frozenset[str] | None = None) -> dict:
    """Bouw het gedeelde voorkeurenmodel voor gewone en round-triproutes."""
    area_evs = available_area_evs() if area_evs is None else frozenset(area_evs)
    custom = {"priority": list(STRICT_PRIORITY) if strict else []}
    if profile == "trail":
        custom["priority"] = custom["priority"] + list(TRAIL_OFFROAD_PRIORITY)
    if avoid_cobbles:
        custom["priority"] = custom["priority"] + list(AVOID_COBBLES_PRIORITY)
        if "in_kassei_tvl" in area_evs:
            custom["priority"].append(dict(AVOID_COBBLES_AREA_PRIORITY))
    if avoid_concrete:
        custom["priority"] = custom["priority"] + list(AVOID_CONCRETE_PRIORITY)
    if avoid_busy and "in_druk_tvl" in area_evs:
        custom["priority"].append(dict(AVOID_BUSY_PRIORITY))
    if avoid_polygons:
        features = []
        for k, item in enumerate(avoid_polygons):
            ring = item["ring"] if isinstance(item, dict) else item
            factor = item.get("factor", priority_factor) if isinstance(item, dict) else priority_factor
            features.append(
                {
                    "type": "Feature",
                    "id": f"corridor{k}",
                    "properties": {},
                    "geometry": {"type": "Polygon", "coordinates": [ring]},
                }
            )
            custom["priority"].append(
                {"if": f"in_corridor{k}", "multiply_by": str(factor)}
            )
        custom["areas"] = {"type": "FeatureCollection", "features": features}
    return custom


def _path_result(data: dict, details: bool = False) -> dict:
    if not data.get("paths"):
        raise GhError("geen route gevonden")
    p = data["paths"][0]
    coords = [
        (lat, lon, (c[2] if len(c) > 2 else None))
        for c in p["points"]["coordinates"]
        for lon, lat in [(c[0], c[1])]
    ]
    out = {
        "distance_m": p["distance"],
        "time_s": p["time"] / 1000.0,
        "ascend_m": round(p.get("ascend", 0.0), 1),
        "descend_m": round(p.get("descend", 0.0), 1),
        "coords": coords,
    }
    if details:
        out["details"] = p.get("details", {})
    return out


def route(points_latlon, avoid_polygons=None, priority_factor: float = 0.30,
          strict: bool = False, avoid_cobbles: bool = False,
          avoid_concrete: bool = False, avoid_busy: bool = False,
          details: bool = False,
          profile: str = config.GH_PROFILE, start_heading: float | None = None,
          point_hints: list | None = None, *,
          area_evs: set[str] | frozenset[str] | None = None,
          post_fn=_post) -> dict:
    """Route langs waypoints [(lat, lon), ...].

    avoid_polygons: lijst van GeoJSON-ringen ([[lon,lat],...]) of dicts
    {"ring": ..., "factor": 0.x} die ontmoedigd worden — corridors van eerdere
    legs en/of vermijdzones rond plaatsen.
    strict: extra straf op steenwegen/drukke wegen bovenop het quiet-profiel.
    avoid_cobbles / avoid_concrete: zachte oppervlakte-voorkeuren.
    avoid_busy: zachte voorkeur voor autovrije/verkeersarme wegen.
    details: per-segment surface/road_class in het resultaat ("details").
    profile: GraphHopper-profiel, standaard het bestaande fietsprofiel.
    """
    body = {
        "points": [[lon, lat] for lat, lon in points_latlon],
        "profile": profile,
        "elevation": True,
        "points_encoded": False,
        "instructions": False,
        "locale": "nl",
        "ch.disable": True,
        # geen U-bochten op via-punten: voorkomt heen-en-weer-uitsteeksels
        # bij klimvoeten en -toppen
        "pass_through": True,
    }
    if start_heading is not None:
        # vertrek in de aankomstrichting van de vorige leg: voorkomt
        # heen-en-weer-uitsteeksels op leg-grenzen
        body["headings"] = [round(start_heading, 1)]
    if point_hints is not None:
        # snap via-punten op de juiste (genoemde) weg, niet op een parallelpad
        body["point_hints"] = point_hints
    if details:
        body["details"] = ["surface", "road_class"]
    body["custom_model"] = _custom_model(
        avoid_polygons, priority_factor, strict, avoid_cobbles, avoid_concrete,
        avoid_busy, profile=profile, area_evs=area_evs,
    )

    data = post_fn("/route", body)
    return _path_result(data, details)


def round_trip(point, distance_m: float, seed: int,
               profile: str = config.GH_PROFILE, avoid_polygons=None,
               priority_factor: float = 0.30, strict: bool = False,
               avoid_cobbles: bool = False, avoid_concrete: bool = False,
               avoid_busy: bool = False, details: bool = False, *,
               area_evs: set[str] | frozenset[str] | None = None,
               post_fn=_post) -> dict:
    """Maak via GraphHopper een rondrit vanaf één ``(lat, lon)``-punt."""
    lat, lon = point
    body = {
        "points": [[lon, lat]],
        "profile": profile,
        "algorithm": "round_trip",
        "round_trip.distance": distance_m,
        "round_trip.seed": seed,
        "elevation": True,
        "points_encoded": False,
        "instructions": False,
        "locale": "nl",
        "ch.disable": True,
        "custom_model": _custom_model(
            avoid_polygons, priority_factor, strict, avoid_cobbles, avoid_concrete,
            avoid_busy, profile=profile, area_evs=area_evs,
        ),
    }
    if details:
        body["details"] = ["surface", "road_class"]
    return _path_result(post_fn("/route", body), details)
