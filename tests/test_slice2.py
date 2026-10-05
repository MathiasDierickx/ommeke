"""Slice 2 van #29: echte vlakrangschikking, voorkeuren per activiteit, voorstellen."""

import tempfile
from pathlib import Path

from lusmaker import draft, intents, profiles, proposals, questions, readiness

from .test_optimize import _synthetic_climb_db, _synthetic_routed_draft
from .test_intents import _climbs, _routed_draft


# -- 1. vlak ---------------------------------------------------------------

def _fill(objective, ascents, *, target_total_m=None, distances=None):
    """Draai de rondrit-opvulling met vijf geinjecteerde kandidaten."""
    routed = _synthetic_routed_draft()
    distances = distances or [4000] * 5

    def round_trip_fn(anchor, distance_m, seed, **_preferences):
        offset = 0.01 + seed * 0.001
        coords = [anchor, (50.01, 4.02), (50.01, 4.02 + offset), anchor]
        return {
            "distance_m": distances[seed],
            "ascend_m": ascents[seed],
            "coords": [(lat, lon, 0) for lat, lon in coords],
        }

    def router(d, passed_climb_db):
        seed = d["opvullingen"][-1]["seed"]
        d["computed"] = {
            "total_km": 5.0 + distances[seed] / 1000.0,
            "ascend_m": 40 + ascents[seed],
            "descend_m": 40,
            "legs": [],
            "kwaliteit": {"heen_en_weer_m": 0},
        }
        d["_geometry"] = []

    return draft._fill_with_round_trip(
        routed,
        _synthetic_climb_db(),
        budget_m=10500,
        router=router,
        round_trip_fn=round_trip_fn,
        popular_cells=set(),
        objective=objective,
        target_total_m=target_total_m,
    )


def test_flat_objective_picks_lowest_ascent_per_km_while_hm_picks_highest():
    ascents = [60, 20, 100, 45, 30]
    assert _fill("vlak", ascents)["seed"] == 1
    assert _fill("hm-per-km", ascents)["seed"] == 2


def test_flat_objective_normalises_by_distance_not_total_ascent():
    # Seed 0: 30 hm over 2 km (15/km); seed 1: 40 hm over 4 km (10/km).
    result = _fill("vlak", [30, 40, 90, 90, 90], distances=[2000, 4000, 4000, 4000, 4000])
    assert result["seed"] == 1


def test_flat_objective_keeps_distance_target_ahead_of_flatness():
    # Doel: 9 km totaal => 4 km opvulling. De vlakste kandidaat (2 km) schiet te kort,
    # de afstand blijft dus voorgaan op vlakheid.
    result = _fill(
        "vlak", [5, 80, 70, 90, 95],
        target_total_m=9000, distances=[2000, 4000, 4000, 4000, 4000],
    )
    assert result["seed"] == 2


def test_flat_is_a_tour_objective_and_validates_in_select():
    assert draft._objective_weights("vlak") is None
    candidates = [
        {"climb": {"id": "steil"}, "extra_km": 1.0, "extra_hoogtemeters": 40, "invoegen_op_positie": 0},
        {"climb": {"id": "zacht"}, "extra_km": 2.0, "extra_hoogtemeters": 10, "invoegen_op_positie": 0},
    ]
    assert draft._select_candidate(candidates, "vlak")["climb"]["id"] == "zacht"
    assert draft._select_candidate(candidates, "hm-per-km")["climb"]["id"] == "steil"


def test_optimize_with_flat_objective_does_not_hunt_climbs():
    routed = _synthetic_routed_draft()
    routed["climbs"] = []
    seen = {}

    def candidates_fn(*_args, **_kwargs):
        raise AssertionError("vlak mag geen klimmen zoeken")

    def router(d, _db):
        d["computed"] = d["computed"] or {
            "total_km": 5.0, "ascend_m": 10, "descend_m": 10, "legs": [],
            "kwaliteit": {"heen_en_weer_m": 0},
        }
        d["_geometry"] = d.get("_geometry") or [[[50.0, 4.0, 0], [50.0, 4.01, 0]]]

    def round_trip_fn(*_args, **_kwargs):
        seen["called"] = True
        raise draft.gh.GhError("geen verbinding in test")

    result = draft._optimize(
        routed, _synthetic_climb_db(), 20.0, objective="vlak",
        route_fn=router, candidates_fn=candidates_fn, round_trip_fn=round_trip_fn,
    )
    assert result["objective"] == "vlak"
    assert routed["climbs"] == []


