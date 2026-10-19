"""Criteria en rit-in-lijn door de intentielaag en de route-detail-API."""
import tempfile
from pathlib import Path

from lusmaker import aws_api, intents

CRITERIA = [{"metriek": "stil", "label": "Rustig", "gewicht": 3},
            {"metriek": "kassei", "richting": "laag", "hard": True, "drempel": 0.05}]


def _state():
    return {
        "id": "abc123", "name": "testlus", "revision": 2,
        "start": {"label": "Wetteren", "lat": 50.0, "lon": 4.0}, "loop": True, "climbs": [],
        "computed": {"total_km": 9.0, "ascend_m": 40, "legs": [],
                     "kwaliteit": {"kassei_m": 0, "stil_pct": 81.0, "steenweg_kruisingen": 1}},
    }


def _export(_d, _db, path):
    return {"file": path}


def test_plan_route_geeft_criteria_als_objective_en_waarom_terug():
    state, calls = _state(), []

    def optimize_fn(d, _db, **kwargs):
        calls.append(kwargs)
        d["computed"] = _state()["computed"]

    with tempfile.TemporaryDirectory() as tmp:
        result = intents.plan_route(
            "Wetteren", target_km=9, activiteit="wandelen", criteria=CRITERIA,
            create_fn=lambda **_k: {"id": "abc123"}, load_fn=lambda _i: state,
            optimize_fn=optimize_fn, climbs_fn=dict, export_gpx_fn=_export,
            export_preview_fn=_export, save_fn=lambda _d: None, exports_root=Path(tmp),
        )
    spec = calls[0]["objective"]["criteria"]
    assert [c["id"] for c in spec] == ["stil", "kassei"] and spec[0]["gewicht"] == 1.0
    assert state["route_request"]["criteria"] == spec
    assert [(w["id"], w["ok"]) for w in result["waarom"]] == [("stil", True), ("kassei", True)]
    assert result["waarom"][0]["tekst"] == "81 % rustige wegen"


def test_plan_route_weigert_onbekende_metriek():
    try:
        intents.plan_route("Wetteren", target_km=9, criteria=[{"metriek": "bos"}],
                           create_fn=lambda **_k: {"id": "x"}, load_fn=lambda _i: _state())
    except intents.IntentError as exc:
        assert "onbekende metriek" in str(exc)
    else:
        raise AssertionError("IntentError verwacht")


def test_plan_route_eind_maakt_rit_in_lijn_zonder_opvulling():
    state = _state() | {"loop": False, "end": {"label": "Gent", "lat": 51.05, "lon": 3.72}}
    created, routed = {}, []

    def create_fn(**kwargs):
        created.update(kwargs)
        return {"id": "abc123"}

    def route_fn(d, _db):
        routed.append(True)
        d["computed"] = _state()["computed"] | {"total_km": 21.0}

    def unexpected(*_a, **_k):
        raise AssertionError("rit in lijn mag niet optimaliseren")

    with tempfile.TemporaryDirectory() as tmp:
        result = intents.plan_route(
            "Wetteren", eind="Gent", activiteit="koersfiets",
            create_fn=create_fn, load_fn=lambda _i: state, route_fn=route_fn,
            optimize_fn=unexpected, climbs_fn=dict, export_gpx_fn=_export,
            export_preview_fn=_export, save_fn=lambda _d: None, exports_root=Path(tmp),
        )
    assert created["loop"] is False and created["end"] == "Gent"
    assert routed and result["km"] == 21.0 and state["route_request"]["eind"] == "Gent"


def test_route_detail_toont_verkenning_en_waarom():
    waiting = _state() | {"computed": None, "route_request": {"doel": "toeren"},
                          "_probe": {"km": 12.0, "punten": [[50.0, 4.0], [50.01, 4.01]]}}
    payload = aws_api._route_detail_payload(waiting, proposals_fn=lambda _i: [])
    assert payload["ready"] is False
    assert payload["geometry"]["verkenning"] is True and payload["geometry"]["points"] == [[50.0, 4.0], [50.01, 4.01]]
    assert payload["waarom"] == []

    ready = _state() | {"route_request": {"doel": "toeren", "criteria": intents.criteria.parse(CRITERIA)}}
    payload = aws_api._route_detail_payload(ready, proposals_fn=lambda _i: [])
    assert payload["ready"] is True and "verkenning" not in payload["geometry"]
    assert [w["ok"] for w in payload["waarom"]] == [True, True]


