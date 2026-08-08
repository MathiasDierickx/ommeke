"""Offline cassette-replay van de drie canonieke routes."""
import copy
import os
import tempfile
from contextlib import contextmanager
from pathlib import Path
from unittest import SkipTest

from lusmaker import draft, gh
from lusmaker.recording import ReplayPost
from tests.regression_support import (
    fixture_path,
    invariant_failures,
    load_fixture,
)


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


def _replay(name: str):
    path = fixture_path(name)
    if not path.exists():
        raise SkipTest(f"{path.name} ontbreekt; neem hem op met tests/record_fixtures.py")
    fixture = load_fixture(name)
    scenario_draft = copy.deepcopy(fixture["draft"])
    replay = ReplayPost(fixture)
    with tempfile.TemporaryDirectory() as temp_dir:
        with _isolated_home(Path(temp_dir)):
            def offline_route(points, **kwargs):
                # Replay is volledig offline: er is bewust geen /info-call en
                # dus geen capability voor nieuw ingebakken TVL-areas.
                return gh.route(points, area_evs=set(), **kwargs)

            draft.route(
                scenario_draft,
                copy.deepcopy(fixture["climbs"]),
                router=offline_route,
                post_fn=replay,
            )
    failures = invariant_failures(name, scenario_draft)
    assert not failures, f"{name}: {'; '.join(failures)}"
    assert not replay.unused_hashes, (
        f"{name}: {len(replay.unused_hashes)} cassette-responses niet gebruikt; "
        "engine-gedrag gewijzigd"
    )


def test_berendries_quiet():
    _replay("berendries_quiet")


def test_trail_offroad():
    _replay("trail_offroad")


def test_zottegem_avoid():
    _replay("zottegem_avoid")