def _request(**explicit):
    return {
        "doel": "toeren", "target_km": 10.0, "max_km": 12.5, "max_km_explicit": False,
        "geen_opvulling": False, "activiteit": "wandelen",
        "expliciete_voorkeuren": explicit,
    }


def test_flat_preference_selects_flat_objective_for_tour_goals_only():
    assert intents._tour_objective(_request(heuvels="vlak")) == "vlak"
    assert intents._tour_objective(_request(heuvels="ok")) == "toeren"
    assert intents._tour_objective(_request()) == "toeren"
    hills = {**_request(heuvels="vlak"), "doel": "hoogtemeters"}
    assert intents._tour_objective(hills, "hoogtemeters") == "hoogtemeters"


def test_route_request_passes_flat_objective_and_keeps_distance_target():
    captured = {}

    def optimize_fn(d, climb_db, **kwargs):
        captured.update(kwargs)

    d = {"id": "x", "loop": True, "climbs": [], "computed": None}
    intents._route_for_request(
        d, {}, _request(heuvels="vlak"),
        route_fn=lambda *_a: None, optimize_fn=optimize_fn,
    )
    assert captured["objective"] == "vlak"
    assert captured["fill_target_km"] == 10.0
    assert captured["max_km"] >= 12.5


# -- 2. voorkeuren per activiteit ------------------------------------------

def test_per_activity_preferences_do_not_leak_between_activities():
    profile = profiles.default_document()
    profile["voorkeuren"]["kasseien"] = "vermijd"
    profile["voorkeuren_per_activiteit"] = {"wandelen": {"kasseien": "graag"}}
    # Fiets: top-level is de terugval.
    assert profiles.effective_preferences(profile, "koersfiets")["kasseien"] == "vermijd"
    assert profiles.effective_preferences(profile, "fietsen")["kasseien"] == "vermijd"  # legacy
    # Te voet lekt de fietsvoorkeur niet door; een eigen waarde wint.
    assert profiles.effective_preferences({**profile, "voorkeuren_per_activiteit": {}}, "wegloop")["kasseien"] is None
    assert profiles.effective_preferences(profile, "wandelen")["kasseien"] == "graag"
    # Plaatsen om te vermijden zijn activiteitsneutraal.
    profile["voorkeuren"]["vermijd_plaatsen"] = ["Zottegem"]
    assert profiles.effective_preferences(profile, "trail")["vermijd_plaatsen"] == ["Zottegem"]


def test_per_activity_override_beats_top_level_for_bikes():
    profile = profiles.default_document()
    profile["voorkeuren"]["kasseien"] = "vermijd"
    profile["voorkeuren_per_activiteit"] = {"koersfiets": {"kasseien": "graag"}}
    assert profiles.effective_preferences(profile, "koersfiets")["kasseien"] == "graag"
    assert profiles.effective_preferences(profile, "gravel")["kasseien"] == "vermijd"


def test_profile_validation_is_backwards_compatible_and_strict():
    legacy = profiles.default_document()
    del legacy["voorkeuren_per_activiteit"]
    assert profiles._validate(legacy)["voorkeuren_per_activiteit"] == {}

    bad_activity = profiles.default_document()
    bad_activity["voorkeuren_per_activiteit"] = {"zweefvliegen": {"kasseien": "ok"}}
    bad_key = profiles.default_document()
    bad_key["voorkeuren_per_activiteit"] = {"wandelen": {"vermijd_plaatsen": []}}
    bad_value = profiles.default_document()
    bad_value["voorkeuren_per_activiteit"] = {"wandelen": {"heuvels": "bergop"}}
    for broken in (bad_activity, bad_key, bad_value):
        try:
            profiles._validate(broken)
        except profiles.ProfileError:
            continue
        raise AssertionError("ongeldige per-activiteitvoorkeur werd aanvaard")

    legacy_name = profiles.default_document()
    legacy_name["voorkeuren_per_activiteit"] = {"fietsen": {"beton": "vermijd"}}
    assert profiles._validate(legacy_name)["voorkeuren_per_activiteit"] == {"toerfiets": {"beton": "vermijd"}}


