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
