"""Pure tests voor fiets- en trailprofielen."""

import json
import os
import tempfile
from contextlib import contextmanager
from pathlib import Path

from lusmaker import config, draft, gh, gh_config


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


def test_gh_route_posts_selected_profile():
    captured = {}

    def post(path, body):
        captured["path"] = path
        captured["body"] = body
        return {
            "paths": [
                {
                    "distance": 1234,
                    "time": 456000,
                    "ascend": 12,
                    "descend": 10,
                    "points": {
                        "coordinates": [[3.87, 50.98, 10], [3.88, 50.99, 22]]
                    },
                }
            ]
        }

    result = gh.route(
        [(50.98, 3.87), (50.99, 3.88)],
        profile="trail",
        post_fn=post,
    )

    assert captured["path"] == "/route"
    assert captured["body"]["profile"] == "trail"
    assert result["distance_m"] == 1234


def test_gh_round_trip_posts_algorithm_distance_seed_and_preferences():
    captured = {}

    def post(path, body):
        captured["path"] = path
        captured["body"] = body
        return {
            "paths": [
                {
                    "distance": 4800,
                    "time": 900000,
                    "ascend": 35,
                    "descend": 35,
                    "points": {
                        "coordinates": [[3.87, 50.98, 10], [3.87, 50.98, 10]]
                    },
                }
            ]
        }

    gh.round_trip(
        (50.98, 3.87),
        5000,
        3,
        profile="trail",
        strict=True,
        avoid_cobbles=True,
        post_fn=post,
    )

    body = captured["body"]
    assert captured["path"] == "/route"
    assert body["points"] == [[3.87, 50.98]]
    assert body["profile"] == "trail"
    assert body["algorithm"] == "round_trip"
    assert body["round_trip.distance"] == 5000
    assert body["round_trip.seed"] == 3
    # strict (4) + kasseien (1) + trail-offroadboost (4)
    assert len(body["custom_model"]["priority"]) == 9


def test_new_draft_stores_and_routes_with_profile():
    with tempfile.TemporaryDirectory() as temp_dir:
        with _isolated_home(Path(temp_dir)):
            d = draft.new(
                start={"lat": 50.98, "lon": 3.87, "label": "Wetteren"},
                name="trailtest",
                loop=True,
                end=None,
                profile="trail",
            )
            calls = []

            def router(_points, **kwargs):
                calls.append(kwargs)
                return {
                    "distance_m": 1000,
                    "ascend_m": 20,
                    "descend_m": 20,
                    "coords": [
                        (50.98, 3.87, 10),
                        (50.981, 3.871, 30),
                    ],
                    "details": {},
                }

            result = draft.route(d, {}, router=router)
            stored = draft.load(d["id"])

    assert d["profile"] == "trail"
    assert result["profile"] == "trail"
    assert stored["profile"] == "trail"
    assert calls
    assert all(call["profile"] == "trail" for call in calls)


def test_write_gh_files_adds_trail_profile_and_model():
    with tempfile.TemporaryDirectory() as temp_dir:
        with _isolated_home(Path(temp_dir)):
            files = gh_config.write_gh_files()
            generated = [Path(path) for path in files]
            config_yml = generated[0].read_text(encoding="utf-8")
            trail = json.loads(generated[2].read_text(encoding="utf-8"))

    assert "foot_access, foot_priority, foot_average_speed" in config_yml
    assert "name: trail" in config_yml
    assert "custom_model_files: [foot.json, trail.json]" in config_yml
    assert generated[2].name == "trail.json"
    assert trail == gh_config.TRAIL_MODEL
    assert all(
        "in_popular" not in rule.get("if", rule.get("else_if", ""))
        for rule in trail["priority"]
    )