def test_apply_patch_merges_per_activity_preferences_and_routing_follows_activity():
    from tests.test_profiles import _isolated_home

    with tempfile.TemporaryDirectory() as temp_dir:
        with _isolated_home(Path(temp_dir)):
            profiles.apply_patch("mix", {"voorkeuren": {"kasseien": "vermijd"}}, bron="test")
            saved = profiles.apply_patch(
                "mix", {"voorkeuren_per_activiteit": {"wandelen": {"kasseien": "ok"}}}, bron="test"
            )
            saved = profiles.apply_patch(
                "mix", {"voorkeuren_per_activiteit": {"wandelen": {"beton": "vermijd"}}}, bron="test"
            )
    assert saved["voorkeuren_per_activiteit"] == {"wandelen": {"kasseien": "ok", "beton": "vermijd"}}
    bike = profiles.routing_prefs(saved, "koersfiets")
    walk = profiles.routing_prefs(saved, "wandelen")
    assert bike["avoid_cobbles"] is True and bike["avoid_concrete"] is False
    assert walk["avoid_cobbles"] is False and walk["avoid_concrete"] is True


def _probe_draft(cobble=2000):
    return {
        "id": "q1", "start": {"label": "Start", "lat": 51.0, "lon": 3.7}, "end": None,
        "avoid_places": [],
        "_probe": {
            "km": 20, "hm": 50,
            "kwaliteit": {"kassei_m": cobble, "onverhard_m": 0},
            "terrein": {"kassei_aanwezig_m": cobble, "plaatskernen": []},
        },
    }


def test_questions_skip_only_for_the_activity_that_has_an_answer():
    profile = profiles.default_document()
    profile["activiteit"] = "koersfiets"
    profile["voorkeuren"]["kasseien"] = "vermijd"
    d = _probe_draft()
    ids = lambda p: [q["id"] for q in questions.ask(d, p, d["_probe"])]
    assert "kasseien" not in ids(profile)                      # fiets: al beantwoord
    walk_run = {**profile, "activiteit": "wegloop"}
    assert "kasseien" in ids(walk_run)                         # lopen: niet doorgelekt
    answered_run = {**walk_run, "voorkeuren_per_activiteit": {"wegloop": {"kasseien": "ok"}}}
    assert "kasseien" not in ids(answered_run)


def test_readiness_uses_activity_specific_preferences():
    profile = profiles.default_document()
    profile["activiteit"] = "wegloop"
    profile["voorkeuren"].update(kasseien="vermijd", beton="vermijd")
    d = _probe_draft()
    asked = readiness.assess(d, profile, {})["onbekend"]
    assert "kasseien" in asked
    profile["voorkeuren_per_activiteit"] = {"wegloop": {"kasseien": "ok"}}
    assert "kasseien" not in readiness.assess(d, profile, {})["onbekend"]


def test_explicit_trip_answers_win_on_foot_without_top_level_fallback():
    profile = profiles.default_document()
    profile["voorkeuren"]["kasseien"] = "vermijd"
    request = {
        "profiel_naam": "standaard", "activiteit": "wandelen",
        "expliciete_voorkeuren": {"heuvels": "vlak"},
    }
    resolved = intents._profile_for_request(request, lambda _name: profile)
    prefs = profiles.effective_preferences(resolved, "wandelen")
    assert prefs["heuvels"] == "vlak" and prefs["kasseien"] is None
    assert profile["voorkeuren_per_activiteit"] == {}          # bronprofiel onaangeroerd


# -- 3. voorstellen --------------------------------------------------------

def _suggestion(climb_id, extra_km, hm, name=None):
    return {
        "id": climb_id, "climb": {"id": climb_id, "name": name or climb_id.title()},
        "extra_km": extra_km, "extra_hoogtemeters": hm,
    }


def _bike_draft(km=40.0, climbs=()):
    return {
        "id": "b1", "loop": True, "climbs": list(climbs),
        "start": {"lat": 50.9, "lon": 3.9, "label": "Wetteren"},
        "computed": {"total_km": km, "ascend_m": 200},
    }


def test_bike_proposals_offer_best_climbs_with_ready_adjust_arguments():
    suggestions = [
        _suggestion("molenberg", 2.0, 60, "Molenberg"),
        _suggestion("vlakke-klim", 1.0, 5),          # te weinig hoogtemeters
        _suggestion("kapelmuur", 4.0, 70, "Kapelmuur"),
        _suggestion("ver", 9.0, 200),                # te veel omweg
        _suggestion("al-erin", 1.0, 90),
    ]
    found = proposals.build(
        _bike_draft(climbs=["al-erin"]), {}, {"activiteit": "toerfiets"},
        suggest_fn=lambda *_a, **_k: suggestions,
    )
    assert [p["adjust_route"]["voeg_klimmen_toe"] for p in found] == [["molenberg"], ["kapelmuur"]]
    assert found[0]["titel"] == "Voeg Molenberg toe"
    assert found[0]["adjust_route"]["target_km"] == 43          # 40 + 2 + 0,5 afgerond naar boven
    assert "2,0 km" in found[0]["uitleg"] and "60" in found[0]["uitleg"]
    assert set(found[0]) == {"titel", "uitleg", "adjust_route"}


