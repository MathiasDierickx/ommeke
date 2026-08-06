"""Pure tests voor de token-zuinige composiet-intenties."""

import tempfile
from pathlib import Path

from lusmaker import intents


def _climb(climb_id, name, length_m=1000, avg_pct=4.0):
    return {
        "id": climb_id,
        "name": name,
        "length_m": length_m,
        "avg_pct": avg_pct,
    }


def _climbs():
    return {
        "molenberg": _climb("molenberg", "Molenberg"),
        "molenbeekberg": _climb("molenbeekberg", "Molenbeekberg"),
        "kampenheuvel": _climb("kampenheuvel", "Kampenheuvel", 600, 4.3),
        "diepestraat": _climb("diepestraat", "Diepestraat", 1100, 3.5),
    }


def _routed_draft():
    return {
        "id": "abc123",
        "name": "testlus",
        "start": {"label": "Wetteren", "lat": 50.0, "lon": 4.0},
        "loop": True,
        "climbs": ["diepestraat", "kampenheuvel"],
        "avoid_cobbles": True,
        "computed": {
            "total_km": 44.0,
            "ascend_m": 559,
            "legs": [{"from": "start", "to": "Diepestraat", "km": 8.0}],
            "kwaliteit": {
                "kassei_m": 0,
                "steenweg_m": 900,
                "steenweg_kruisingen": 7,
                "populair_pct": 73,
            },
        },
    }


def test_match_climb_prefers_exact_then_prefix_then_substring():
    db = _climbs()

    assert intents.match_climb("Molenberg", db)["id"] == "molenberg"
    assert intents.match_climb("kampen", db)["id"] == "kampenheuvel"
    assert intents.match_climb("straat", db)["id"] == "diepestraat"


def test_match_climb_reports_ambiguous_candidates():
    try:
        intents.match_climb("molenb", _climbs())
    except intents.IntentError as exc:
        message = str(exc)
        assert "niet eenduidig" in message
        assert "Molenberg" in message
        assert "Molenbeekberg" in message
    else:
        raise AssertionError("ambigue klimnaam werd aanvaard")


def test_match_climb_unknown_reports_three_suggestions():
    try:
        intents.match_climb("onbekend", _climbs())
    except intents.IntentError as exc:
        suggestions = str(exc).split("bedoelde je: ", 1)[1].rstrip("?").split(", ")
        assert len(suggestions) == 3
    else:
        raise AssertionError("onbekende klimnaam werd aanvaard")


def test_compact_output_contract_and_summary():
    result = intents.compact_result(
        _routed_draft(),
        _climbs(),
        {"gpx": "/tmp/test.gpx", "preview": "/tmp/test.html"},
    )

    assert set(result) == {
        "draft",
        "km",
        "hoogtemeters",
        "klimmen",
        "kwaliteit",
        "bestanden",
        "samenvatting",
        "vervolg",
    }
    assert result["klimmen"] == [
        "Diepestraat (1.1 km @ 3.5%)",
        "Kampenheuvel (0.6 km @ 4.3%)",
    ]
    assert result["kwaliteit"] == (
        "0 m kassei · 0.9 km steenweg · 7 kruisingen · 73% populaire wegen"
    )
    assert result["samenvatting"] == (
        "Lus vanuit Wetteren: 44,0 km / +559 hm langs 2 klimmen; "
        "kasseien vermeden."
    )


