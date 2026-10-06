"""Offline tests voor de bbox-afleiding uit de Vlaanderen-grens (fixturepolygoon)."""
import json
import tempfile
from pathlib import Path

from lusmaker import boundary, config, regions

# Grof fixturepolygoon (lon,lat) met een gat en een exclave; geen echte grens.
FIXTURE = {
    "type": "Feature",
    "properties": {},
    "geometry": {
        "type": "MultiPolygon",
        "coordinates": [
            [
                [[2.5, 51.0], [3.0, 51.4], [5.9, 51.2], [5.5, 50.7],
                 [4.0, 50.75], [2.9, 50.7], [2.5, 51.0]],
                [[4.3, 50.8], [4.5, 50.8], [4.5, 50.95], [4.3, 50.8]],
            ],
            [[[4.9, 51.45], [5.0, 51.45], [5.0, 51.5], [4.9, 51.45]]],
        ],
    },
}


def test_raw_bbox_covers_all_rings():
    assert boundary.raw_bbox(FIXTURE) == (50.7, 2.5, 51.5, 5.9)


def test_buffered_bbox_adds_buffer_and_is_valid():
    raw = boundary.raw_bbox(FIXTURE)
    box = boundary.buffered_bbox(FIXTURE, buffer_km=2.0)
    assert box[0] < raw[0] and box[1] < raw[1] and box[2] > raw[2] and box[3] > raw[3]
    assert abs((raw[0] - box[0]) * 111.32 - 2.0) < 0.05
    assert boundary.buffered_bbox(FIXTURE, 0) == raw
    assert config._validate_bbox(box) == box


def test_bbox_accepts_featurecollection_and_bare_geometry():
    fc = {"type": "FeatureCollection", "features": [FIXTURE]}
    assert boundary.raw_bbox(fc) == boundary.raw_bbox(FIXTURE["geometry"])
    assert boundary.raw_bbox(fc) == (50.7, 2.5, 51.5, 5.9)


def test_missing_boundary_file_gives_clear_error():
    with tempfile.TemporaryDirectory() as temp:
        missing = Path(temp) / "nope.geojson"
        assert boundary.load_boundary(missing) is None
        try:
            boundary.flanders_bbox(missing)
        except ValueError as exc:
            assert "flanders_boundary.py" in str(exc)
        else:
            raise AssertionError("verwachtte ValueError")


def test_resolve_bbox_token_and_explicit_value():
    with tempfile.TemporaryDirectory() as temp:
        path = Path(temp) / "b.geojson"
        path.write_text(json.dumps(FIXTURE), encoding="utf-8")
        assert boundary.resolve_bbox("boundary", path) == boundary.buffered_bbox(FIXTURE)
    assert boundary.resolve_bbox("50.68,3.35,51.10,4.20") == (50.68, 3.35, 51.1, 4.2)
    try:
        boundary.resolve_bbox("onzin")
    except ValueError as exc:
        assert "minlat" in str(exc)
    else:
        raise AssertionError("verwachtte ValueError")


def test_regions_parse_bbox_keeps_explicit_behaviour():
    assert regions.parse_bbox("50.68,3.35,51.10,4.20") == config.LEGACY_BBOX


def test_simplify_keeps_bbox_and_reduces_points():
    ring = [[3.0 + i * 0.01, 51.0 + (0.0001 if i % 2 else 0)] for i in range(101)]
    ring += [[4.0, 50.5], [3.0, 50.5], [3.0, 51.0]]
    poly = {"type": "Polygon", "coordinates": [ring]}
    simple = boundary.simplify_geojson(poly, tolerance=0.005)
    out = simple["geometry"]["coordinates"][0][0]
    assert len(out) < len(ring) // 4
    assert out[0] == out[-1]
    assert boundary.raw_bbox(simple)[:2] == (50.5, 3.0)
    assert boundary.raw_bbox(simple)[3] >= 4.0


def test_simplify_drops_degenerate_rings():
    poly = {"type": "Polygon", "coordinates": [[[0, 0], [1, 0], [0, 0]]]}
    try:
        boundary.simplify_geojson(poly)
    except ValueError:
        return
    raise AssertionError("verwachtte ValueError")


def test_committed_boundary_if_present_covers_legacy_bbox():
    geojson = boundary.load_boundary()
    if geojson is None:
        return  # eenmalige fetch (scripts/flanders_boundary.py) nog niet gedaan
    box = boundary.flanders_bbox()
    legacy = config.LEGACY_BBOX
    assert box[0] <= legacy[0] and box[1] <= legacy[1]
    assert box[2] >= legacy[2] and box[3] >= legacy[3]
