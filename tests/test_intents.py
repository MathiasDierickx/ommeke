"""Pure tests voor de token-zuinige composiet-intenties."""

import tempfile
from pathlib import Path

from lusmaker import artifacts, config, draft, geo, intents


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
        "status",
        "draft",
        "revision",
        "request_id",
        "km",
        "hoogtemeters",
        "klimmen",
        "kwaliteit",
        "bestanden",
        "samenvatting",
        "vervolg",
        "artifacts",
        "constraints",
    }
    assert result["status"] == "ready"
    assert result["revision"] == 0
    assert result["request_id"] is None
    assert result["constraints"]["voldaan"] is None
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
    assert [item["type"] for item in result["artifacts"]] == ["gpx", "preview"]
    assert result["artifacts"][0]["uri"] == (
        "lusmaker://drafts/abc123/route.gpx"
    )


def test_compact_output_adds_one_underway_line_when_pois_are_present():
    state = _routed_draft()
    state["_probe"] = {
        "terrein": {
            "pois_langs_route": {
                "toilet": 1,
                "uitkijktoren": 1,
                "picknickbank": 2,
            }
        }
    }

    result = intents.compact_result(
        state,
        _climbs(),
        {"gpx": "/tmp/test.gpx", "preview": "/tmp/test.html"},
    )

    assert result["onderweg"] == (
        "2 picknickbanken, 1 uitkijktoren, toilet"
    )


def test_suggest_route_name_summarises_place_character_and_distance():
    assert intents.suggest_route_name(
        "Wetteren station",
        target_km=None,
        max_km=38,
        doel="hoogtemeters",
        activiteit="fietsen",
    ) == "Heuvelrit rond Wetteren station · 38 km"
    assert intents.suggest_route_name(
        "50.8,3.7",
        target_km=12,
        max_km=None,
        doel="toeren",
        activiteit="trail",
    ) == "Traillus rond je startpunt · 12 km"


def test_heat_activity_for_maps_activity_and_profile_name():
    assert intents.heat_activity_for("trail", "race") == "trail"
    assert intents.heat_activity_for("fietsen", "snelle koers") == "koersfiets"
    assert intents.heat_activity_for("fietsen", "RACE") == "koersfiets"
    assert intents.heat_activity_for("fietsen", "gravel avontuur") == "gravel"
    assert intents.heat_activity_for("fietsen", "mtb technisch") == "mtb"
    assert intents.heat_activity_for("fietsen", None) == "stadsfiets"
    assert intents.heat_activity_for("wandelen", "standaard") is None


def test_plan_route_injects_route_and_export_functions():
    state = {
        "id": "abc123",
        "name": "testlus",
        "start": {"label": "Wetteren", "lat": 50.0, "lon": 4.0},
        "loop": True,
        "climbs": [],
        "avoid_cobbles": False,
        "avoid_busy": False,
        "computed": None,
    }
    calls = []

    def create_fn(**kwargs):
        state["avoid_cobbles"] = kwargs["avoid_cobbles"]
        state["avoid_busy"] = kwargs["avoid_busy"]
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
            autovrij=True,
            via_klimmen=["Diepestraat"],
            create_fn=create_fn,
            load_fn=lambda _draft_id: state,
            add_climb_fn=add_climb_fn,
            climbs_fn=_climbs,
            route_fn=route_fn,
            export_gpx_fn=export_fn,
            export_preview_fn=export_fn,
            save_fn=lambda _d: None,
            exports_root=Path(temp_dir),
        )

    assert calls == ["route", ".gpx", ".html"]
    assert state["avoid_cobbles"] is True
    assert state["avoid_busy"] is True
    assert state["profile"] == "trail"
    assert result["draft"] == "abc123"


def test_plan_route_export_helper_returns_http_urls_in_delivery_scope():
    def export_fn(_draft, _climbs, path):
        Path(path).write_text("artifact", encoding="utf-8")

    with tempfile.TemporaryDirectory() as temp_dir:
        with (
            config.user_scope("alice"),
            artifacts.delivery_mode(
                True, public_url="https://routes.example.test"
            ),
        ):
            files = intents._export_files(
                {"id": "abc123"},
                {},
                export_gpx_fn=export_fn,
                export_preview_fn=export_fn,
                exports_root=Path(temp_dir),
            )

    assert files == {
        "gpx": "https://routes.example.test/files/alice/abc123/route.gpx",
        "preview": (
            "https://routes.example.test/files/alice/abc123/preview.html"
        ),
    }


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
            save_fn=lambda _d: None,
            exports_root=Path(temp_dir),
        )

    assert optimize_calls == [{"max_km": 10, "fill": False}]


