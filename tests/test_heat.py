"""Pure tests voor de persoonlijke en gecureerde routelagen."""

import json
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


def _write_gpx(path: Path):
    points = "".join(
        f'<trkpt lat="{50.8 + index * 0.0001}" lon="3.7" />'
        for index in range(10)
    )
    path.write_text(f"<gpx><trk><trkseg>{points}</trkseg></trk></gpx>")


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


def test_fetch_vlaanderen_reports_http_404_as_clear_error():
    class NotFound(OSError):
        code = 404

    def fetcher(_url):
        raise NotFound("niet gevonden")

    with tempfile.TemporaryDirectory() as temp_dir:
        with _isolated_home(Path(temp_dir)):
            try:
                heat.fetch_vlaanderen(fetcher=fetcher)
            except RuntimeError as exc:
                assert "HTTP 404" in str(exc)
                assert "fietsnetwerk" in str(exc)
            else:
                raise AssertionError("HTTP 404 werd niet als duidelijke fout gemeld")


def test_build_writes_both_area_ids_and_keeps_cellsets_separate():
    bike_cell = heat.geo.cell(50.82, 3.72)
    walk_cell = heat.geo.cell(50.83, 3.73)
    with tempfile.TemporaryDirectory() as temp_dir:
        with _isolated_home(Path(temp_dir)):
            config.ensure_dirs()
            _write_gpx(config.HEAT_DIR / "eigen.gpx")
            with open(config.VLAANDEREN_ROUTES_PKL, "wb") as handle:
                pickle.dump(
                    {"fiets": {bike_cell}, "wandel": {walk_cell}}, handle
                )
            result = heat.build()
            geojson = json.loads(
                (config.CUSTOM_AREAS / "popular.geojson").read_text()
            )
            with open(config.HEAT_PKL, "rb") as handle:
                cached = pickle.load(handle)

    own = heat._track_cells(
        [(50.8 + index * 0.0001, 3.7) for index in range(10)]
    )
    assert [feature["id"] for feature in geojson["features"]] == [
        "popular",
        "popular_trail",
    ]
    assert cached["cells"] == own | {bike_cell}
    assert cached["trail_cells"] == own | {walk_cell}
    assert result["trail_cellen"] == len(own | {walk_cell})


def test_build_without_walking_data_keeps_single_popular_area():
    bike_cell = heat.geo.cell(50.82, 3.72)
    with tempfile.TemporaryDirectory() as temp_dir:
        with _isolated_home(Path(temp_dir)):
            config.ensure_dirs()
            with open(config.VLAANDEREN_ROUTES_PKL, "wb") as handle:
                pickle.dump({"fiets": {bike_cell}, "wandel": set()}, handle)
            heat.build()
            geojson = json.loads(
                (config.CUSTOM_AREAS / "popular.geojson").read_text()
            )
            with open(config.HEAT_PKL, "rb") as handle:
                cached = pickle.load(handle)

    assert [feature["id"] for feature in geojson["features"]] == ["popular"]
    assert cached["trail_cells"] == set()
