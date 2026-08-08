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
        return MINI_LINES if "traject_fiets" in layer else {
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
    assert cached["version"] == heat.VLAANDEREN_CACHE_VERSION
    assert cached["fiets"] == expected
    assert cached["wandel"] == set()
    assert cached["wegdek"] == {}
    assert cached["druk"] == set()
    assert cached["knopen"] == []
    assert set(cached["pois"]) == set(heat.VLAANDEREN_POI_LAYERS)
    assert all(not points for points in cached["pois"].values())
    assert result["fiets_cellen"] == len(expected)
    assert result["wandel_cellen"] == 0
    assert len(calls) == 17
    for url in calls:
        query = parse_qs(urlparse(url).query)
        assert query["bbox"] == ["3.35,50.68,4.2,51.1,EPSG:4326"]
        assert query["outputFormat"] == ["application/json"]


def test_fetch_vlaanderen_parses_surface_traffic_poi_and_knot_layers():
    def collection(*features):
        return {"type": "FeatureCollection", "features": list(features)}

    def line(properties, lon=3.7, lat=50.8):
        return {
            "type": "Feature",
            "geometry": {
                "type": "LineString",
                "coordinates": [[lon, lat], [lon + 0.002, lat]],
            },
            "properties": properties,
        }

    def point(properties, lon=3.7, lat=50.8):
        return {
            "type": "Feature",
            "geometry": {"type": "Point", "coordinates": [lon, lat]},
            "properties": properties,
        }

    def fetcher(url):
        layer = parse_qs(urlparse(url).query)["typeNames"][0]
        if layer == "routes:wegdek_fiets":
            return collection(
                line({"ground": "Kassei"}),
                line({"ground": "  halfverhard  "}, lat=50.81),
                line({"ground": ""}, lat=50.82),
                line({"ground": None}, lat=50.83),
            )
        if layer == "routes:wegdek_wandel":
            return collection(line({"ground": "onverhard"}, lat=50.84))
        if layer == "routes:verkeersintensiteit_fiets":
            return collection(
                line({"traffic": "niet-autovrij"}, lat=50.85),
                line({"traffic": ""}, lat=50.86),
            )
        if layer == "poi:picknickbank":
            return collection(
                point({"naam": "Bank aan <de beek>"}, lon=3.71, lat=50.87),
                point({"naam": "buiten bbox"}, lon=5.0, lat=50.87),
            )
        if layer == "routes:knoop_fiets":
            return collection(
                point({"knoopnr": 42}, lon=3.72, lat=50.88),
                point({"knoopnr": -9999}, lon=3.73, lat=50.88),
            )
        if layer == "routes:knoop_wandel":
            return collection(point({"knoopnr": "7"}, lon=3.74, lat=50.89))
        return collection()

    with tempfile.TemporaryDirectory() as temp_dir:
        with _isolated_home(Path(temp_dir)):
            result = heat.fetch_vlaanderen(fetcher=fetcher)
            with open(config.VLAANDEREN_ROUTES_PKL, "rb") as handle:
                cached = pickle.load(handle)

    assert set(cached["wegdek"]) == {"kassei", "halfverhard", "onverhard"}
    assert cached["wegdek"]["kassei"] == heat._track_cells(
        [(50.8, 3.7), (50.8, 3.702)]
    )
    assert cached["druk"] == heat._track_cells(
        [(50.85, 3.7), (50.85, 3.702)]
    )
    assert cached["pois"]["picknickbank"] == [
        (50.87, 3.71, "Bank aan <de beek>")
    ]
    assert cached["knopen"] == [
        (50.88, 3.72, 42, "fiets"),
        (50.89, 3.74, 7, "wandel"),
    ]
    assert result["wegdek_cellen"]["halfverhard"] > 0
    assert result["druk_cellen"] > 0
    assert result["pois"]["picknickbank"] == 1
    assert result["knopen"] == 2


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


def test_features_near_route_applies_distances_and_global_poi_cap():
    route = [(50.0, 4.0), (50.0, 4.1)]
    pois = [
        (50.0, 4.001 + index * 0.001, f"bank {index}")
        for index in range(45)
    ]
    pois.extend(
        [
            (50.0008, 4.06, "nabij"),
            (50.003, 4.06, "te ver"),
        ]
    )
    knots = [
        (50.0005, 4.05, 12, "fiets"),
        (50.0012, 4.05, 13, "fiets"),
    ]

    with tempfile.TemporaryDirectory() as temp_dir:
        with _isolated_home(Path(temp_dir)):
            config.ensure_dirs()
            with open(config.VLAANDEREN_ROUTES_PKL, "wb") as handle:
                pickle.dump(
                    {
                        "version": 2,
                        "pois": {"picknickbank": pois},
                        "knopen": knots,
                    },
                    handle,
                )
            capped = heat.features_near_route(route, max_pois=40)
            uncapped = heat.features_near_route(route)

    assert len(capped["pois"]) == 40
    assert len(uncapped["pois"]) == 46
    assert all(poi["naam"] != "te ver" for poi in uncapped["pois"])
    assert [knot["nummer"] for knot in uncapped["knopen"]] == [12]
