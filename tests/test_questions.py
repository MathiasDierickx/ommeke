"""Situationele vragencatalogus met geinjecteerde probe-waarnemingen (offline)."""

from lusmaker import intents, profiles, questions, readiness


def _draft(*, km, hm, cobble=0, unpaved=0, goal=None):
    d = {
        "id": "q1",
        "start": {"label": "Start", "lat": 51.0, "lon": 3.7},
        "end": None,
        "avoid_places": [],
        "_probe": {
            "km": km,
            "hm": hm,
            "kwaliteit": {"kassei_m": cobble, "onverhard_m": unpaved},
            "terrein": {"kassei_aanwezig_m": cobble, "plaatskernen": []},
        },
    }
    if goal:
        d["route_request"] = {"doel": goal}
    return d


def _profile(activity, **preferences):
    profile = profiles.default_document()
    profile["activiteit"] = activity
    profile["voorkeuren"].update(preferences)
    return profile


def _ids(d, profile):
    return [q["id"] for q in questions.ask(d, profile, d["_probe"])]


# -- beide richtingen: wel en niet vragen ---------------------------------

def test_city_walk_with_cobbles_asks_no_cobble_question():
    d = _draft(km=6, hm=15, cobble=3000)
    assert "kasseien" not in _ids(d, _profile("wandelen"))
    assert "kasseien" not in _ids(d, _profile("trail"))
    assert readiness.assess(d, _profile("wandelen"), {})["klaar"] is True


def test_road_bike_in_the_flemish_ardennes_asks_cobbles_and_hills_with_numbers():
    d = _draft(km=45, hm=700, cobble=2400)
    result = readiness.assess(d, _profile("koersfiets"), {})
    by_id = {q["id"]: q for q in result["vragen"]}

    assert set(by_id) == {"kasseien", "heuvels"}
    assert "2,4 km kasseien op je verkenningsroute" in by_id["kasseien"]["reden"]
    assert "700 hoogtemeters" in by_id["heuvels"]["reden"]
    assert "15,6 hm/km" in by_id["heuvels"]["reden"]
    assert result["klaar"] is False


def test_touring_bike_in_the_polders_asks_no_hills_question():
    d = _draft(km=40, hm=80)  # 2 hm/km
    assert _ids(d, _profile("toerfiets")) == []


def test_hill_threshold_is_8_for_bikes_and_12_for_foot():
    assert "heuvels" not in _ids(_draft(km=10, hm=79), _profile("toerfiets"))
    assert "heuvels" in _ids(_draft(km=10, hm=80), _profile("toerfiets"))
    assert "heuvels" not in _ids(_draft(km=10, hm=119), _profile("wandelen"))
    assert "heuvels" in _ids(_draft(km=10, hm=120), _profile("wandelen"))
    assert "heuvels" in _ids(_draft(km=10, hm=120), _profile("wegloop"))


def test_cobbles_only_ask_for_paved_bikes_and_road_running():
    d = _draft(km=30, hm=30, cobble=2000)
    for activity in ("koersfiets", "stadsfiets", "toerfiets", "fietsen", "wegloop"):
        assert "kasseien" in _ids(d, _profile(activity)), activity
    for activity in ("gravel", "mtb", "trail", "wandelen"):
        assert "kasseien" not in _ids(d, _profile(activity)), activity


def test_cobble_trigger_needs_300_meter_and_two_percent():
    assert "kasseien" not in _ids(_draft(km=5, hm=5, cobble=300), _profile("koersfiets"))
    assert "kasseien" in _ids(_draft(km=5, hm=5, cobble=301), _profile("koersfiets"))
    assert "kasseien" not in _ids(_draft(km=50, hm=50, cobble=900), _profile("koersfiets"))  # 1,8%
    assert "kasseien" in _ids(_draft(km=50, hm=50, cobble=1100), _profile("koersfiets"))


# -- al beantwoord ---------------------------------------------------------

def test_explicit_preferences_skip_their_question_but_null_asks():
    d = _draft(km=45, hm=700, cobble=2400, unpaved=6000)
    base = _profile("koersfiets")
    assert set(_ids(d, base)) == {"kasseien", "heuvels", "ondergrond"}
    assert "kasseien" not in _ids(d, _profile("koersfiets", kasseien="vermijd"))
    assert "heuvels" not in _ids(d, _profile("koersfiets", heuvels="zoek"))
    assert "ondergrond" not in _ids(d, _profile("koersfiets", ondergrond="verhard"))


def test_ok_means_indifferent_and_is_never_asked_again():
    d = _draft(km=45, hm=700, cobble=2400, unpaved=6000)
    profile = _profile("koersfiets", kasseien="ok", heuvels="ok", ondergrond="ok")
    assert _ids(d, profile) == []


def test_explicit_goal_skips_the_hills_question():
    for goal in ("hoogtemeters", "offroad", "kort"):
        assert "heuvels" not in _ids(_draft(km=45, hm=700, goal=goal), _profile("koersfiets"))
    assert "heuvels" in _ids(_draft(km=45, hm=700, goal="toeren"), _profile("koersfiets"))


