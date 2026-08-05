"""Genereert de GraphHopper-configuratie en het 'quiet' custom model."""
import json

from . import config

GH_CONFIG_YML = """\
graphhopper:
  datareader.file: /lus/data/belgium-latest.osm.pbf
  graph.location: /lus/gh/graph-cache

  graph.elevation.provider: skadi
  graph.elevation.cache_dir: /lus/gh/elevation-cache

  graph.encoded_values: bike_access, bike_priority, bike_average_speed, bike_road_access, roundabout, road_class, road_environment, surface, smoothness, max_speed, track_type, bike_network, mtb_rating, hike_rating, ferry_speed

  import.osm.ignored_highways: motorway, trunk

  custom_areas.directory: /lus/gh/custom_areas
  custom_models.directory: /lus/gh/custom_models
  profiles:
    - name: quiet
      custom_model_files: [bike.json, quiet.json]

  profiles_ch: []
  prepare.min_network_size: 200

server:
  application_connectors:
    - type: http
      port: 8989
      bind_host: 0.0.0.0
  admin_connectors:
    - type: http
      port: 8990
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


# relatieve boost voor bereden corridors: alles daarbuiten een zachte straf
POPULAR_RULE = {"if": "!in_popular", "multiply_by": "0.75"}


def write_gh_files() -> list[str]:
    config.ensure_dirs()
    cfg = config.GH_DIR / "config.yml"
    cfg.write_text(GH_CONFIG_YML)
    model = dict(QUIET_MODEL)
    if (config.CUSTOM_AREAS / "popular.geojson").exists():
        model = {"priority": QUIET_MODEL["priority"] + [POPULAR_RULE]}
    quiet = config.GH_DIR / "custom_models" / "quiet.json"
    quiet.write_text(json.dumps(model, indent=2))
    return [str(cfg), str(quiet)]
