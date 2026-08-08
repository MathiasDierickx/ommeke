"""Pure tests voor route-kwaliteitsmetrieken."""

import os
import pickle
import tempfile
from contextlib import contextmanager
from pathlib import Path

from lusmaker import analysis, config, geo


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


def test_concrete_surface_classes_are_measured_separately_from_cobbles():
    coords = [
        [50.0, 4.0, 0],
        [50.001, 4.0, 0],
        [50.002, 4.0, 0],
        [50.003, 4.0, 0],
    ]
    details = [
        [0, 1, "concrete"],
        [1, 2, "concrete:plates"],
        [2, 3, "cobblestone"],
    ]

    concrete_m = analysis.detail_meters(
        coords, details, analysis.CONCRETE_SURFACES
    )
    cobble_m = analysis.detail_meters(coords, details, analysis.COBBLE_SURFACES)

    assert 220 < concrete_m < 223
    assert 110 < cobble_m < 112


def test_route_stats_selects_profile_cells_and_trail_falls_back_to_popular():
    geometry = [[[50.0, 4.0, 0], [50.001, 4.0, 0]]]
    route_points = geo.resample([(50.0, 4.0), (50.001, 4.0)], 60.0)
    bike_cells = {geo.cell(*point) for point in route_points}
    unrelated_trail_cells = {geo.cell(50.1, 4.1)}

    with tempfile.TemporaryDirectory() as temp_dir:
        with _isolated_home(Path(temp_dir)):
            config.ensure_dirs()
            with open(config.HEAT_PKL, "wb") as handle:
                pickle.dump(
                    {
                        "cells": bike_cells,
                        "trail_cells": unrelated_trail_cells,
                    },
                    handle,
                )
            quiet = analysis.route_stats(geometry, [{}], profile="quiet")
            trail = analysis.route_stats(geometry, [{}], profile="trail")

            with open(config.HEAT_PKL, "wb") as handle:
                pickle.dump({"cells": bike_cells, "trail_cells": set()}, handle)
            fallback = analysis.route_stats(geometry, [{}], profile="trail")

    assert quiet["populair_pct"] == 100.0
    assert trail["populair_pct"] == 0.0
    assert fallback["populair_pct"] == 100.0


def test_route_stats_uses_vlaanderen_surface_only_for_missing_gh_segments():
    coords = [
        [50.0, 4.000, 0],
        [50.0, 4.002, 0],
        [50.0, 4.004, 0],
        [50.0, 4.006, 0],
        [50.0, 4.008, 0],
    ]
    cobble_cells = {geo.cell(*coords[index][:2]) for index in (0, 1)}
    unpaved_cells = {geo.cell(*coords[index][:2]) for index in (2, 3)}
    details = {
        "surface": [[0, 4, "missing"]],
        # Het laatste segment is al offroad en mag niet dubbel tellen.
        "road_class": [[0, 3, "residential"], [3, 4, "track"]],
    }

    with tempfile.TemporaryDirectory() as temp_dir:
        with _isolated_home(Path(temp_dir)):
            config.ensure_dirs()
            with open(config.VLAANDEREN_ROUTES_PKL, "wb") as handle:
                pickle.dump(
                    {
                        "version": 2,
                        "fiets": set(),
                        "wandel": set(),
                        "wegdek": {
                            "kassei": cobble_cells,
                            "onverhard": unpaved_cells,
                        },
                    },
                    handle,
                )
            stats = analysis.route_stats([coords], [details])

    expected_cobble = sum(
        geo.haversine(*coords[index][:2], *coords[index + 1][:2])
        for index in (0, 1)
    )
    expected_unpaved = sum(
        geo.haversine(*coords[index][:2], *coords[index + 1][:2])
        for index in (2, 3)
    )
    assert stats["kassei_m"] == round(expected_cobble)
    assert stats["onverhard_m"] == round(expected_unpaved)


def test_route_stats_autovrij_uses_only_route_points_with_network_coverage():
    coords = [[50.0, 4.000 + index * 0.002, 0] for index in range(5)]
    route_points = [(point[0], point[1]) for point in coords]
    network_cells = {geo.cell(*point) for point in route_points[:-2]}
    busy_cells = {geo.cell(*route_points[1])}

    with tempfile.TemporaryDirectory() as temp_dir:
        with _isolated_home(Path(temp_dir)):
            config.ensure_dirs()
            with open(config.VLAANDEREN_ROUTES_PKL, "wb") as handle:
                pickle.dump(
                    {
                        "version": 2,
                        "fiets": network_cells,
                        "wandel": set(),
                        "druk": busy_cells,
                    },
                    handle,
                )
            covered = analysis.route_stats([coords], [{}])

            with open(config.VLAANDEREN_ROUTES_PKL, "wb") as handle:
                pickle.dump(
                    {"version": 2, "fiets": set(), "wandel": set()}, handle
                )
            uncovered = analysis.route_stats([coords], [{}])

    covered_points = [
        point for point in route_points if geo.cell(*point) in network_cells
    ]
    expected_free = sum(
        1 for point in covered_points if geo.cell(*point) not in busy_cells
    )
    assert covered["autovrij_pct"] == round(
        expected_free / len(covered_points) * 100, 1
    )
    assert "autovrij_pct" not in uncovered


def test_route_stats_without_vlaanderen_cache_keeps_cassette_metrics_cacheless():
    """Regressiecassettes bevatten GH-details, maar geen Vlaanderen-cache."""
    coords = [[50.0, 4.0, 0], [50.001, 4.0, 0]]
    details = {
        "surface": [[0, 1, "missing"]],
        "road_class": [[0, 1, "residential"]],
    }

    with tempfile.TemporaryDirectory() as temp_dir:
        with _isolated_home(Path(temp_dir)):
            stats = analysis.route_stats([coords], [details])

    assert stats["kassei_m"] == 0
    assert stats["onverhard_m"] == 0
    assert "autovrij_pct" not in stats
