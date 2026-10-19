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
