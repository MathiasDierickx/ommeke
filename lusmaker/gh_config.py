"""Genereert de GraphHopper-configuratie en custom sportmodellen."""
import json

from . import config

GH_CONFIG_YML = """\
graphhopper:
  datareader.file: /lus/data/{pbf_name}
  graph.location: /lus/gh/graph-cache

  graph.elevation.provider: skadi
  graph.elevation.cache_dir: /lus/gh/elevation-cache

  graph.encoded_values: bike_access, bike_priority, bike_average_speed, bike_road_access, foot_access, foot_priority, foot_average_speed, foot_road_access, roundabout, road_class, road_environment, surface, smoothness, max_speed, track_type, bike_network, mtb_rating, hike_rating, ferry_speed

  import.osm.ignored_highways: motorway, trunk

  custom_areas.directory: /lus/gh/custom_areas
  custom_models.directory: /lus/gh/custom_models
  profiles:
    - name: quiet
      custom_model_files: [bike.json, quiet.json]
    - name: trail
      custom_model_files: [foot.json, trail.json]

  profiles_ch: []
  prepare.min_network_size: 200

server:
  application_connectors:
    - type: http
      port: {gh_port}
      bind_host: 0.0.0.0
  admin_connectors:
    - type: http
      port: {admin_port}
      bind_host: 0.0.0.0
"""

# Rustige-wegen-profiel: straffen (0..1) bovenop het gebundelde bike.json.
# 'bike_network == MISSING' straft wegen die níet op een fietsroutenetwerk
# liggen — netto hetzelfde als een boost voor knooppuntroutes.
QUIET_MODEL = {
    "priority": [
        {"if": "road_class == PRIMARY", "multiply_by": "0.30"},
        {"else_if": "road_class == SECONDARY", "multiply_by": "0.50"},
        {"else_if": "road_class == TERTIARY", "multiply_by": "0.85"},
        {"if": "bike_network == MISSING", "multiply_by": "0.75"},
        {"if": "max_speed >= 70", "multiply_by": "0.60"},
        {"if": "surface == COBBLESTONE", "multiply_by": "0.80"},
        {"if": "surface == GRAVEL || surface == DIRT || surface == GRASS || surface == SAND", "multiply_by": "0.30"},
        {"if": "road_environment == FERRY", "multiply_by": "0.10"},
    ]
}

TRAIL_MODEL = {
    "priority": [
        {"if": "road_class == PRIMARY", "multiply_by": "0.20"},
        {"else_if": "road_class == SECONDARY", "multiply_by": "0.30"},
        {"else_if": "road_class == TERTIARY", "multiply_by": "0.55"},
        {"else_if": "road_class == RESIDENTIAL", "multiply_by": "0.75"},
        {
            "if": "surface == ASPHALT || surface == CONCRETE || surface == PAVED",
            "multiply_by": "0.75",
        },
        {"if": "road_environment == FERRY", "multiply_by": "0.10"},
    ]
}


# relatieve boost voor bereden corridors: alles daarbuiten een zachte straf
POPULAR_RULE = {"if": "!in_popular", "multiply_by": "0.75"}
POPULAR_TRAIL_RULE = {"if": "!in_popular_trail", "multiply_by": "0.75"}


def _custom_area_ids() -> set[str]:
    path = config.CUSTOM_AREAS / "popular.geojson"
    if not path.exists():
        return set()
    document = json.loads(path.read_text(encoding="utf-8"))
    return {
        feature.get("id")
        for feature in document.get("features", [])
        if isinstance(feature, dict) and feature.get("id")
    }


def write_gh_files() -> list[str]:
    config.ensure_dirs()
    region = config.current_region()
    cfg = config.GH_DIR / "config.yml"
    cfg.write_text(
        GH_CONFIG_YML.format(
            pbf_name=region.pbf_name,
            gh_port=region.gh_port,
            admin_port=region.gh_port + 1,
        )
    )
    area_ids = _custom_area_ids()
    model = dict(QUIET_MODEL)
    if "popular" in area_ids:
        model = {"priority": QUIET_MODEL["priority"] + [POPULAR_RULE]}
    quiet = config.GH_DIR / "custom_models" / "quiet.json"
    quiet.write_text(json.dumps(model, indent=2))
    trail_model = dict(TRAIL_MODEL)
    if "popular_trail" in area_ids:
        trail_model = {
            "priority": TRAIL_MODEL["priority"] + [POPULAR_TRAIL_RULE]
        }
    trail = config.GH_DIR / "custom_models" / "trail.json"
    trail.write_text(json.dumps(trail_model, indent=2))
    return [str(cfg), str(quiet), str(trail)]
