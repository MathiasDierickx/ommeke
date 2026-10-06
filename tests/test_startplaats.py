"""Dubbelzinnige plaatsen: volledig offline, met injecteerbare probe/router."""
import copy
import tempfile
from pathlib import Path

from lusmaker import geocode, intents


GAZETTEER = {
    "places": [("Kluisbergen", "municipality", 50.76, 3.50), ("Halle", "town", 50.74, 4.26)],
    "streets": {},
    "landmarks": [("Kluisbos", "natural:wood", 50.76, 3.50), ("Kluisbos", "natural:wood", 50.74, 4.26)],
}


def resolve(query):
    return geocode.resolve(query, gazetteer=GAZETTEER, google_resolver=None)


def test_geocode_ambiguity_labels_and_explicit_municipality():
    point, _ = resolve("Kluisbos")
    assert [c["label"] for c in point["candidates"]] == ["Kluisbos (Halle)", "Kluisbos (Kluisbergen)"]
    point, _ = resolve("Kluisbos, Kluisbergen")
    assert "candidates" not in point
    assert point["lon"] == 3.50
    gaz = copy.deepcopy(GAZETTEER)
    gaz["landmarks"] = gaz["landmarks"][:1]
    assert "candidates" not in geocode.resolve("Kluisbos", gazetteer=gaz, google_resolver=None)[0]
    gaz["landmarks"].append(("Kluisbos", "natural:wood", 50.761, 3.501))
    assert "candidates" not in geocode.resolve("Kluisbos", gazetteer=gaz, google_resolver=None)[0]


def _plan(start="Kluisbos", rond_plaats=None):
    state = {"id": "ambiguity", "name": "Kluisboslus", "start": resolve(start)[0],
             "loop": True, "climbs": [], "computed": None}
    calls = []
    saved = []
    def save(d):
        saved.append(copy.deepcopy(d))
    result = intents.plan_route(
        start, rond_plaats=rond_plaats, target_km=20, profiel_naam="standaard", check_readiness=True,
        create_fn=lambda **kwargs: {"id": state["id"]}, load_fn=lambda _: state,
        save_fn=save, climbs_fn=lambda: {}, resolve_fn=resolve,
        probe_fn=lambda *_: calls.append("probe"),
        assess_fn=lambda *_: {"klaar": False, "profiel": "standaard", "onbekend": ["heuvels"],
                             "vragen": [{"id": "heuvels"}], "advies": "Kies je voorkeur."},
        profile_load_fn=lambda _: {"voorkeuren": {}},
    )
    assert saved[-1]["open_vragen"] == result["vragen"]
    return state, result, calls


def test_plan_start_question_precedes_probe_and_retry():
    state, result, calls = _plan()
    assert result["status"] == "needs_input"
    assert [q["id"] for q in result["vragen"]] == ["startplaats"]
    assert result["vragen"][0]["vraag"] == "Welke Kluisbos bedoel je?"
    assert result["vragen"][0]["opties"]["1"]["patch"]["start"]["lon"] == 3.50
    assert calls == []
    state["route_request"]["request_id"] = "retry"
    again = intents.plan_route("Kluisbos", target_km=20, profiel_naam="standaard", check_readiness=True,
                               request_id="retry", find_request_fn=lambda _: state, save_fn=lambda _: None,
                               probe_fn=lambda *_: (_ for _ in ()).throw(AssertionError("probe before choice")))
    assert again["vragen"] == result["vragen"]


def test_plan_explicit_and_single_start_continue_to_terrain_questions():
    for start in ("Kluisbos, Kluisbergen", "Halle"):
        state, result, calls = _plan(start)
        assert result["vragen"] == [{"id": "heuvels"}]
        assert calls == ["probe"]


def _resume(state, *, ready=False):
    def adjust(draft_id, **kwargs):
        def probe(d, _db):
            assert d["start"]["lon"] == 3.50
            d["_probe"] = {"chosen_lon": d["start"]["lon"]}
        def route(d, _db, **kwargs):
            d["computed"] = {"total_km": 20, "ascend_m": 100, "legs": [], "kwaliteit": {}}
        with tempfile.TemporaryDirectory() as root:
            return intents.adjust_route(
                draft_id, **kwargs, load_fn=lambda _: state, save_fn=lambda _: None,
                climbs_fn=lambda: {}, probe_fn=probe, resolve_fn=resolve,
                assess_fn=lambda *_: {"klaar": ready, "profiel": "standaard", "onbekend": ["heuvels"],
                                     "vragen": [{"id": "heuvels"}], "advies": "Kies je voorkeur."},
                profile_load_fn=lambda _: {"voorkeuren": {}}, optimize_fn=route, route_fn=route,
                export_gpx_fn=lambda _d, _db, path: {"file": path},
                export_preview_fn=lambda _d, _db, path: {"file": path}, exports_root=Path(root),
            )
    return adjust


