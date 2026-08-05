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


def route(points_latlon, avoid_polygons=None, priority_factor: float = 0.15) -> dict:
    """Route langs waypoints [(lat, lon), ...].

    avoid_polygons: GeoJSON-ringen ([[lon,lat],...]) die sterk ontmoedigd worden
    (voor de geen-zelfde-weg-terug-lus).
    """
    body = {
        "points": [[lon, lat] for lat, lon in points_latlon],
        "profile": config.GH_PROFILE,
        "elevation": True,
        "points_encoded": False,
        "instructions": False,
        "locale": "nl",
        "ch.disable": True,
    }
    custom = {"priority": []}
    if avoid_polygons:
        features = []
        for k, ring in enumerate(avoid_polygons):
            features.append(
                {
                    "type": "Feature",
                    "id": f"corridor{k}",
                    "properties": {},
                    "geometry": {"type": "Polygon", "coordinates": [ring]},
                }
            )
            custom["priority"].append(
                {"if": f"in_corridor{k}", "multiply_by": str(priority_factor)}
            )
        custom["areas"] = {"type": "FeatureCollection", "features": features}
    body["custom_model"] = custom

    data = _post("/route", body)
    if not data.get("paths"):
        raise GhError("geen route gevonden")
    p = data["paths"][0]
    coords = [(lat, lon, (c[2] if len(c) > 2 else None)) for c in p["points"]["coordinates"] for lon, lat in [(c[0], c[1])]]
    return {
        "distance_m": p["distance"],
        "time_s": p["time"] / 1000.0,
        "ascend_m": round(p.get("ascend", 0.0), 1),
        "descend_m": round(p.get("descend", 0.0), 1),
        "coords": coords,
    }