def test_plan_route_resolves_landmark_and_passes_it_as_round_trip_anchor():
    state = _routed_draft()
    state["climbs"] = []
    state["computed"] = None
    optimize_calls = []

    def resolve_fn(query):
        assert query == "Blaarmeersen, Gent"
        return (
            {"label": "Blaarmeersen", "lat": 51.039, "lon": 3.700},
            [],
        )

    def optimize_fn(d, _db, **kwargs):
        optimize_calls.append(kwargs)
        assert d["round_trip_anchor"]["label"] == "Blaarmeersen"
        d["computed"] = _routed_draft()["computed"] | {"total_km": 5.0}

    def export_fn(_d, _db, path):
        return {"file": path}

    with tempfile.TemporaryDirectory() as temp_dir:
        result = intents.plan_route(
            "Blaarmeersen",
            rond_plaats="Blaarmeersen, Gent",
            target_km=5,
            activiteit="trail",
            create_fn=lambda **_kwargs: {"id": state["id"]},
            load_fn=lambda _draft_id: state,
            optimize_fn=optimize_fn,
            climbs_fn=lambda: {},
            export_gpx_fn=export_fn,
            export_preview_fn=export_fn,
            save_fn=lambda _d: None,
            resolve_fn=resolve_fn,
            exports_root=Path(temp_dir),
        )

    assert optimize_calls == [
        {
            "max_km": 7.5,
            "fill": True,
            "objective": "offroad",
            "fill_target_km": 5,
        }
    ]
    assert result["status"] == "ready"
    assert state["route_request"]["rond_plaats"] == "Blaarmeersen, Gent"


def test_plan_route_defaults_landmark_loop_to_five_km():
    state = _routed_draft()
    state["climbs"] = []
    state["computed"] = None
    calls = []

    def optimize_fn(d, _db, **kwargs):
        calls.append(kwargs)
        d["computed"] = _routed_draft()["computed"] | {"total_km": 5.0}

    def export_fn(_d, _db, path):
        return {"file": path}

    with tempfile.TemporaryDirectory() as temp_dir:
        intents.plan_route(
            "Blaarmeersen",
            rond_plaats="Blaarmeersen",
            create_fn=lambda **_kwargs: {"id": state["id"]},
            load_fn=lambda _draft_id: state,
            optimize_fn=optimize_fn,
            climbs_fn=lambda: {},
            export_gpx_fn=export_fn,
            export_preview_fn=export_fn,
            save_fn=lambda _d: None,
            resolve_fn=lambda _query: (
                {"label": "Blaarmeersen", "lat": 51.039, "lon": 3.700},
                [],
            ),
            exports_root=Path(temp_dir),
        )

    assert calls[0]["fill_target_km"] == 5.0
    assert calls[0]["max_km"] == 7.5


def test_water_via_points_follow_longest_direction_for_half_target():
    river = [(51.0, 3.0 + index * 0.01) for index in range(11)]
    start = (51.001, 3.04)

    first = draft.water_via_points(start, [river], 6)
    second = draft.water_via_points(start, [river], 6)

    assert first == second
    assert draft.water_via_points(start, [], 6) == []
    assert len(first) == 8
    assert all(abs(lat - 51.0) < 1e-9 for lat, _lon in first)
    assert first[0][1] == 3.04
    assert all(a[1] <= b[1] for a, b in zip(first, first[1:]))
    assert 2_950 <= geo.path_length(first) <= 3_050


def test_plan_route_passes_waterway_via_points_to_router_without_optimizing():
    river = [(51.0, 3.0 + index * 0.01) for index in range(11)]
    state = {
        "id": "water1",
        "name": "waterlus",
        "start": {"label": "Teststad", "lat": 51.001, "lon": 3.05},
        "loop": True,
        "climbs": [],
        "avoid_places": [],
        "computed": None,
    }
    routed_points = []

    def route_fn(d, climb_db):
        legs = draft._waypoints(d, climb_db)
        routed_points.extend(legs[0]["points"])
        assert legs[-1]["to"] == "start"
        d["computed"] = _routed_draft()["computed"] | {"total_km": 6.1}

    def unexpected(*_args, **_kwargs):
        raise AssertionError("een waterlooproute mag de optimizer niet gebruiken")

    def export_fn(_d, _db, path):
        return {"file": path}

    with tempfile.TemporaryDirectory() as temp_dir:
        intents.plan_route(
            "Teststad",
            target_km=6,
            langs_water="Testrivier",
            rond_plaats="Genegeerde plek",
            create_fn=lambda **_kwargs: {"id": state["id"]},
            load_fn=lambda _draft_id: state,
            route_fn=route_fn,
            optimize_fn=unexpected,
            climbs_fn=lambda: {},
            export_gpx_fn=export_fn,
            export_preview_fn=export_fn,
            save_fn=lambda _d: None,
            resolve_fn=unexpected,
            water_fn=lambda name: [river] if name == "Testrivier" else [],
            exports_root=Path(temp_dir),
        )

    via = state["water_via"]
    assert routed_points == [
        (state["start"]["lat"], state["start"]["lon"]),
        *via,
    ]
    assert all(abs(lat - 51.0) < 1e-9 for lat, _lon in via)
    assert 2_950 <= geo.path_length(via) <= 3_050
    assert state["route_request"]["langs_water"] == "Testrivier"
    assert state["route_request"]["input_signature"]["langs_water"] == "Testrivier"


