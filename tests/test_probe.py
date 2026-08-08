"""Pure tests voor de gecachete terreinprobe."""

import os
import pickle
import tempfile
from contextlib import contextmanager
from pathlib import Path

from lusmaker import config, draft, geo


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


def _climb_db():
    return {
        "dichtbij": {
            "id": "dichtbij",
            "name": "Dichtbijklim",
            "town": "Testdorp",
            "length_m": 300,
            "gain_m": 30,
            "avg_pct": 10.0,
            "max_pct": 12.0,
            "warnings": [],
            "foot": [50.001, 4.002],
            "mid": [50.0015, 4.003],
            "top": [50.002, 4.004],
            "geom": [[50.001, 4.002], [50.0015, 4.003], [50.002, 4.004]],
        }
    }


def _mark_cached(d):
    d["computed"] = {"total_km": 1.0}
    d["_geometry"] = [[[50.0, 4.0, 0], [50.0, 4.01, 0]]]
    d["_probe"] = {"cached": True}
    draft.save(d)


def test_probe_routes_once_uses_prefilter_and_caches_result():
    calls = []

    def router(points, **_kwargs):
        calls.append(points)
        coords = [(point[0], point[1], 10 + index * 10) for index, point in enumerate(points)]
        return {
            "distance_m": geo.path_length(points),
            "ascend_m": 20,
            "descend_m": 5,
            "coords": coords,
            "details": {
                "surface": [[0, len(coords) - 1, "concrete"]],
                "road_class": [[0, len(coords) - 1, "track"]],
            },
        }

    with tempfile.TemporaryDirectory() as temp_dir:
        with _isolated_home(Path(temp_dir)):
            d = draft.new(
                start={"lat": 50.0, "lon": 4.0, "label": "Start"},
                name="probe",
                loop=False,
                end={"lat": 50.0, "lon": 4.01, "label": "Einde"},
            )
            first = draft.probe(d, _climb_db(), router=router)
            second = draft.probe(d, _climb_db(), router=router)
            stored = draft.load(d["id"])

    assert len(calls) == 1
    assert first == second == stored["_probe"]
    assert first["km"] > 0
    assert first["kwaliteit"]["beton_m"] > 0
    assert first["terrein"]["beton_m"] == first["kwaliteit"]["beton_m"]
    assert first["terrein"]["offroad_beschikbaar_pct"] == 100.0
    assert first["terrein"]["klimmen_binnen_5km"] == 1


def test_probe_empty_loop_uses_exploratory_round_trip_without_mutating_route():
    round_trip_calls = []

    def unexpected_router(*_args, **_kwargs):
        raise AssertionError("een lege lus mag niet als start-naar-start gerouteerd worden")

    def round_trip_fn(anchor, distance_m, seed, **preferences):
        round_trip_calls.append((anchor, distance_m, seed, preferences))
        coords = [
            [50.0, 4.0, 10],
            [50.01, 4.04, 30],
            [50.02, 4.0, 20],
            [50.0, 4.0, 10],
        ]
        return {
            "distance_m": 14_800,
            "ascend_m": 120,
            "descend_m": 120,
            "coords": coords,
            "details": {
                "surface": [[0, len(coords) - 1, "concrete"]],
                "road_class": [[0, len(coords) - 1, "track"]],
            },
        }

    with tempfile.TemporaryDirectory() as temp_dir:
        with _isolated_home(Path(temp_dir)):
            d = draft.new(
                start={"lat": 50.0, "lon": 4.0, "label": "Start"},
                name="lege-lus-probe",
                loop=True,
                end=None,
            )
            result = draft.probe(
                d,
                _climb_db(),
                router=unexpected_router,
                round_trip_fn=round_trip_fn,
            )
            stored = draft.load(d["id"])

    assert len(round_trip_calls) == 1
    anchor, distance_m, seed, preferences = round_trip_calls[0]
    assert anchor == (50.0, 4.0)
    assert distance_m == 15_000
    assert seed == 0
    assert preferences["details"] is True
    assert result["km"] == 14.8
    assert result["hm"] == 120
    assert result["kwaliteit"]["beton_m"] > 0
    assert stored["computed"] is None
    assert "_geometry" not in stored
    assert stored["_probe"] == result


def test_route_mutations_invalidate_probe_cache():
    with tempfile.TemporaryDirectory() as temp_dir:
        with _isolated_home(Path(temp_dir)):
            config.ensure_dirs()
            with open(config.GAZETTEER_PKL, "wb") as handle:
                pickle.dump(
                    {
                        "places": [("Testdorp", "village", 50.0, 4.005)],
                        "streets": {},
                    },
                    handle,
                )
            d = draft.new(
                start={"lat": 50.0, "lon": 4.0, "label": "Start"},
                name="invalidate",
                loop=False,
                end={"lat": 50.0, "lon": 4.01, "label": "Einde"},
            )

            _mark_cached(d)
            draft.add_climb(d["id"], "dichtbij", climb_db=_climb_db())
            assert "_probe" not in draft.load(d["id"])

            d = draft.load(d["id"])
            _mark_cached(d)
            draft.remove_climb(d["id"], "dichtbij")
            assert "_probe" not in draft.load(d["id"])

            d = draft.load(d["id"])
            _mark_cached(d)
            draft.avoid_place(d["id"], "Testdorp")
            assert "_probe" not in draft.load(d["id"])

            d = draft.load(d["id"])
            _mark_cached(d)
            draft.unavoid_place(d["id"], "Testdorp")
            assert "_probe" not in draft.load(d["id"])
