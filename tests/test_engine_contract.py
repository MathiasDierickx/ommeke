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


def test_soft_target_keeps_a_slightly_long_route_with_a_warning_instead_of_failing():
    state = _state() | {"computed": None}
    calls = []

    def optimize_fn(d, _db, **kwargs):
        calls.append(kwargs["max_km"])
        d["computed"] = _state()["computed"] | {"total_km": 25.4}
        from lusmaker import draft as draft_mod
        raise draft_mod.DraftError("De route wordt 25,4 km, langer dan je maximum van 24 km.")

    with tempfile.TemporaryDirectory() as tmp:
        result = intents.plan_route(
            "Oudenaarde", target_km=20, tolerance_km=2, activiteit="gravel",
            create_fn=lambda **_k: {"id": "abc123"}, load_fn=lambda _i: state,
            optimize_fn=optimize_fn, climbs_fn=dict, export_gpx_fn=_export,
            export_preview_fn=_export, save_fn=lambda _d: None, exports_root=Path(tmp),
        )
    assert calls == [24.0, 24.0]  # eerste poging en terugval op hetzelfde plafond, nooit 1,6x
    assert result["status"] == "ready" and result["km"] == 25.4
    assert result["constraints"]["binnen_doelbereik"] is False
    assert any("langer" in w for w in result["constraints"]["waarschuwingen"])


def test_routing_draft_errors_are_400_not_404():
    from lusmaker import draft as draft_mod
    import json as _json
    too_long = aws_api._draft_error(draft_mod.DraftError("De route wordt 25,4 km, langer dan je maximum van 22 km."))
    missing = aws_api._draft_error(draft_mod.DraftError("draft 'x' bestaat niet — zie `lus draft list`"))
    assert too_long.status_code == 400 and _json.loads(too_long.body)["code"] == "route_failed"
    assert missing.status_code == 404 and _json.loads(missing.body)["code"] == "route_not_found"


def test_goal_is_never_pushed_out_by_answer_criteria():
    from lusmaker import criteria as crit
    quiet_only = crit.parse([{"metriek": "stil", "drempel": 0.6}])
    merged = crit.with_goal(quiet_only, "hoogtemeters")
    assert [(c["metriek"], round(c["gewicht"], 2)) for c in merged] == [("stil", 0.33), ("hoogtemeters", 0.67)]
    assert crit.with_goal(quiet_only, "toeren") == quiet_only
    assert crit.with_goal(None, "offroad")[0]["metriek"] == "offroad"
    # al aanwezig: ongewijzigd
    both = crit.parse([{"metriek": "stil"}, {"metriek": "hoogtemeters", "richting": "laag"}])
    assert crit.with_goal(both, "hoogtemeters") == both

    state = _state() | {"computed": None, "route_request": None}
    calls = []

    def optimize_fn(d, _db, **kwargs):
        calls.append(kwargs["objective"])
        d["computed"] = _state()["computed"]

    with tempfile.TemporaryDirectory() as tmp:
        intents.plan_route(
            "Wetteren", target_km=36, doel="hoogtemeters", activiteit="koersfiets",
            criteria=[{"metriek": "stil", "drempel": 0.6}],
            create_fn=lambda **_k: {"id": "abc123"}, load_fn=lambda _i: state,
            optimize_fn=optimize_fn, climbs_fn=dict, export_gpx_fn=_export,
            export_preview_fn=_export, save_fn=lambda _d: None, exports_root=Path(tmp),
        )
    assert [c["metriek"] for c in calls[0]["criteria"]] == ["stil", "hoogtemeters"]


def test_anchor_may_use_at_most_70_percent_of_the_budget():
    from lusmaker import optimizer
    start = {"lat": 51.0, "lon": 3.87}
    far = {"id": "far", "foot": [50.80, 3.87], "length_m": 800, "gain_m": 120}    # ~22 km hemelsbreed
    near = {"id": "near", "foot": [50.93, 3.87], "length_m": 600, "gain_m": 60}   # ~8 km
    assert optimizer._pick_anchor(start, {"far": far, "near": near}, max_km=72)["id"] == "near"


def test_soft_target_fallback_is_a_pure_loop_and_never_keeps_far_overshoot():
    state = _state() | {"computed": None}
    calls = []

    def optimize_fn(d, _db, **kwargs):
        calls.append(kwargs.get("max_rounds"))
        d["computed"] = _state()["computed"] | {"total_km": 89.4}
        from lusmaker import draft as draft_mod
        raise draft_mod.DraftError("De route wordt 89,4 km, langer dan je maximum van 72 km.")

    try:
        intents.plan_route(
            "Wetteren", target_km=60, doel="hoogtemeters", activiteit="koersfiets",
            create_fn=lambda **_k: {"id": "abc123"}, load_fn=lambda _i: state,
            optimize_fn=optimize_fn, climbs_fn=dict, export_gpx_fn=_export,
            export_preview_fn=_export, save_fn=lambda _d: None,
        )
    except Exception as exc:  # DraftError of IntentError: in elk geval geen 89 km als klaar
        assert "89,4" in str(exc)
    else:
        raise AssertionError("89 km voor 60 km mag niet als klaar terugkomen")
    assert calls == [None, 0]  # eerste poging normaal, terugval zonder klimrondes