def test_adjust_route_replaces_waterway_via_before_one_reroute():
    river = [(51.0, 3.0 + index * 0.01) for index in range(11)]
    state = _routed_draft()
    state["climbs"] = []
    state["route_request"] = {
        "doel": "hoogtemeters",
        "target_km": 6,
        "max_km": 8.5,
        "max_km_explicit": False,
        "tolerance_km": 2.5,
        "geen_opvulling": False,
    }
    calls = []

    def route_fn(d, _db):
        calls.append(list(d["water_via"]))
        d["computed"] = _routed_draft()["computed"] | {"total_km": 6.0}

    def unexpected(*_args, **_kwargs):
        raise AssertionError("een waterlooproute mag de optimizer niet gebruiken")

    def export_fn(_d, _db, path):
        return {"file": path}

    with tempfile.TemporaryDirectory() as temp_dir:
        intents.adjust_route(
            "abc123",
            langs_water="Testrivier",
            load_fn=lambda _draft_id: state,
            route_fn=route_fn,
            optimize_fn=unexpected,
            climbs_fn=lambda: {},
            export_gpx_fn=export_fn,
            export_preview_fn=export_fn,
            save_fn=lambda _d: None,
            water_fn=lambda _name: [river],
            exports_root=Path(temp_dir),
        )

    assert calls == [state["water_via"]]
    assert state["route_request"]["langs_water"] == "Testrivier"


def test_plan_route_without_waterway_data_falls_back_to_normal_route():
    state = _routed_draft()
    state["climbs"] = []
    state["computed"] = None
    calls = []

    def route_fn(d, _db):
        calls.append("route")
        assert not d.get("water_via")
        d["computed"] = _routed_draft()["computed"] | {"total_km": 6.0}

    def export_fn(_d, _db, path):
        return {"file": path}

    with tempfile.TemporaryDirectory() as temp_dir:
        intents.plan_route(
            "Teststad",
            target_km=6,
            doel="kort",
            langs_water="Onbekende rivier",
            create_fn=lambda **_kwargs: {"id": state["id"]},
            load_fn=lambda _draft_id: state,
            route_fn=route_fn,
            climbs_fn=lambda: {},
            export_gpx_fn=export_fn,
            export_preview_fn=export_fn,
            save_fn=lambda _d: None,
            water_fn=lambda _name: [],
            exports_root=Path(temp_dir),
        )

    assert calls == ["route"]


def test_plan_route_passes_named_preference_profile_to_draft():
    state = _routed_draft()
    captured = {}

    def create_fn(**kwargs):
        captured.update(kwargs)
        return {"id": state["id"]}

    def route_fn(d, _db):
        d["computed"] = _routed_draft()["computed"]

    def export_fn(_d, _db, path):
        return {"file": path}

    with tempfile.TemporaryDirectory() as temp_dir:
        intents.plan_route(
            "Wetteren",
            doel="kort",
            profiel_naam="gravel",
            create_fn=create_fn,
            load_fn=lambda _draft_id: state,
            route_fn=route_fn,
            climbs_fn=_climbs,
            export_gpx_fn=export_fn,
            export_preview_fn=export_fn,
            save_fn=lambda _d: None,
            exports_root=Path(temp_dir),
        )

    assert captured["profile_doc"] == "gravel"


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
            save_fn=lambda _d: None,
            exports_root=Path(temp_dir),
        )

    assert len(route_calls) == 1
    assert route_calls[0] == [
        ("remove", "diepestraat"),
        ("add", "kampenheuvel"),
        ("avoid", "Zottegem"),
        ("unavoid", "Oudenaarde"),
    ]


