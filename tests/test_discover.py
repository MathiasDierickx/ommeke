"""Pure tests voor globale plaats- en Geofabrik-resolutie."""

import json
import os
import tempfile
from pathlib import Path

from lusmaker import discover, geo


def _feature(slug, parent, coordinates, size=10_000_000):
    return {
        "type": "Feature",
        "properties": {
            "id": slug,
            "name": slug.title(),
            "parent": parent,
            "pbf_size_bytes": size,
            "urls": {
                "pbf": (
                    f"https://download.geofabrik.de/europe/"
                    f"{slug}-latest.osm.pbf"
                )
            },
        },
        "geometry": {"type": "Polygon", "coordinates": [coordinates]},
    }


def _mini_index():
    outer = [[0, 0], [10, 0], [10, 10], [0, 10], [0, 0]]
    inner = [[2, 2], [4, 2], [4, 4], [2, 4], [2, 2]]
    return {
        "type": "FeatureCollection",
        "features": [
            _feature("outer", None, outer),
            _feature("inner", "outer", inner),
        ],
    }


def test_point_in_polygon_handles_boundary_and_holes():
    polygon = [
        [[0, 0], [10, 0], [10, 10], [0, 10], [0, 0]],
        [[4, 4], [6, 4], [6, 6], [4, 6], [4, 4]],
    ]
    assert geo.point_in_polygon(2, 2, polygon)
    assert geo.point_in_polygon(0, 5, polygon)
    assert not geo.point_in_polygon(5, 5, polygon)
    assert not geo.point_in_polygon(12, 2, polygon)


def test_region_slug_for_selects_deepest_nested_feature():
    result = discover.region_slug_for(
        3,
        3,
        index=_mini_index(),
        size_fetch=None,
    )
    assert result == {
        "slug": "inner",
        "pbf_url": (
            "https://download.geofabrik.de/europe/inner-latest.osm.pbf"
        ),
        "bbox": [2.0, 2.0, 4.0, 4.0],
    }

    assert discover.region_slug_for(
        8, 8, index=_mini_index(), size_fetch=None
    )["slug"] == "outer"


def test_region_size_limit_gives_subregion_advice():
    index = _mini_index()
    index["features"][1]["properties"]["pbf_size_bytes"] = 701_000_000
    previous = os.environ.pop("LUSMAKER_MAX_PBF_MB", None)
    try:
        try:
            discover.region_slug_for(3, 3, index=index, size_fetch=None)
        except RuntimeError as exc:
            assert "kleinere subregio" in str(exc)
            assert "700 MB" in str(exc)
        else:
            raise AssertionError("te groot PBF werd aanvaard")
    finally:
        if previous is not None:
            os.environ["LUSMAKER_MAX_PBF_MB"] = previous


def test_nominatim_result_is_cached_without_second_fetch():
    with tempfile.TemporaryDirectory() as temp_dir:
        home = Path(temp_dir)
        calls = []

        def fetch(url, headers):
            calls.append((url, headers))
            return [
                {
                    "lat": "51.731",
                    "lon": "3.775",
                    "display_name": "Renesse, Nederland",
                    "address": {"country": "Nederland"},
                }
            ]

        first = discover.find_place(
            "Renesse", home=home, fetch=fetch, clock=lambda: 10
        )
        second = discover.find_place(
            "renesse",
            home=home,
            fetch=lambda *_args: (_ for _ in ()).throw(
                AssertionError("cache-miss")
            ),
        )

        assert first == second
        assert first["country"] == "Nederland"
        assert len(calls) == 1
        assert "format=jsonv2" in calls[0][0]
        assert "limit=3" in calls[0][0]
        assert calls[0][1]["User-Agent"] == "lusmaker/0.1"
        cache = json.loads(
            (home / "cache" / "nominatim.json").read_text(encoding="utf-8")
        )
        assert cache["renesse"] == first