# -- ondergrond ------------------------------------------------------------

def test_ground_question_is_inverse_for_gravel_and_mtb():
    mostly_unpaved = _draft(km=30, hm=30, unpaved=25000)
    mostly_paved = _draft(km=30, hm=30, unpaved=5000)
    assert "ondergrond" in _ids(mostly_unpaved, _profile("stadsfiets"))
    assert "ondergrond" not in _ids(_draft(km=30, hm=30, unpaved=500), _profile("stadsfiets"))
    assert "ondergrond" not in _ids(mostly_unpaved, _profile("gravel"))
    assert "ondergrond" not in _ids(mostly_unpaved, _profile("mtb"))
    for activity in ("gravel", "mtb"):
        asked = questions.ask(mostly_paved, _profile(activity), mostly_paved["_probe"])
        ground = next(q for q in asked if q["id"] == "ondergrond")
        assert "verhard" in ground["reden"] and set(ground["opties"]) == {"onverhard", "ok"}
    assert "ondergrond" not in _ids(mostly_unpaved, _profile("wandelen"))


def test_ground_question_needs_a_measurement():
    d = _draft(km=30, hm=30)
    del d["_probe"]["kwaliteit"]["onverhard_m"]
    assert _ids(d, _profile("gravel")) == []
    assert _ids(d, _profile("stadsfiets")) == []


# -- rangschikking en limiet -----------------------------------------------

def test_questions_rank_by_impact_and_cap_at_three_overall():
    hills_dominant = _draft(km=20, hm=600, cobble=450)   # 30 hm/km, cobbles net boven drempel
    asked = questions.ask(hills_dominant, _profile("koersfiets"), hills_dominant["_probe"])
    assert [q["id"] for q in asked] == ["heuvels", "kasseien"]
    assert [q["prioriteit"] for q in asked] == [1, 2]

    cobbles_dominant = _draft(km=20, hm=170, cobble=6000)
    asked = questions.ask(cobbles_dominant, _profile("koersfiets"), cobbles_dominant["_probe"])
    assert [q["id"] for q in asked] == ["kasseien", "heuvels"]

    crowded = _draft(km=20, hm=600, cobble=3000, unpaved=9000)
    crowded["_probe"]["kwaliteit"].update(beton_m=2000, steenweg_m=4000)
    result = readiness.assess(crowded, _profile("koersfiets"), {})
    assert len(result["vragen"]) == 3
    assert {q["id"] for q in result["vragen"]} <= {"kasseien", "heuvels", "ondergrond", "beton", "steenwegen"}
    assert len(result["onbekend"]) >= 4


def test_every_question_has_reason_with_a_number_and_options_with_patches():
    d = _draft(km=45, hm=700, cobble=2400, unpaved=6000)
    for q in questions.ask(d, _profile("koersfiets"), d["_probe"]):
        assert any(ch.isdigit() for ch in q["reden"])
        assert q["opties"]
        for option in q["opties"].values():
            assert list(option["patch"]["voorkeuren"]) == [q["id"]]


def test_hill_answers_map_to_goals():
    d = _draft(km=45, hm=700)
    hills = questions.ask(d, _profile("toerfiets"), d["_probe"])[0]
    assert hills["opties"]["zoek"]["adjust_route"] == {"doel": "hoogtemeters"}
    assert hills["opties"]["ok"]["adjust_route"] == {"doel": "toeren"}
    assert hills["opties"]["vlak"]["adjust_route"] == {"doel": "toeren"}


# -- profielen en doorvoer -------------------------------------------------

def test_profile_nullable_keys_are_backward_compatible_and_validated():
    legacy = profiles.default_document()
    for key in ("heuvels", "ondergrond"):
        del legacy["voorkeuren"][key]
    checked = profiles._validate(legacy)
    assert checked["voorkeuren"]["heuvels"] is None and checked["voorkeuren"]["ondergrond"] is None

    bad = profiles.default_document()
    bad["voorkeuren"]["heuvels"] = "bergop"
    try:
        profiles._validate(bad)
    except profiles.ProfileError:
        pass
    else:
        raise AssertionError("ongeldige heuvelwaarde moet falen")
    for value in ("zoek", "ok", "vlak"):
        ok = profiles.default_document()
        ok["voorkeuren"]["heuvels"] = value
        assert profiles._validate(ok)["voorkeuren"]["heuvels"] == value


def test_plan_route_explicit_hills_and_ground_reach_the_profile_and_silence_questions():
    request = intents._route_request(
        doel="toeren", target_km=40, max_km=None, tolerance_km=2.5, geen_opvulling=False,
        profiel_naam="standaard", activiteit="koersfiets", kasseien=None,
        beton_vermijden=None, autovrij=None, strict=None, request_id=None,
        rond_plaats=None, langs_water=None, input_signature={},
        heuvels="vlak", ondergrond="verhard",
    )
    assert request["expliciete_voorkeuren"] == {"heuvels": "vlak", "ondergrond": "verhard"}
    profile = intents._profile_for_request(request, lambda _name: profiles.default_document())
    d = _draft(km=45, hm=700, unpaved=9000)
    assert _ids(d, profile) == []


