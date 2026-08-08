"""Pure tests voor de persoonlijke en gecureerde routelagen."""

import os
import pickle
import tempfile
from contextlib import contextmanager
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from lusmaker import config, heat


@contextmanager
def _isolated_home(path: Path):
    previous = os.environ.get("LUSMAKER_HOME")
    os.environ["LUSMAKER_HOME"] = str(path)
    try:
        yield
    finally:
        if previous is None:
            os.environ.pop("LUSMAKER_HOME", None)
        else:
            os.environ["LUSMAKER_HOME"] = previous


MINI_LINES = {
    "type": "FeatureCollection",
    "features": [
        {
            "type": "Feature",
            "geometry": {
                "type": "LineString",
                "coordinates": [[3.7, 50.8], [3.702, 50.8]],
            },
            "properties": {},
        },
        {
            "type": "Feature",
            "geometry": {
                "type": "MultiLineString",
                "coordinates": [[[3.71, 50.81], [3.71, 50.812]]],
            },
            "properties": {},
        },
    ],
}


def test_fetch_vlaanderen_parses_lines_uses_bbox_and_caches_separate_sets():
    calls = []

    def fetcher(url):
        calls.append(url)
        layer = parse_qs(urlparse(url).query)["typeNames"][0]
        return MINI_LINES if layer.endswith("cycling_node_network_v2") else {
            "type": "FeatureCollection",
            "features": [],
        }

    with tempfile.TemporaryDirectory() as temp_dir:
        with _isolated_home(Path(temp_dir)):
            result = heat.fetch_vlaanderen(fetcher=fetcher)
            with open(config.VLAANDEREN_ROUTES_PKL, "rb") as handle:
                cached = pickle.load(handle)

    expected = heat._track_cells([(50.8, 3.7), (50.8, 3.702)])
    expected |= heat._track_cells([(50.81, 3.71), (50.812, 3.71)])
    assert cached == {"fiets": expected, "wandel": set()}
    assert result["fiets_cellen"] == len(expected)
    assert result["wandel_cellen"] == 0
    assert len(calls) == 3
    for url in calls:
        query = parse_qs(urlparse(url).query)
        assert query["bbox"] == ["3.35,50.68,4.2,51.1,EPSG:4326"]
        assert query["outputFormat"] == ["application/json"]


def test_fetch_vlaanderen_rejects_html_with_clear_error():
    with tempfile.TemporaryDirectory() as temp_dir:
        with _isolated_home(Path(temp_dir)):
            try:
                heat.fetch_vlaanderen(fetcher=lambda _url: b"<html>niet gevonden</html>")
            except RuntimeError as exc:
                assert "HTML/XML-antwoord" in str(exc)
                assert "fietsnetwerk" in str(exc)
            else:
                raise AssertionError("HTML-antwoord werd als GeoJSON aanvaard")
