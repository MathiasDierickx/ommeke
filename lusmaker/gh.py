"""Client voor de lokale GraphHopper-instantie."""
import json
import os
import threading
import time
import urllib.error
import urllib.request
from functools import lru_cache
from pathlib import Path

from . import config
from .heat import ACTIVITIES, PAVED_PREFERENCE_ACTIVITIES


class GhError(RuntimeError):
    pass


_ready_lock = threading.Lock()
_ready_url: str | None = None


def _health_ok(url: str) -> bool:
    try:
        with urllib.request.urlopen(url + "/health", timeout=2) as resp:
            return resp.status == 200
    except OSError:
        return False


def wait_until_ready(*, health=_health_ok, sleep=time.sleep, clock=time.monotonic) -> None:
    """Wacht op een GraphHopper die naast de API opstart (Lambda).

    Alleen actief met ``LUSMAKER_GH_STARTUP_WAIT_S``; lokaal blijft een
    ontbrekende router meteen een duidelijke fout.
    """
    global _ready_url
    budget = float(os.environ.get("LUSMAKER_GH_STARTUP_WAIT_S") or 0)
    url = config.GH_URL
    if budget <= 0 or _ready_url == url:
        return
    marker = os.environ.get("LUSMAKER_GH_FAILED_MARKER")
    with _ready_lock:
        if _ready_url == url:
            return
        deadline = clock() + budget
        while True:
            if health(url):
                _ready_url = url
                return
            if marker and Path(marker).exists():
                raise GhError("De router kon niet starten. Probeer het over enkele minuten opnieuw.")
            if clock() >= deadline:
                raise GhError("De router is nog aan het opstarten. Probeer het over een minuut opnieuw.")
            sleep(0.25)


def _post(path: str, body: dict) -> dict:
    wait_until_ready()
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
    wait_until_ready()
    try:
        with urllib.request.urlopen(config.GH_URL + "/info", timeout=5) as resp:
            return json.load(resp)
    except OSError as e:
        raise GhError(f"GraphHopper niet bereikbaar op {config.GH_URL}: {e}") from e


def _area_ev_works(name: str, probe_post=None) -> bool:
    return _cached_area_ev_works(name, config.GH_URL, tuple(config.current_region().bbox), probe_post)


