"""Pure tests voor de OSM-extract- en gazetteerstructuur."""

import tempfile
from pathlib import Path

from lusmaker import config, osm


def test_gazetteer_keeps_all_normalised_waterway_segments_intact():
    first = [(51.00, 3.70), (51.01, 3.71), (51.02, 3.72)]
    second = [(51.02, 3.72), (51.03, 3.73)]
    extract = {
        "ways": [],
        "places": [],
        "landmarks": [],
        "waterways": [
            ("De Schélde", "river", first),
            ("De Schelde", "river", second),
        ],
    }

    with tempfile.TemporaryDirectory() as temp_dir:
        path = Path(temp_dir) / "gazetteer.pkl"
        previous = config.__dict__.get("GAZETTEER_PKL")
        config.GAZETTEER_PKL = path
        try:
            gazetteer = osm.build_gazetteer(extract)
        finally:
            if previous is None:
                del config.GAZETTEER_PKL
            else:
                config.GAZETTEER_PKL = previous

    assert gazetteer["waterways"] == {"de schelde": [first, second]}


def test_waterway_extract_contract_is_limited_to_rivers_and_canals():
    assert osm.WATERWAY_VALUES == {"river", "canal"}
    assert osm.EXTRACT_FORMAT_VERSION == 4