def test_apply_answers_merges_criteria_into_the_request():
    state = {"id": "d1", "revision": 1, "route_request": {"doel": "toeren", "activiteit": "wandelen",
             "criteria": intents.criteria.parse([{"metriek": "onverhard", "gewicht": 1}])}}
    intents.apply_answers("d1", {"stil": "belangrijk", "oversteken": "vermijd"},
                          load_fn=lambda _i: state, save_fn=lambda _d: None,
                          adjust_fn=lambda _i, **_k: {"status": "ready"})
    assert [c["id"] for c in state["route_request"]["criteria"]] == ["onverhard", "stil", "oversteken"]
    intents.apply_answers("d1", {"stil": "ok"}, load_fn=lambda _i: state, save_fn=lambda _d: None,
                          adjust_fn=lambda _i, **_k: {"status": "ready"})
    assert [c["id"] for c in state["route_request"]["criteria"]] == ["onverhard", "oversteken"]


def test_empty_answers_route_now_without_asking_again():
    state = {"id": "d1", "revision": 1, "route_request": {"doel": "toeren", "activiteit": "wandelen", "profiel_naam": "standaard"}}
    calls = []
    intents.apply_answers("d1", {}, load_fn=lambda _i: state, save_fn=lambda _d: None,
                          adjust_fn=lambda _i, **kw: calls.append(kw) or {"status": "ready"})
    assert calls == [{"doel": "toeren", "check_readiness": False}]
    assert state["route_request"].get("criteria") is None


def test_summary_sentence_names_a_point_to_point_ride():
    d = _state() | {"loop": False, "end": {"label": "Gent", "lat": 51.05, "lon": 3.72}}
    assert intents.summary_sentence(d).startswith("Rit van Wetteren naar Gent: 9,0 km")
    assert intents.summary_sentence(_state()).startswith("Lus vanuit Wetteren")


def test_readiness_skips_questions_already_covered_by_criteria():
    from lusmaker import profiles, readiness
    d = {"id": "q1", "start": {"label": "Start", "lat": 51.0, "lon": 3.7}, "end": None, "avoid_places": [],
         "route_request": {"doel": "toeren", "criteria": intents.criteria.parse([{"metriek": "oversteken", "richting": "laag"}])},
         "_probe": {"km": 6, "hm": 10, "kwaliteit": {"kassei_m": 0, "onverhard_m": 0, "steenweg_kruisingen": 7, "stil_pct": 30.0},
                    "terrein": {"kassei_aanwezig_m": 0, "plaatskernen": [], "kruisingen": 7}}}
    profile = profiles.default_document(); profile["activiteit"] = "wandelen"
    ids = [q["id"] for q in readiness.assess(d, profile, {})["vragen"]]
    assert "oversteken" not in ids and "stil" in ids


def test_auto_route_name_uses_a_decimal_comma():
    assert intents.suggest_route_name("Wetteren", target_km=3.1, max_km=None, doel="toeren", activiteit="wandelen").endswith("· 3,1 km")
    assert intents.suggest_route_name("Wetteren", target_km=38, max_km=None, doel="toeren", activiteit="toerfiets").endswith("· 38 km")


def test_water_too_far_from_start_is_not_planned_and_explained():
    state = _state() | {"computed": None}
    saved = []

    def route_fn(d, _db):
        assert not d.get("water_via"), "te verre waterloop mag geen via-punten geven"
        d["computed"] = _state()["computed"]

    def optimize_fn(d, _db, **_k):
        d["computed"] = _state()["computed"]

    with tempfile.TemporaryDirectory() as tmp:
        result = intents.plan_route(
            "Wetteren", target_km=5, activiteit="wandelen", langs_water="Dender",
            create_fn=lambda **_k: {"id": "abc123"}, load_fn=lambda _i: state,
            route_fn=route_fn, optimize_fn=optimize_fn, climbs_fn=dict, export_gpx_fn=_export,
            export_preview_fn=_export, save_fn=lambda d: saved.append(True),
            water_fn=lambda _name: [[(50.96, 4.04), (50.97, 4.05)]],  # ~13 km verderop
            exports_root=Path(tmp),
        )
    assert result["status"] == "ready"
    assert result["constraints"]["langs_water_gepland"] is False
    assert any("te ver" in w for w in result["constraints"]["waarschuwingen"])


def test_route_over_hard_maximum_never_stays_ready_in_the_draft():
    state = _state() | {"computed": None, "water_via": [(50.0, 4.0)]}

    def route_fn(d, _db):
        d["computed"] = _state()["computed"] | {"total_km": 45.5}

    try:
        intents.plan_route(
            "Wetteren", target_km=5, max_km=5, activiteit="wandelen", langs_water="Schelde",
            create_fn=lambda **_k: {"id": "abc123"}, load_fn=lambda _i: state,
            route_fn=route_fn, optimize_fn=lambda *_a, **_k: None, climbs_fn=dict,
            export_gpx_fn=_export, export_preview_fn=_export, save_fn=lambda _d: None,
            water_fn=lambda _name: [[(50.0, 4.0), (50.001, 4.001)]],
        )
    except intents.IntentError as exc:
        assert "harde maximum" in str(exc)
    else:
        raise AssertionError("IntentError verwacht")
    assert state.get("computed") is None, "een te lange route mag niet als klaar achterblijven"