@lru_cache(maxsize=128)
def _cached_area_ev_works(name: str, router_url: str, bbox: tuple, probe_post=None) -> bool:
    """Probeer of een ingebakken ``in_<area>`` encoded value bestaat.

    GH's /info toont area-EV's niet, dus we proben met een minimaal
    routeverzoek: onbekende variabele -> foutmelding met de naam erin.
    """
    post = probe_post or _post
    lat, lon = (bbox[0] + bbox[2]) / 2, (bbox[1] + bbox[3]) / 2
    body = {
        "points": [[lon, lat], [lon + 0.0001, lat + 0.0001]],
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
        message = str(e)
        # Ontbrekende area meldt GH als "Area '<naam>' wasn't found" — dus
        # zonder de in_-prefix. Herken zowel de EV-naam als de kale areanaam.
        area_name = name.removeprefix("in_")
        if name in message or (area_name in message and "wasn't found" in message):
            return False
        # Een fout kan vóór modelcompilatie optreden (bv. punt buiten graaf).
        # Alleen een geslaagd verzoek bewijst dat deze area bruikbaar is.
        return False
    except Exception:
        return False


_area_ev_works.cache_clear = _cached_area_ev_works.cache_clear


def available_area_evs(probe_post=None) -> frozenset[str]:
    """Welke ingebakken area-EV's bruikbaar zijn (probe-gebaseerd, gecachet)."""
    names = (
        "in_kassei_tvl",
        "in_druk_tvl",
        "in_niet_autovrij_tvl",
        *(f"in_popular_{activity}" for activity in ACTIVITIES),
        "in_onverhard",
    )
    return frozenset(
        name for name in names
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
                  profile: str = "", area_evs: set[str] | frozenset[str] | None = None,
                  heat_activity: str | None = None) -> dict:
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
    if avoid_busy:
        if "in_niet_autovrij_tvl" in area_evs:
            # Een toegangskenmerk, geen intensiteitsmeting. Houd het gewicht
            # mild en stapel nooit met de historische alias druk_tvl.
            custom["priority"].append({"if": "in_niet_autovrij_tvl", "multiply_by": "0.85"})
        elif "in_druk_tvl" in area_evs:
            custom["priority"].append(dict(AVOID_BUSY_PRIORITY))
    activity_ev = f"in_popular_{heat_activity}" if heat_activity else None
    if activity_ev in area_evs:
        custom["priority"].append(
            {"if": f"!{activity_ev}", "multiply_by": "0.85"}
        )
    if (
        heat_activity in PAVED_PREFERENCE_ACTIVITIES
        and "in_onverhard" in area_evs
    ):
        custom["priority"].append(
            {"if": "in_onverhard", "multiply_by": "0.55"}
        )
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
    if "instructions" in p:
        out["instructions"] = p["instructions"]
    if details:
        out["details"] = p.get("details", {})
    return out


def route(points_latlon, avoid_polygons=None, priority_factor: float = 0.30,
          strict: bool = False, avoid_cobbles: bool = False,
          avoid_concrete: bool = False, avoid_busy: bool = False,
          details: bool = False,
          profile: str = config.GH_PROFILE, start_heading: float | None = None,
          point_hints: list | None = None,
          headings: list | None = None, *,
          instructions: bool = False,
          heat_activity: str | None = None,
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
    heat_activity: activiteit voor de request-side populariteitsvoorkeur.
    point_hints: één straatnaam per punt ("" = geen hint); lengte moet gelijk
    zijn aan het aantal punten, anders wordt de hint genegeerd.
    headings: één kompasrichting per punt (None = geen voorkeur, als JSON
    null); alleen gebruikt als de lengte gelijk is aan het aantal punten en
    anders dan `start_heading`.
    """
    body = {
        "points": [[lon, lat] for lat, lon in points_latlon],
        "profile": profile,
        "elevation": True,
        "points_encoded": False,
        "instructions": instructions,
        "locale": "nl",
        "ch.disable": True,
        # geen U-bochten op via-punten: voorkomt heen-en-weer-uitsteeksels
        # bij klimvoeten en -toppen
        "pass_through": True,
    }
    n_points = len(points_latlon)
    if headings is not None and len(headings) == n_points \
            and any(h is not None for h in headings):
        body["headings"] = [None if h is None else round(h, 1) for h in headings]
    elif start_heading is not None:
        # vertrek in de aankomstrichting van de vorige leg: voorkomt
        # heen-en-weer-uitsteeksels op leg-grenzen
        body["headings"] = [round(start_heading, 1)]
    if point_hints is not None and len(point_hints) == n_points \
            and any(point_hints):
        # snap via-punten op de juiste (genoemde) weg, niet op een parallelpad
        body["point_hints"] = point_hints
    if details:
        body["details"] = ["surface", "road_class"]
    body["custom_model"] = _custom_model(
        avoid_polygons, priority_factor, strict, avoid_cobbles, avoid_concrete,
        avoid_busy, profile=profile, area_evs=area_evs,
        heat_activity=heat_activity,
    )

    data = post_fn("/route", body)
    return _path_result(data, details)


def round_trip(point, distance_m: float, seed: int,
               profile: str = config.GH_PROFILE, avoid_polygons=None,
               priority_factor: float = 0.30, strict: bool = False,
               avoid_cobbles: bool = False, avoid_concrete: bool = False,
               avoid_busy: bool = False, details: bool = False, *,
               heat_activity: str | None = None,
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
            heat_activity=heat_activity,
        ),
    }
    if details:
        body["details"] = ["surface", "road_class"]
    return _path_result(post_fn("/route", body), details)