def test_refreshed_auto_name_is_persisted():
    state = _state() | {"computed": None, "name": "Rondrit rond Wetteren · 9 km", "name_auto": True}
    saved = []

    def optimize_fn(d, _db, **_k):
        d["computed"] = _state()["computed"] | {"total_km": 34.1}

    intents._execute_request(state, {}, {"doel": "toeren", "target_km": 35, "max_km": 42, "max_km_explicit": False,
                                         "tolerance_km": 2.5, "geen_opvulling": False},
                             route_fn=lambda *_a: None, optimize_fn=optimize_fn,
                             persist_fn=lambda d: saved.append(d["name"]), pois_fn=lambda _d: [])
    assert state["name"] == "Rondrit rond Wetteren · 34 km" and saved[-1] == state["name"]


def test_water_with_a_place_heads_to_the_place_and_returns_along_the_water():
    from lusmaker import draft as draft_mod
    river = [(51.0, 3.5 + index * 0.01) for index in range(11)]   # west-oost, 3.50 .. 3.60
    state = {"id": "w2", "name": "x", "start": {"label": "Teststad", "lat": 51.001, "lon": 3.55},
             "loop": True, "climbs": [], "avoid_places": [], "computed": None}
    seen = {}

    def route_fn(d, db):
        seen["legs"] = draft_mod._waypoints(d, db)
        d["computed"] = _state()["computed"] | {"total_km": 11.0}

    with tempfile.TemporaryDirectory() as tmp:
        intents.plan_route(
            "Teststad", target_km=6, activiteit="wandelen", langs_water="Testrivier", rond_plaats="Meer",
            create_fn=lambda **_k: {"id": "w2"}, load_fn=lambda _i: state, route_fn=route_fn,
            optimize_fn=lambda *_a, **_k: None, climbs_fn=dict, export_gpx_fn=_export,
            export_preview_fn=_export, save_fn=lambda _d: None, exports_root=Path(tmp),
            resolve_fn=lambda _q: ({"label": "Meer", "lat": 51.004, "lon": 3.505}, []),
            water_fn=lambda _name: [river],
        )
    via = state["water_via"]
    assert via[-1][1] <= 3.51 + 1e-9, "de waterpunten lopen naar het westen, richting het meer"
    assert state["round_trip_anchor"]["label"] == "Meer"
    legs = seen["legs"]
    assert [leg["to"] for leg in legs][:2] == ["waterloop", "Meer"]
    back = legs[-1]["points"]
    assert legs[-1]["to"] == "start" and back[1:-1] == list(reversed([tuple(p) for p in via]))


def test_far_place_asks_first_and_both_answers_resolve_it():
    from lusmaker import profiles, readiness
    d = {"id": "p1", "start": {"label": "Wetteren", "lat": 50.9986, "lon": 3.8717}, "end": None, "avoid_places": [],
         "round_trip_anchor": {"label": "Donkmeer (Donk, Overmere)", "lat": 51.0357, "lon": 3.9692},
         "route_request": {"doel": "toeren", "target_km": 14, "tolerance_km": 2.5, "max_km": 16.5, "max_km_explicit": False,
                           "rond_plaats": "Donkmeer"},
         "_probe": {"km": 15, "hm": 10, "kwaliteit": {}, "terrein": {"plaatskernen": []}}}
    profile = profiles.default_document(); profile["activiteit"] = "wandelen"
    first = readiness.assess(d, profile, {})["vragen"][0]
    assert first["id"] == "plek_afstand" and set(first["opties"]) == {"ruimer", "zonder"}
    assert "ongeveer 22 km" in first["vraag"]  # 8 km hemelsbreed x 2 x 1,4

    import copy
    wider = copy.deepcopy(d)
    intents.apply_answers("p1", {"plek_afstand": "ruimer"}, load_fn=lambda _i: wider, save_fn=lambda _d: None,
                          adjust_fn=lambda _i, **_k: {"status": "ready"})
    assert wider["route_request"]["target_km"] == 22 and wider["route_request"]["max_km"] == 24.5
    assert "plek_afstand" not in wider["route_request"]["expliciete_voorkeuren"]
    assert readiness._place_distance_question(wider) is None

    without = copy.deepcopy(d)
    intents.apply_answers("p1", {"plek_afstand": "zonder"}, load_fn=lambda _i: without, save_fn=lambda _d: None,
                          adjust_fn=lambda _i, **_k: {"status": "ready"})
    assert "round_trip_anchor" not in without and without["route_request"]["rond_plaats"] is None


