"""Pure tests voor fiets- en trailprofielen."""

import json
import os
import tempfile
from contextlib import contextmanager
from pathlib import Path

from lusmaker import cli, config, draft, gh, gh_config, profiles


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
        area_evs=set(),
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
        area_evs=set(),
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


def test_write_gh_files_adds_rules_only_for_respective_custom_areas():
    with tempfile.TemporaryDirectory() as temp_dir:
        with _isolated_home(Path(temp_dir)):
            config.ensure_dirs()
            areas = {
                "type": "FeatureCollection",
                "features": [
                    {"type": "Feature", "id": "popular"},
                    {"type": "Feature", "id": "popular_trail"},
                ],
            }
            (config.CUSTOM_AREAS / "popular.geojson").write_text(
                json.dumps(areas), encoding="utf-8"
            )
            files = gh_config.write_gh_files()
            quiet = json.loads(Path(files[1]).read_text(encoding="utf-8"))
            trail = json.loads(Path(files[2]).read_text(encoding="utf-8"))

    assert quiet["priority"][-1] == gh_config.POPULAR_RULE
    assert trail["priority"][-1] == gh_config.POPULAR_TRAIL_RULE


def test_write_gh_files_keeps_trail_rule_off_for_popular_only():
    with tempfile.TemporaryDirectory() as temp_dir:
        with _isolated_home(Path(temp_dir)):
            config.ensure_dirs()
            areas = {
                "type": "FeatureCollection",
                "features": [{"type": "Feature", "id": "popular"}],
            }
            (config.CUSTOM_AREAS / "popular.geojson").write_text(
                json.dumps(areas), encoding="utf-8"
            )
            files = gh_config.write_gh_files()
            trail = json.loads(Path(files[2]).read_text(encoding="utf-8"))

    assert trail == gh_config.TRAIL_MODEL


def test_preference_profile_load_default_and_list_only_saved_documents():
    with tempfile.TemporaryDirectory() as temp_dir:
        with _isolated_home(Path(temp_dir)):
            default = profiles.load("toerist")
            before = profiles.list_all()
            profiles.save(default)
            after = profiles.list_all()

    assert default["naam"] == "toerist"
    assert default["gewichten"] == {
        "hoogtemeters": 1.0,
        "offroad": 0.0,
        "populair": 0.0,
        "kort": 0.0,
    }
    assert default["voorkeuren"]["kasseien"] is None
    assert before == []
    assert [profile["naam"] for profile in after] == ["toerist"]


def test_preference_profile_patch_records_history_and_normalizes_weights():
    with tempfile.TemporaryDirectory() as temp_dir:
        with _isolated_home(Path(temp_dir)):
            updated = profiles.apply_patch(
                "gravel",
                {
                    "gewichten": {"hoogtemeters": 2, "offroad": 2},
                    "voorkeuren": {"kasseien": "graag"},
                },
                bron="test",
            )
            stored = profiles.load("gravel")

    assert updated == stored
    assert stored["gewichten"]["hoogtemeters"] == 0.5
    assert stored["gewichten"]["offroad"] == 0.5
    assert len(stored["historiek"]) == 1
    assert stored["historiek"][0]["bron"] == "test"
    assert stored["historiek"][0]["patch"]["voorkeuren"]["kasseien"] == "graag"
    assert stored["historiek"][0]["timestamp"]


def test_profile_patch_invalidates_computed_route_and_probe_on_linked_drafts():
    with tempfile.TemporaryDirectory() as temp_dir:
        with _isolated_home(Path(temp_dir)):
            d = draft.new(
                start={"lat": 50.98, "lon": 3.87, "label": "Wetteren"},
                name="profielcache",
                loop=True,
                end=None,
                profile_doc="gravel",
            )
            d["computed"] = {"total_km": 12.3}
            d["_geometry"] = [[[50.98, 3.87, 10], [50.99, 3.88, 20]]]
            d["_probe"] = {"km": 12.3}
            draft.save(d)

            profiles.apply_patch(
                "gravel",
                {"voorkeuren": {"kasseien": "vermijd"}},
                bron="test",
            )
            stored = draft.load(d["id"])

    assert stored["computed"] is None
    assert "_geometry" not in stored
    assert "_probe" not in stored


def test_preference_validation_and_routing_mapping_keep_graag_scoring_only():
    profile = profiles.default_document("trailfan")
    profile["activiteit"] = "trail"
    profile["voorkeuren"].update(
        {"kasseien": "graag", "beton": "vermijd", "steenwegen": "vermijd"}
    )

    assert profiles.routing_prefs(profile) == {
        "avoid_cobbles": False,
        "avoid_concrete": True,
        "strict": True,
        "profile": "trail",
    }

    profile["voorkeuren"]["steenwegen"] = "graag"
    try:
        profiles.routing_prefs(profile)
    except profiles.ProfileError as exc:
        assert "steenwegen ondersteunt 'graag' niet" in str(exc)
    else:
        raise AssertionError("ongeldige steenwegvoorkeur werd aanvaard")


def test_draft_profile_preferences_apply_and_explicit_true_flags_override():
    with tempfile.TemporaryDirectory() as temp_dir:
        with _isolated_home(Path(temp_dir)):
            profiles.apply_patch(
                "trailfan",
                {
                    "activiteit": "trail",
                    "voorkeuren": {"beton": "vermijd"},
                },
                bron="test",
            )
            d = draft.new(
                start={"lat": 50.98, "lon": 3.87, "label": "Wetteren"},
                name="profieltest",
                loop=True,
                end=None,
                strict=True,
                profile_doc="trailfan",
            )
            effective = draft.routing_preferences(d)

    assert d["profile_doc"] == "trailfan"
    assert d["profile"] == "trail"
    assert effective == {
        "profile": "trail",
        "strict": True,
        "avoid_cobbles": False,
        "avoid_concrete": True,
    }


def test_cli_weight_parser_accepts_ratios_and_rejects_bad_input():
    assert cli.parse_weights("hoogtemeters=0.5, offroad=1.5") == {
        "hoogtemeters": 0.5,
        "offroad": 1.5,
        "populair": 0.0,
        "kort": 0.0,
    }
    for value in ("hoogtemeters", "onbekend=1", "offroad=veel"):
        try:
            cli.parse_weights(value)
        except ValueError:
            pass
        else:
            raise AssertionError(f"ongeldige gewichten werden aanvaard: {value}")
