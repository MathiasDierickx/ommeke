"""Client voor de lokale GraphHopper-instantie."""
import json
import urllib.error
import urllib.request

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

# oude betonbanen bollen slecht: milde straf (veel landelijk Vlaanderen is
# beton, dus niet te agressief)
AVOID_CONCRETE_PRIORITY = [
    {"if": "surface == CONCRETE", "multiply_by": "0.60"},
]


def route(points_latlon, avoid_polygons=None, priority_factor: float = 0.30,
          strict: bool = False, avoid_cobbles: bool = False,
          avoid_concrete: bool = False, details: bool = False,
          profile: str = config.GH_PROFILE, *, post_fn=_post) -> dict:
    """Route langs waypoints [(lat, lon), ...].

    avoid_polygons: lijst van GeoJSON-ringen ([[lon,lat],...]) of dicts
    {"ring": ..., "factor": 0.x} die ontmoedigd worden — corridors van eerdere
    legs en/of vermijdzones rond plaatsen.
    strict: extra straf op steenwegen/drukke wegen bovenop het quiet-profiel.
    avoid_cobbles / avoid_concrete: zachte oppervlakte-voorkeuren.
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
    }
    if details:
        body["details"] = ["surface", "road_class"]
    custom = {"priority": list(STRICT_PRIORITY) if strict else []}
    if avoid_cobbles:
        custom["priority"] = custom["priority"] + list(AVOID_COBBLES_PRIORITY)
    if avoid_concrete:
        custom["priority"] = custom["priority"] + list(AVOID_CONCRETE_PRIORITY)
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
    body["custom_model"] = custom

    data = post_fn("/route", body)
    if not data.get("paths"):
        raise GhError("geen route gevonden")
    p = data["paths"][0]
    coords = [(lat, lon, (c[2] if len(c) > 2 else None)) for c in p["points"]["coordinates"] for lon, lat in [(c[0], c[1])]]
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