def test_network_question_for_walkers_off_the_node_network_and_answer_becomes_criterion():
    from lusmaker import profiles, questions
    from lusmaker import criteria as crit
    d = {"id": "k1", "start": {"label": "S", "lat": 51, "lon": 3.8}, "end": None, "avoid_places": [],
         "_probe": {"km": 6, "hm": 5, "kwaliteit": {"gecureerd_pct": 20.0}, "terrein": {"plaatskernen": [], "netwerk_in_buurt": True}}}
    walk = profiles.default_document(); walk["activiteit"] = "wandelen"
    race = profiles.default_document(); race["activiteit"] = "koersfiets"
    assert "knooppunten" in [q["id"] for q in questions.ask(d, walk, d["_probe"])]
    assert "knooppunten" not in [q["id"] for q in questions.ask(d, race, d["_probe"])]
    d["_probe"]["terrein"]["netwerk_in_buurt"] = False      # geen netwerk in de buurt: niet vragen
    assert "knooppunten" not in [q["id"] for q in questions.ask(d, walk, d["_probe"])]
    d["_probe"]["terrein"]["netwerk_in_buurt"] = True
    d["_probe"]["kwaliteit"]["gecureerd_pct"] = 70.0
    assert "knooppunten" not in [q["id"] for q in questions.ask(d, walk, d["_probe"])]
    spec = crit.merge(None, crit.from_answers({"knooppunten": "graag"}))
    assert spec[0]["metriek"] == "knooppunt"
    line = crit.explain(spec, {"gecureerd_pct": 82.4}, {"total_km": 10})[0]
    assert line["tekst"] == "82 % over knooppuntroutes" and line["ok"] is True


def test_fill_prefers_a_compact_loop_over_a_stretched_one_of_the_same_length():
    from lusmaker import optimizer
    import math

    def loop(radius_deg, stretch):
        return [(51.0 + radius_deg * stretch * math.sin(t / 20 * 2 * math.pi),
                 3.87 + radius_deg * math.cos(t / 20 * 2 * math.pi) / stretch) for t in range(21)]
    compact = {"distance_m": 34000.0, "coords": loop(0.04, 1.0), "ascend_m": 50}
    stretched = {"distance_m": 34000.0, "coords": loop(0.04, 3.0), "ascend_m": 50}
    d = {"id": "f1", "start": {"lat": 51.0, "lon": 3.87}, "loop": True, "climbs": [], "opvullingen": [],
         "computed": {"total_km": 0.0, "ascend_m": 0, "descend_m": 0, "legs": [], "kwaliteit": {}}, "_geometry": []}
    chosen = []

    def round_trip(anchor, distance, seed, **_k):
        return [stretched, compact][seed % 2]

    def router(dd, _db):
        chosen.append(dd["opvullingen"][-1]["seed"])
        dd["computed"] = {"total_km": 34.0, "ascend_m": 50, "descend_m": 50, "legs": [], "kwaliteit": {}}
        dd["_geometry"] = [[(51.0, 3.87), (51.01, 3.88)]]

    optimizer._fill_with_round_trip(d, {}, 40000.0, router=router, round_trip_fn=round_trip,
                                    objective="toeren", target_total_m=34000.0)
    assert chosen and chosen[0] % 2 == 1, "de compacte lus moet als eerste geprobeerd worden"


def test_network_nearby_reads_the_route_source_database():
    import sqlite3
    from lusmaker import route_evidence
    with tempfile.TemporaryDirectory() as tmp:
        db = Path(tmp) / "rs.sqlite"
        con = sqlite3.connect(db)
        con.executescript("""CREATE TABLE feature(id INTEGER PRIMARY KEY, layer, source_id, mode, role, geometry, properties);
            CREATE TABLE bounds(id INTEGER, minlon, maxlon, minlat, maxlat);
            INSERT INTO feature VALUES (1,'routes:traject_wandel','x','wandel','network','{}','{}');
            INSERT INTO bounds VALUES (1, 3.70, 3.71, 51.05, 51.06);""")
        con.commit(); con.close()
        assert route_evidence.network_nearby([(51.055, 3.72)], "trail", database=db) is True
        assert route_evidence.network_nearby([(51.20, 3.72)], "trail", database=db) is False
        assert route_evidence.network_nearby([(51.055, 3.72)], "quiet", database=db) is False   # fietsmodus


def test_klaar_applies_given_answers_and_routes_without_new_questions():
    state = {"id": "d1", "revision": 1, "route_request": {"doel": "toeren", "activiteit": "toerfiets", "profiel_naam": "standaard"}}
    calls = []
    intents.apply_answers("d1", {"ondergrond": "ok"}, klaar=True, load_fn=lambda _i: state, save_fn=lambda _d: None,
                          adjust_fn=lambda _i, **kw: calls.append(kw) or {"status": "ready"})
    assert calls == [{"doel": "toeren", "check_readiness": False}]
    assert state["route_request"]["expliciete_voorkeuren"] == {"ondergrond": "ok"}