def test_bike_proposals_respect_flat_preference_and_hard_maximum_and_cap_at_two():
    many = [_suggestion(f"k{i}", 1.0 + i / 10, 50) for i in range(4)]
    suggest = lambda *_a, **_k: many
    assert len(proposals.build(_bike_draft(), {}, {"activiteit": "toerfiets"}, suggest_fn=suggest)) == 2
    flat = {"activiteit": "toerfiets", "expliciete_voorkeuren": {"heuvels": "vlak"}}
    assert proposals.build(_bike_draft(), {}, flat, suggest_fn=suggest) == []
    capped = {"activiteit": "toerfiets", "max_km": 40.5, "max_km_explicit": True}
    assert proposals.build(_bike_draft(), {}, capped, suggest_fn=suggest) == []


def test_proposals_are_empty_when_nothing_is_sensible_or_lookup_fails():
    assert proposals.build(_bike_draft(), {}, {"activiteit": "gravel"},
                           suggest_fn=lambda *_a, **_k: []) == []

    def boom(*_a, **_k):
        raise RuntimeError("geen netwerk")

    assert proposals.build(_bike_draft(), {}, {"activiteit": "gravel"}, suggest_fn=boom) == []
    assert proposals.build({"id": "x", "computed": None}, {}, {"activiteit": "gravel"}) == []


_GAZETTEER = {
    "landmarks": [
        ("Parking X", "parking", 50.9005, 3.9005),
        ("Ver Park", "park", 51.5, 4.5),
        ("Warandepark", "park", 50.905, 3.905),
        ("Dichter Domein", "nature_reserve", 50.903, 3.903),
    ],
    "waterways": {
        "schelde": [[(50.91, 3.91), (50.912, 3.912)]],
        "verre beek": [[(52.0, 5.0), (52.001, 5.001)]],
    },
}


def test_foot_proposals_offer_nearby_green_and_water_from_existing_data():
    walk = {**_bike_draft(km=6.2), "start": {"lat": 50.9, "lon": 3.9, "label": "Wetteren"}}
    found = proposals.build(walk, {}, {"activiteit": "wandelen"}, gazetteer_fn=lambda: _GAZETTEER)
    assert [p["adjust_route"] for p in found] == [
        {"rond_plaats": "Dichter Domein", "target_km": 6},
        {"langs_water": "schelde", "target_km": 6},
    ]
    assert found[0]["titel"] == "Wandel rond Dichter Domein"
    assert found[1]["titel"] == "Langs het water: Schelde"


def test_foot_proposals_skip_what_is_already_asked_or_out_of_reach():
    walk = _bike_draft(km=8.0)
    asked = {"activiteit": "trail", "rond_plaats": "Warandepark", "langs_water": "Leie"}
    assert proposals.build(walk, {}, asked, gazetteer_fn=lambda: _GAZETTEER) == []
    far = {**walk, "start": {"lat": 40.0, "lon": 0.0, "label": "Ver"}}
    assert proposals.build(far, {}, {"activiteit": "wandelen"}, gazetteer_fn=lambda: _GAZETTEER) == []


def test_compact_result_includes_proposals_only_when_present():
    files = {"gpx": "/tmp/test.gpx", "preview": "/tmp/test.html"}
    offered = [{"titel": "Voeg X toe", "uitleg": "u", "adjust_route": {"voeg_klimmen_toe": ["x"], "target_km": 45}}]
    with_ = intents.compact_result(_routed_draft(), _climbs(), files, proposals_fn=lambda *_a: offered)
    assert with_["voorstellen"] == offered
    assert any("voorstellen" in step for step in with_["vervolg"])
    without = intents.compact_result(_routed_draft(), _climbs(), files, proposals_fn=lambda *_a: [])
    assert "voorstellen" not in without


def test_chat_prompt_tells_the_model_to_offer_proposals():
    from lusmaker import aws_chat

    assert "voorstellen" in aws_chat.SYSTEM_PROMPT
    assert "adjust_route-argumenten" in aws_chat.SYSTEM_PROMPT