def test_adjust_route_forwards_offroad_goal_to_optimizer():
    state = _routed_draft()
    state["route_request"] = {
        "doel": "hoogtemeters",
        "target_km": 40,
        "max_km": 42.5,
        "tolerance_km": 2.5,
        "geen_opvulling": False,
    }
    calls = []

    def optimize_fn(d, _db, **kwargs):
        calls.append(kwargs)
        d["computed"] = _routed_draft()["computed"]

    def export_fn(_d, _db, path):
        return {"file": path}

    with tempfile.TemporaryDirectory() as temp_dir:
        intents.adjust_route(
            "abc123",
            doel="offroad",
            load_fn=lambda _draft_id: state,
            optimize_fn=optimize_fn,
            climbs_fn=_climbs,
            export_gpx_fn=export_fn,
            export_preview_fn=export_fn,
            save_fn=lambda _d: None,
            exports_root=Path(temp_dir),
        )

    assert calls == [
        {
            # Zacht doel (geen expliciete max_km): de optimizer krijgt marge
            # (target*1.2) zodat een round-trip die het doel licht overschrijdt
            # niet hard faalt; fill_target_km blijft het eigenlijke doel.
            "max_km": 48.0,
            "fill": True,
            "objective": "offroad",
            "fill_target_km": 40,
        }
    ]


def test_adjust_route_replaces_round_trip_anchor_before_rerouting():
    state = _routed_draft()
    state["climbs"] = []
    calls = []

    def optimize_fn(d, _db, **kwargs):
        calls.append(kwargs)
        assert d["round_trip_anchor"] == {
            "label": "Blaarmeersen",
            "lat": 51.039,
            "lon": 3.700,
        }
        d["computed"] = _routed_draft()["computed"] | {"total_km": 5.0}

    def export_fn(_d, _db, path):
        return {"file": path}

    with tempfile.TemporaryDirectory() as temp_dir:
        intents.adjust_route(
            "abc123",
            rond_plaats="Blaarmeersen, Gent",
            target_km=5,
            load_fn=lambda _draft_id: state,
            optimize_fn=optimize_fn,
            climbs_fn=lambda: {},
            export_gpx_fn=export_fn,
            export_preview_fn=export_fn,
            save_fn=lambda _d: None,
            resolve_fn=lambda query: (
                {"label": "Blaarmeersen", "lat": 51.039, "lon": 3.700},
                [],
            ),
            exports_root=Path(temp_dir),
        )

    assert calls == [
        {
            "max_km": 7.5,
            "fill": True,
            "objective": "toeren",
            "fill_target_km": 5,
        }
    ]
    assert state["route_request"]["rond_plaats"] == "Blaarmeersen, Gent"


def test_plan_route_stops_at_needs_input_before_optimization_and_export():
    state = {
        "id": "ask123",
        "name": "vraaglus",
        "start": {"label": "Wetteren", "lat": 50.0, "lon": 4.0},
        "end": None,
        "loop": True,
        "climbs": [],
        "avoid_places": [],
        "computed": None,
    }
    calls = []

    def probe_fn(d, _db):
        calls.append("probe")
        d["_probe"] = {"km": 15, "kwaliteit": {}, "terrein": {}}

    def assess_fn(_d, profile, _db):
        assert profile["voorkeuren"]["kasseien"] is None
        return {
            "profiel": profile["naam"],
            "onbekend": ["kasseien"],
            "vragen": [{"id": "kasseien", "vraag": "Kasseien?"}],
            "klaar": False,
            "advies": "stel de kasseivraag eerst",
        }

    def unexpected(*_args, **_kwargs):
        raise AssertionError("needs_input mag nog niet routeeren of exporteren")

    result = intents.plan_route(
        "Wetteren",
        target_km=50,
        profiel_naam="standaard",
        check_readiness=True,
        kasseien=None,
        beton_vermijden=None,
        strict=None,
        create_fn=lambda **_kwargs: {"id": state["id"]},
        load_fn=lambda _draft_id: state,
        climbs_fn=_climbs,
        save_fn=lambda _d: None,
        probe_fn=probe_fn,
        assess_fn=assess_fn,
        profile_load_fn=lambda name: {
            "naam": name,
            "activiteit": "fietsen",
            "gewichten": {},
            "voorkeuren": {
                "kasseien": None,
                "beton": None,
                "steenwegen": None,
                "autovrij": None,
                "vermijd_plaatsen": [],
            },
        },
        route_fn=unexpected,
        optimize_fn=unexpected,
        export_gpx_fn=unexpected,
        export_preview_fn=unexpected,
    )

    assert calls == ["probe"]
    assert result["status"] == "needs_input"
    assert result["draft"] == "ask123"
    assert result["constraints"]["doel_km"] == 50
    assert result["constraints"]["maximum_km"] == 52.5
    assert result["next_action"]["ga_daarna_verder_met"] == "adjust_route"