def test_plan_route_injects_route_and_export_functions():
    state = {
        "id": "abc123",
        "name": "testlus",
        "start": {"label": "Wetteren", "lat": 50.0, "lon": 4.0},
        "loop": True,
        "climbs": [],
        "avoid_cobbles": False,
        "computed": None,
    }
    calls = []

    def create_fn(**kwargs):
        state["avoid_cobbles"] = kwargs["avoid_cobbles"]
        state["profile"] = kwargs["profile"]
        return {"id": state["id"]}

    def add_climb_fn(_draft_id, climb_id):
        state["climbs"].append(climb_id)

    def route_fn(d, _db):
        calls.append("route")
        d["computed"] = _routed_draft()["computed"]

    def export_fn(_d, _db, path):
        calls.append(Path(path).suffix)
        return {"file": path}

    with tempfile.TemporaryDirectory() as temp_dir:
        result = intents.plan_route(
            "Wetteren",
            doel="kort",
            activiteit="trail",
            via_klimmen=["Diepestraat"],
            create_fn=create_fn,
            load_fn=lambda _draft_id: state,
            add_climb_fn=add_climb_fn,
            climbs_fn=_climbs,
            route_fn=route_fn,
            export_gpx_fn=export_fn,
            export_preview_fn=export_fn,
            exports_root=Path(temp_dir),
        )

    assert calls == ["route", ".gpx", ".html"]
    assert state["avoid_cobbles"] is True
    assert state["profile"] == "trail"
    assert result["draft"] == "abc123"


def test_plan_route_passes_no_fill_to_optimizer():
    state = _routed_draft()
    state["climbs"] = []
    optimize_calls = []

    def optimize_fn(d, _db, **kwargs):
        optimize_calls.append(kwargs)
        d["computed"] = _routed_draft()["computed"]

    def export_fn(_d, _db, path):
        return {"file": path}

    with tempfile.TemporaryDirectory() as temp_dir:
        intents.plan_route(
            "Wetteren",
            max_km=10,
            geen_opvulling=True,
            create_fn=lambda **_kwargs: {"id": state["id"]},
            load_fn=lambda _draft_id: state,
            optimize_fn=optimize_fn,
            climbs_fn=_climbs,
            export_gpx_fn=export_fn,
            export_preview_fn=export_fn,
            exports_root=Path(temp_dir),
        )

    assert optimize_calls == [{"max_km": 10, "fill": False}]


def test_adjust_route_batches_edits_before_one_reroute():
    state = _routed_draft()
    state["climbs"] = ["diepestraat"]
    edits = []

    def add_fn(_draft_id, climb_id):
        edits.append(("add", climb_id))
        state["climbs"].append(climb_id)
        state["computed"] = None

    def remove_fn(_draft_id, climb_id):
        edits.append(("remove", climb_id))
        state["climbs"].remove(climb_id)
        state["computed"] = None

    def avoid_fn(_draft_id, place):
        edits.append(("avoid", place))
        state["computed"] = None

    def unavoid_fn(_draft_id, place):
        edits.append(("unavoid", place))
        state["computed"] = None

    route_calls = []

    def route_fn(d, _db):
        route_calls.append(list(edits))
        d["computed"] = _routed_draft()["computed"]

    def export_fn(_d, _db, path):
        return {"file": path}

    with tempfile.TemporaryDirectory() as temp_dir:
        intents.adjust_route(
            "abc123",
            voeg_klimmen_toe=["Kampenheuvel"],
            verwijder_klimmen=["Diepestraat"],
            vermijd_plaatsen=["Zottegem"],
            niet_meer_vermijden=["Oudenaarde"],
            load_fn=lambda _draft_id: state,
            add_climb_fn=add_fn,
            remove_climb_fn=remove_fn,
            avoid_place_fn=avoid_fn,
            unavoid_place_fn=unavoid_fn,
            route_fn=route_fn,
            climbs_fn=_climbs,
            export_gpx_fn=export_fn,
            export_preview_fn=export_fn,
            exports_root=Path(temp_dir),
        )

    assert len(route_calls) == 1
    assert route_calls[0] == [
        ("remove", "diepestraat"),
        ("add", "kampenheuvel"),
        ("avoid", "Zottegem"),
        ("unavoid", "Oudenaarde"),
    ]


def test_route_details_without_computed_is_clear_error():
    try:
        intents.route_details(
            "leeg01",
            load_fn=lambda _draft_id: {"id": "leeg01", "computed": None},
        )
    except intents.IntentError as exc:
        assert "nog geen berekende route" in str(exc)
        assert "routeer eerst" in str(exc)
    else:
        raise AssertionError("ongerouteerde draft kreeg details")