def test_answer_uses_saved_coordinates_and_restarts_probe_then_ready():
    for ready in (False, True):
        state, _, _ = _plan()
        state["_probe"] = {"stale": True}
        result = intents.apply_answers(state["id"], {"startplaats": "1"}, load_fn=lambda _: state,
                                       save_fn=lambda _: None, adjust_fn=_resume(state, ready=ready))
        assert state["start"] == {"label": "Kluisbos (Kluisbergen)", "lat": 50.76, "lon": 3.50}
        assert state["_probe"] == {"chosen_lon": 3.50}
        assert result["status"] == ("ready" if ready else "needs_input")
        if not ready:
            assert result["vragen"] == [{"id": "heuvels"}]


def test_answer_rejects_coordinates_unoffered_and_unasked_options():
    state, _, _ = _plan()
    for answers in ({"startplaats": {"lat": 50, "lon": 3}}, {"startplaats": "3"},
                    {"startplaats": "1", "heuvels": "zoek"}, {"heuvels": "zoek"}):
        before = copy.deepcopy(state)
        try:
            intents.apply_answers(state["id"], answers, load_fn=lambda _: state, save_fn=lambda _: None)
        except intents.IntentError:
            pass
        else:
            raise AssertionError("invalid place choice accepted")
        assert state == before
    state.pop("pending_places")
    try:
        intents.apply_answers(state["id"], {"startplaats": "1"}, load_fn=lambda _: state)
    except intents.IntentError:
        pass
    else:
        raise AssertionError("unasked choice accepted")


def test_ambiguous_anchor_and_start_are_chosen_sequentially():
    state, result, calls = _plan(rond_plaats="Kluisbos")
    assert len(state["pending_places"]) == 2
    result = intents.apply_answers(state["id"], {"startplaats": "1"}, load_fn=lambda _: state,
                                   save_fn=lambda _: None, adjust_fn=_resume(state))
    assert result["vragen"][0]["opties"]["1"]["patch"]["round_trip_anchor"]["lon"] == 3.50
    result = intents.apply_answers(state["id"], {"startplaats": "1"}, load_fn=lambda _: state,
                                   save_fn=lambda _: None, adjust_fn=_resume(state))
    assert state["round_trip_anchor"]["label"] == "Kluisbos (Kluisbergen)"
    assert result["vragen"] == [{"id": "heuvels"}]
    assert calls == []


def test_nearly_equal_names_same_rank_and_four_option_limit():
    gaz = copy.deepcopy(GAZETTEER)
    gaz["landmarks"] = [("Kluisbosjes", "natural:wood", 50.74, 4.26),
                        ("Kluisbosje", "natural:wood", 50.76, 3.50)]
    assert len(geocode.resolve("Kluisbos", gazetteer=gaz, google_resolver=None)[0]["candidates"]) == 2
    # Een exacte match wint van een langere naam, ook op grote afstand.
    gaz["landmarks"].append(("Kluisbos", "natural:wood", 50.80, 3.20))
    assert "candidates" not in geocode.resolve("Kluisbos", gazetteer=gaz, google_resolver=None)[0]
    hits = [{"label": "Kluisbos", "lat": 50.0, "lon": lon} for lon in (3, 3.2, 3.4, 3.6, 3.8, 4)]
    assert len(geocode.ambiguous_candidates("Kluisbos", hits, GAZETTEER)) == 4


def test_adjust_startplaats_uses_same_saved_candidates_for_chat_and_mcp():
    state, _, _ = _plan()
    result = intents.adjust_route(
        state["id"], startplaats="1", load_fn=lambda _: state, save_fn=lambda _: None,
        climbs_fn=lambda: {}, probe_fn=lambda *_: None,
        assess_fn=lambda *_: {"klaar": False, "profiel": "standaard", "onbekend": ["heuvels"],
                             "vragen": [{"id": "heuvels"}], "advies": "Kies je voorkeur."},
        profile_load_fn=lambda _: {"voorkeuren": {}},
    )
    assert state["start"]["lon"] == 3.50
    assert result["vragen"] == [{"id": "heuvels"}]


def test_place_answer_without_preference_profile_can_continue_without_readiness():
    state, _, _ = _plan()
    state["route_request"]["profiel_naam"] = None
    calls = []
    intents.apply_answers(state["id"], {"startplaats": "1"}, load_fn=lambda _: state,
                          save_fn=lambda _: None,
                          adjust_fn=lambda _id, **kwargs: calls.append(kwargs) or {"status": "ready"})
    assert calls == [{"doel": "toeren", "check_readiness": False}]
    assert state["start"]["lon"] == 3.50
