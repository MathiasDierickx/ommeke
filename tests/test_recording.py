"""Pure tests voor GraphHopper-cassettes en post_fn-doorgave."""
import json
import os
import tempfile
from contextlib import contextmanager
from pathlib import Path

from lusmaker import draft, gh
from lusmaker.recording import RecordingPost, ReplayPost, hash_body


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


def _gh_response():
    return {
        "paths": [
            {
                "distance": 1000,
                "time": 60000,
                "ascend": 20,
                "descend": 20,
                "points": {
                    "coordinates": [
                        [3.8700019, 50.9800019, 10.123456],
                        [3.8800019, 50.9900019, 30.123456],
                    ]
                },
                "details": {
                    "surface": [[0, 1, "asphalt"]],
                    "road_class": [[0, 1, "track"]],
                },
            }
        ]
    }


def test_hash_body_is_canonical():
    left = {"profile": "quiet", "points": [[3.87, 50.98]], "nested": {"b": 2, "a": 1}}
    right = {"nested": {"a": 1, "b": 2}, "points": [[3.87, 50.98]], "profile": "quiet"}

    assert hash_body(left) == hash_body(right)


def test_recording_rounds_coordinates_and_replay_returns_a_copy():
    recorder = RecordingPost(lambda _path, _body: _gh_response())
    body = {"points": [[3.87, 50.98]], "profile": "quiet"}

    recorded = recorder("/route", body)
    replay = ReplayPost({"responses": recorder.responses})
    first = replay("/route", body)
    first["paths"][0]["distance"] = 0
    second = replay("/route", body)

    assert recorded["paths"][0]["points"]["coordinates"][0] == [
        3.87,
        50.98,
        10.12346,
    ]
    assert second["paths"][0]["distance"] == 1000


def test_replay_unknown_request_explains_how_to_recover():
    try:
        ReplayPost({"responses": {}})("/route", {"profile": "quiet"})
    except gh.GhError as exc:
        message = str(exc)
    else:
        raise AssertionError("onbekende cassette-aanvraag had moeten falen")

    assert "engine-gedrag gewijzigd t.o.v. cassette" in message
    assert "tests/record_fixtures.py" in message


def test_draft_route_threads_post_fn_and_computes_cacheless_metrics():
    response = _gh_response()
    calls = []

    def post(path, body):
        calls.append((path, body))
        return json.loads(json.dumps(response))

    d = {
        "id": "postfn",
        "name": "post-fn-test",
        "start": {"lat": 50.98, "lon": 3.87, "label": "Wetteren"},
        "loop": True,
        "profile": "trail",
        "strict": False,
        "avoid_cobbles": False,
        "avoid_concrete": False,
        "avoid_places": [],
        "climbs": [],
        "opvullingen": [
            {
                "anchor": [50.98, 3.87],
                "label": "start",
                "points": [[50.98, 3.87], [50.99, 3.88], [50.98, 3.87]],
                "seed": 0,
            }
        ],
        "computed": None,
    }

    with tempfile.TemporaryDirectory() as temp_dir:
        with _isolated_home(Path(temp_dir)):
            result = draft.route(d, {}, router=gh.route, post_fn=post)

    assert calls and all(path == "/route" for path, _body in calls)
    assert result["computed"]["kwaliteit"]["offroad_pct"] > 0
    assert result["computed"]["kwaliteit"]["steenweg_kruisingen"] is None