def test_plan_route_with_injected_probe_returns_situational_needs_input():
    state = {
        "id": "sit1", "name": "lus", "start": {"label": "Gavere", "lat": 50.93, "lon": 3.65},
        "end": None, "loop": True, "climbs": [], "avoid_places": [], "computed": None,
        "_probe": _draft(km=45, hm=700, cobble=2400)["_probe"],
    }

    def unexpected(*_args, **_kwargs):
        raise AssertionError("needs_input mag nog niet routeren")

    result = intents.plan_route(
        "Gavere", target_km=45, activiteit="koersfiets", check_readiness=True,
        profiel_naam="standaard",
        create_fn=lambda **_kwargs: {"id": "sit1"}, load_fn=lambda _id: state,
        climbs_fn=lambda: {}, save_fn=lambda _d: None,
        probe_fn=lambda d, _db: d["_probe"],
        profile_load_fn=lambda name: profiles.default_document(name),
        route_fn=unexpected, optimize_fn=unexpected,
        export_gpx_fn=unexpected, export_preview_fn=unexpected,
    )
    assert result["status"] == "needs_input"
    assert {q["id"] for q in result["vragen"]} == {"kasseien", "heuvels"}
    assert "2,4 km kasseien" in result["vragen"][0]["reden"] or "2,4 km kasseien" in result["vragen"][1]["reden"]


# -- onbekend (null) versus expliciet ok/nee (#11) -------------------------

def _request(**choices):
    base = dict(doel="toeren", target_km=30, max_km=None, tolerance_km=2.5, geen_opvulling=False,
                profiel_naam="standaard", activiteit="koersfiets", kasseien=None, beton_vermijden=None,
                autovrij=None, strict=None, request_id=None, rond_plaats=None, langs_water=None,
                input_signature={})
    return intents._route_request(**{**base, **choices})


def test_unknown_plan_route_inputs_are_not_recorded_as_explicit_choices():
    assert _request()["expliciete_voorkeuren"] == {}
    # False en True zijn echte antwoorden en worden nooit als onbekend behandeld.
    nee = _request(kasseien=False, beton_vermijden=False, autovrij=False, strict=False)["expliciete_voorkeuren"]
    assert nee == {"kasseien": "vermijd", "beton": "ok", "steenwegen": "ok", "autovrij": "ok"}
    ja = _request(kasseien=True, beton_vermijden=True, autovrij=True, strict=True)["expliciete_voorkeuren"]
    assert ja == {"kasseien": "ok", "beton": "vermijd", "steenwegen": "vermijd", "autovrij": "belangrijk"}
    assert _request(heuvels="ok", ondergrond="verhard")["expliciete_voorkeuren"] == {"heuvels": "ok", "ondergrond": "verhard"}


def test_unknown_preference_stays_null_in_profile_but_explicit_values_override_it():
    profile = profiles.default_document()
    profile["voorkeuren"].update(kasseien="graag", heuvels=None)
    loader = lambda _name: profile
    unknown = intents._profile_for_request(_request(), loader)["voorkeuren"]
    assert unknown["kasseien"] == "graag" and unknown["heuvels"] is None   # onbekend wist niets uit
    explicit = intents._profile_for_request(_request(kasseien=False, heuvels="ok"), loader)["voorkeuren"]
    assert explicit["kasseien"] == "vermijd" and explicit["heuvels"] == "ok"
    assert profile["voorkeuren"]["kasseien"] == "graag"                    # bronprofiel blijft onaangeroerd


def test_questions_distinguish_unknown_from_explicit_ok_and_nee():
    from lusmaker import questions
    d = {"id": "q", "start": {"label": "Start", "lat": 51.0, "lon": 3.7}, "end": None, "avoid_places": [],
         "_probe": {"km": 45, "hm": 700, "kwaliteit": {"kassei_m": 2400, "onverhard_m": 0},
                    "terrein": {"kassei_aanwezig_m": 2400, "plaatskernen": []}}}

    def asked(**choices):
        request = _request(**choices)
        profile = intents._profile_for_request(request, lambda _n: profiles.default_document())
        profile["activiteit"] = "koersfiets"
        return {q["id"] for q in questions.ask(d, profile, d["_probe"])}

    assert "kasseien" in asked()                    # onbekend: vragen
    assert "kasseien" not in asked(kasseien=True)   # expliciet oké: nooit meer vragen
    assert "kasseien" not in asked(kasseien=False)  # expliciet vermijden: ook niet
    assert "heuvels" in asked() and "heuvels" not in asked(heuvels="ok")
