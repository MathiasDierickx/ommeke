"""Pure tests voor atomaire draftopslag en optimistic concurrency."""

import os
import tempfile
from contextlib import contextmanager
from pathlib import Path

from lusmaker import config, draft


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


def test_save_is_atomic_increments_revision_and_rejects_stale_writer():
    with tempfile.TemporaryDirectory() as temp_dir:
        with _isolated_home(Path(temp_dir)):
            d = draft.new(
                start={"lat": 50.0, "lon": 4.0, "label": "Start"},
                name="revisietest",
                loop=True,
                end=None,
            )
            assert d["revision"] == 1

            draft.save(d, expected_revision=1)
            assert d["revision"] == 2
            assert draft.load(d["id"])["revision"] == 2
            assert list(config.DRAFTS.glob("*.tmp")) == []
            assert list(config.DRAFTS.glob(".*.tmp")) == []

            stale = dict(d)
            draft.save(d, expected_revision=2)
            try:
                draft.save(stale, expected_revision=2)
            except draft.DraftError as exc:
                assert "verwachte revisie 2" in str(exc)
                assert "huidige revisie 3" in str(exc)
            else:
                raise AssertionError("verouderde writer werd niet afgewezen")


def test_find_by_request_id_returns_original_draft():
    with tempfile.TemporaryDirectory() as temp_dir:
        with _isolated_home(Path(temp_dir)):
            d = draft.new(
                start={"lat": 50.0, "lon": 4.0, "label": "Start"},
                name="retrytest",
                loop=True,
                end=None,
            )
            d["route_request"] = {"request_id": "route-2026-08-08"}
            draft.save(d)

            found = draft.find_by_request_id("route-2026-08-08")
            missing = draft.find_by_request_id("bestaat-niet")

    assert found["id"] == d["id"]
    assert missing is None