def test_plan_route_targets_tour_distance_and_reports_constraints():
    state = {
        "id": "tour50",
        "name": "toerlus",
        "start": {"label": "Wetteren", "lat": 50.0, "lon": 4.0},
        "end": None,
        "loop": True,
        "climbs": [],
        "avoid_places": [],
        "computed": None,
    }
    optimize_calls = []

    def optimize_fn(d, _db, **kwargs):
        optimize_calls.append(kwargs)
        d["computed"] = _routed_draft()["computed"] | {"total_km": 49.0}

    def export_fn(_d, _db, path):
        return {"file": path}

    with tempfile.TemporaryDirectory() as temp_dir:
        result = intents.plan_route(
            "Wetteren",
            target_km=50,
            doel="toeren",
            profiel_naam="standaard",
            check_readiness=True,
            kasseien=None,
            beton_vermijden=None,
            strict=None,
            create_fn=lambda **_kwargs: {"id": state["id"]},
            load_fn=lambda _draft_id: state,
            climbs_fn=_climbs,
            save_fn=lambda _d: None,
            probe_fn=lambda d, _db: d.update({"_probe": {}}),
            assess_fn=lambda _d, profile, _db: {
                "profiel": profile["naam"],
                "onbekend": [],
                "vragen": [],
                "klaar": True,
                "advies": "klaar",
            },
            profile_load_fn=lambda name: {
                "naam": name,
                "activiteit": "fietsen",
                "gewichten": {},
                "voorkeuren": {
                    "kasseien": "ok",
                    "beton": "ok",
                    "steenwegen": "ok",
                    "vermijd_plaatsen": [],
                },
            },
            optimize_fn=optimize_fn,
            export_gpx_fn=export_fn,
            export_preview_fn=export_fn,
            exports_root=Path(temp_dir),
        )

    assert optimize_calls == [
        {
            # Zacht doel: optimizer-plafond krijgt marge (target*1.2 = 60);
            # de gerapporteerde constraints blijven op het doelbudget gebaseerd.
            "max_km": 60.0,
            "fill": True,
            "objective": "toeren",
            "fill_target_km": 50,
        }
    ]
    assert result["status"] == "ready"
    assert result["constraints"]["binnen_doelbereik"] is True
    assert result["constraints"]["binnen_maximum"] is True
    assert result["constraints"]["voldaan"] is True


def test_plan_route_request_id_reuses_completed_draft_without_rerouting():
    state = _routed_draft()
    state["revision"] = 7
    signature = {
        "start": "Wetteren",
        "region": None,
        "via_klimmen": [],
        "vermijd_plaatsen": [],
        "naam": None,
        "doel": "toeren",
        "target_km": 50,
        "max_km": None,
        "tolerance_km": 2.5,
        "geen_opvulling": False,
        "profiel_naam": "standaard",
        "activiteit": "fietsen",
        "kasseien": None,
        "beton_vermijden": None,
        "strict": None,
    }
    state["route_request"] = {
        "request_id": "prompt-123",
        "input_signature": signature,
        "doel": "toeren",
        "target_km": 50,
        "max_km": 52.5,
        "tolerance_km": 2.5,
    }
    calls = []

    def export_fn(_d, _db, path):
        calls.append(Path(path).suffix)
        return {"file": path}

    def unexpected(*_args, **_kwargs):
        raise AssertionError("een retry van een voltooide request mag niet rerouteren")

    with tempfile.TemporaryDirectory() as temp_dir:
        result = intents.plan_route(
            "Wetteren",
            target_km=50,
            doel="toeren",
            profiel_naam="standaard",
            check_readiness=True,
            request_id="prompt-123",
            kasseien=None,
            beton_vermijden=None,
            strict=None,
            find_request_fn=lambda _request_id: state,
            climbs_fn=_climbs,
            route_fn=unexpected,
            optimize_fn=unexpected,
            export_gpx_fn=export_fn,
            export_preview_fn=export_fn,
            exports_root=Path(temp_dir),
        )

    assert calls == [".gpx", ".html"]
    assert result["draft"] == "abc123"
    assert result["revision"] == 7
    assert result["request_id"] == "prompt-123"


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
