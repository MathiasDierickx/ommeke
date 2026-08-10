"""Pure tests voor de readiness-regels en hun patches."""

import os
import tempfile
from contextlib import contextmanager
from pathlib import Path

from lusmaker import profiles, readiness


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


def _draft(
    *,
    cobble=0,
    concrete=0,
    crossings=0,
    main_road=0,
    offroad=0,
    heat=None,
    walking_popularity=False,
    autovrij=None,
    busy_data=False,
    places=None,
):
    return {
        "id": "ready1",
        "start": {"label": "Start", "lat": 50.0, "lon": 4.0},
        "end": None,
        "avoid_places": [],
        "_probe": {
            "km": 20,
            "hm": 200,
            "kwaliteit": {
                "kassei_m": cobble,
                "beton_m": concrete,
                "steenweg_kruisingen": crossings,
                "steenweg_m": main_road,
                "offroad_pct": offroad,
            },
            "terrein": {
                "kassei_aanwezig_m": cobble,
                "beton_m": concrete,
                "offroad_beschikbaar_pct": offroad,
                "heat_dekking_pct": heat,
                "wandelpopulariteit_beschikbaar": walking_popularity,
                "autovrij_pct": autovrij,
                "druk_data_beschikbaar": busy_data,
                "plaatskernen": places or [],
            },
        },
    }


def _question_ids(result):
    return [question["id"] for question in result["vragen"]]


def test_cobble_rule_is_material_only_above_300_meter_and_when_unknown():
    profile = profiles.default_document()

    assert _question_ids(readiness.assess(_draft(cobble=301), profile, {})) == [
        "kasseien"
    ]
    assert _question_ids(readiness.assess(_draft(cobble=300), profile, {})) == []
    profile["voorkeuren"]["kasseien"] = "ok"
    assert _question_ids(readiness.assess(_draft(cobble=1800), profile, {})) == []


def test_concrete_rule_requires_cycling_more_than_one_kilometer_and_unknown():
    profile = profiles.default_document()

    assert _question_ids(readiness.assess(_draft(concrete=1001), profile, {})) == [
        "beton"
    ]
    assert _question_ids(readiness.assess(_draft(concrete=1000), profile, {})) == []
    profile["activiteit"] = "trail"
    assert _question_ids(readiness.assess(_draft(concrete=2000), profile, {})) == []
    profile["activiteit"] = "fietsen"
    profile["voorkeuren"]["beton"] = "vermijd"
    assert _question_ids(readiness.assess(_draft(concrete=2000), profile, {})) == []


def test_main_road_rule_uses_crossings_or_distance_threshold():
    profile = profiles.default_document()

    assert _question_ids(readiness.assess(_draft(crossings=9), profile, {})) == [
        "steenwegen"
    ]
    assert _question_ids(readiness.assess(_draft(main_road=1501), profile, {})) == [
        "steenwegen"
    ]
    assert _question_ids(
        readiness.assess(_draft(crossings=8, main_road=1500), profile, {})
    ) == []
    profile["voorkeuren"]["steenwegen"] = "ok"
    assert _question_ids(readiness.assess(_draft(crossings=20), profile, {})) == []


def test_autovrij_rule_requires_busy_data_low_share_and_unknown_preference():
    profile = profiles.default_document()

    result = readiness.assess(
        _draft(autovrij=39.9, busy_data=True), profile, {}
    )
    question = result["vragen"][0]
    assert question["id"] == "autovrij"
    assert "39.9% autovrij" in question["vraag"]
    assert question["opties"] == {
        "belangrijk": {
            "patch": {"voorkeuren": {"autovrij": "belangrijk"}}
        },
        "ok": {"patch": {"voorkeuren": {"autovrij": "ok"}}},
    }
    assert _question_ids(
        readiness.assess(_draft(autovrij=40, busy_data=True), profile, {})
    ) == []
    assert _question_ids(
        readiness.assess(_draft(autovrij=20, busy_data=False), profile, {})
    ) == []
    profile["voorkeuren"]["autovrij"] = "ok"
    assert _question_ids(
        readiness.assess(_draft(autovrij=20, busy_data=True), profile, {})
    ) == []


def test_weight_rule_requires_default_weights_and_material_route_signal():
    profile = profiles.default_document()

    offroad = readiness.assess(_draft(offroad=20.1), profile, {})
    heat = readiness.assess(_draft(heat=0.0), profile, {})
    assert _question_ids(offroad) == ["gewichten"]
    assert _question_ids(heat) == ["gewichten"]
    assert _question_ids(readiness.assess(_draft(offroad=20), profile, {})) == []

    profile["gewichten"] = {
        "hoogtemeters": 0.5,
        "offroad": 0.5,
        "populair": 0.0,
        "kort": 0.0,
    }
    assert _question_ids(readiness.assess(_draft(offroad=80, heat=50), profile, {})) == []


def test_trail_weight_rule_offers_popularity_only_with_walking_layer():
    profile = profiles.default_document()
    profile["activiteit"] = "trail"

    without_walking = readiness.assess(_draft(heat=40), profile, {})
    with_walking = readiness.assess(
        _draft(heat=40, walking_popularity=True), profile, {}
    )

    assert _question_ids(without_walking) == []
    assert _question_ids(with_walking) == ["gewichten"]
    assert "populaire wandelroutes" in with_walking["vragen"][0]["vraag"]


def test_place_crossings_do_not_block_route_completion():
    # Door dorpskernen rijden is normaal voor een lus: de plaatsvraag mag de
    # eerste route (incl. preview) niet blokkeren. Met een verder volledig
    # profiel is de readiness dus 'klaar' ondanks gepasseerde kernen.
    profile = profiles.default_document()
    places = [
        {"label": "Start", "type": "town", "afstand_m": 0},
        {"label": "Doordorp", "type": "village", "afstand_m": 120},
        {"label": "Kwatrecht", "type": "village", "afstand_m": 220},
    ]

    result = readiness.assess(_draft(places=places), profile, {})

    assert result["klaar"] is True
    assert "vermijd_plaatsen" not in _question_ids(result)

    allowed = _draft(places=places)
    allowed["route_request"] = {
        "toegestane_plaatsen": ["Doordorp", "Kwatrecht"]
    }
    assert _question_ids(readiness.assess(allowed, profiles.default_document(), {})) == []


def test_priority_max_three_unknown_and_ready_logic():
    profile = profiles.default_document()
    result = readiness.assess(
        _draft(
            cobble=500,
            concrete=1200,
            crossings=10,
            offroad=30,
            heat=40,
            places=[{"label": "Doordorp", "type": "village", "afstand_m": 100}],
        ),
        profile,
        {},
    )

    assert _question_ids(result) == ["kasseien", "beton", "steenwegen"]
    assert result["onbekend"] == [
        "kasseien",
        "beton",
        "steenwegen",
        "gewichten",
        "vermijd_plaatsen",
    ]
    assert result["klaar"] is False
    assert "kasseivraag eerst" in result["advies"]

    optional_only = readiness.assess(_draft(crossings=10, offroad=30), profile, {})
    assert _question_ids(optional_only) == ["steenwegen", "gewichten"]
    assert optional_only["klaar"] is False

    resolved = profiles.default_document()
    resolved["voorkeuren"].update(
        {"kasseien": "ok", "beton": "ok", "steenwegen": "ok"}
    )
    resolved["gewichten"] = {
        "hoogtemeters": 0.6,
        "offroad": 0.4,
        "populair": 0.0,
        "kort": 0.0,
    }
    done = readiness.assess(_draft(), resolved, {})
    assert done["vragen"] == []
    assert done["klaar"] is True


def test_all_profile_option_patches_round_trip_through_apply_patch():
    scenarios = [
        _draft(cobble=500),
        _draft(concrete=1200),
        _draft(crossings=10),
        _draft(autovrij=20, busy_data=True),
        _draft(offroad=30, heat=40),
    ]
    patches = []
    for scenario in scenarios:
        result = readiness.assess(scenario, profiles.default_document(), {})
        for question in result["vragen"]:
            for option in question["opties"].values():
                if option.get("doel") != "draft":
                    patches.append(option["patch"])

    with tempfile.TemporaryDirectory() as temp_dir:
        with _isolated_home(Path(temp_dir)):
            for index, patch in enumerate(patches):
                updated = profiles.apply_patch(
                    f"roundtrip-{index}", patch, bron="readiness-test"
                )
                assert updated["historiek"][-1]["patch"] == patch
