"""Pure tests voor request-side GraphHopper-custom-modelregels."""

from lusmaker import gh


def _route_body(*, area_evs, heat_activity=None):
    captured = {}

    def post(_path, body):
        captured["body"] = body
        return {
            "paths": [
                {
                    "distance": 1000,
                    "time": 60_000,
                    "points": {
                        "coordinates": [[4.0, 50.0], [4.01, 50.0]],
                    },
                }
            ]
        }

    gh.route(
        [(50.0, 4.0), (50.0, 4.01)],
        avoid_cobbles=True,
        avoid_busy=True,
        heat_activity=heat_activity,
        area_evs=area_evs,
        post_fn=post,
    )
    return captured["body"]


def test_area_rules_are_added_only_for_available_encoded_values():
    body = _route_body(area_evs={"in_kassei_tvl", "in_druk_tvl"})

    assert body["custom_model"]["priority"] == [
        {"if": "surface == COBBLESTONE", "multiply_by": "0.25"},
        {"if": "in_kassei_tvl", "multiply_by": "0.25"},
        {"if": "in_druk_tvl", "multiply_by": "0.45"},
    ]


def test_area_rules_are_omitted_without_capabilities_but_osm_rule_remains():
    body = _route_body(area_evs=set())

    assert body["custom_model"]["priority"] == [
        {"if": "surface == COBBLESTONE", "multiply_by": "0.25"},
    ]


def test_paved_heat_activity_adds_boost_and_unpaved_penalty():
    body = _route_body(
        area_evs={"in_popular_koersfiets", "in_onverhard"},
        heat_activity="koersfiets",
    )

    assert {"if": "!in_popular_koersfiets", "multiply_by": "0.85"} in body[
        "custom_model"
    ]["priority"]
    assert {"if": "in_onverhard", "multiply_by": "0.55"} in body[
        "custom_model"
    ]["priority"]


def test_unpaved_heat_activity_adds_boost_without_unpaved_penalty():
    body = _route_body(
        area_evs={"in_popular_mtb", "in_onverhard"},
        heat_activity="mtb",
    )

    assert {"if": "!in_popular_mtb", "multiply_by": "0.85"} in body[
        "custom_model"
    ]["priority"]
    assert all(
        rule.get("if") != "in_onverhard"
        for rule in body["custom_model"]["priority"]
    )


def test_heat_activity_rules_are_omitted_without_area_capabilities():
    body = _route_body(area_evs=set(), heat_activity="koersfiets")

    assert all(
        "popular_koersfiets" not in rule.get("if", "")
        and rule.get("if") != "in_onverhard"
        for rule in body["custom_model"]["priority"]
    )


def test_probe_detects_missing_area_without_in_prefix_in_error():
    # GH meldt een ontbrekende area als "Area 'kassei_tvl' wasn't found" —
    # zonder de in_-prefix. De probe moet dat als ontbrekend herkennen.
    def missing(_path, _body):
        raise gh.GhError(
            "GraphHopper: Cannot compile expression: Area 'kassei_tvl' wasn't found"
        )

    def present(_path, _body):
        raise gh.GhError("GraphHopper: Connection between locations not found")

    gh._area_ev_works.cache_clear()
    assert gh._area_ev_works("in_kassei_tvl", missing) is False
    gh._area_ev_works.cache_clear()
    assert gh._area_ev_works("in_kassei_tvl", present) is False
    gh._area_ev_works.cache_clear()


def test_available_area_evs_probes_all_activity_and_unpaved_areas():
    probed = []

    def present(_path, body):
        probed.append(body["custom_model"]["priority"][0]["if"])
        return {"paths": []}

    gh._area_ev_works.cache_clear()
    available = gh.available_area_evs(present)
    gh._area_ev_works.cache_clear()

    expected = {
        "in_kassei_tvl",
        "in_druk_tvl",
        "in_niet_autovrij_tvl",
        *(f"in_popular_{activity}" for activity in gh.ACTIVITIES),
        "in_onverhard",
    }
    assert available == expected
    assert set(probed) == expected


def _with_startup_env(wait_s, marker=None):
    import os
    saved = {k: os.environ.get(k) for k in ("LUSMAKER_GH_STARTUP_WAIT_S", "LUSMAKER_GH_FAILED_MARKER")}
    os.environ["LUSMAKER_GH_STARTUP_WAIT_S"] = str(wait_s)
    if marker:
        os.environ["LUSMAKER_GH_FAILED_MARKER"] = marker
    else:
        os.environ.pop("LUSMAKER_GH_FAILED_MARKER", None)
    gh._ready_url = None

    def restore():
        gh._ready_url = None
        for key, value in saved.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value
    return restore


def test_routing_waits_for_a_graphhopper_that_starts_after_the_api():
    restore = _with_startup_env(60)
    checks = []
    try:
        gh.wait_until_ready(health=lambda _url: checks.append(1) or len(checks) >= 3, sleep=lambda _s: None)
        gh.wait_until_ready(health=lambda _url: checks.append(1) or False, sleep=lambda _s: None)
    finally:
        restore()
    assert len(checks) == 3  # ready is remembered; the second call does not poll


def test_router_startup_failure_and_timeout_are_clear_errors():
    import tempfile
    from pathlib import Path
    with tempfile.TemporaryDirectory() as tmp:
        marker = Path(tmp) / "gh.failed"
        marker.touch()
        restore = _with_startup_env(60, str(marker))
        try:
            gh.wait_until_ready(health=lambda _url: False, sleep=lambda _s: None)
            raise AssertionError("expected GhError")
        except gh.GhError as error:
            assert "kon niet starten" in str(error)
        finally:
            restore()
    now = [0.0]
    restore = _with_startup_env(1)
    try:
        gh.wait_until_ready(health=lambda _url: False, sleep=lambda s: now.__setitem__(0, now[0] + s), clock=lambda: now[0])
        raise AssertionError("expected GhError")
    except gh.GhError as error:
        assert "opstarten" in str(error)
    finally:
        restore()


def test_local_runs_do_not_wait_for_a_router():
    restore = _with_startup_env(0)
    try:
        gh.wait_until_ready(health=lambda _url: (_ for _ in ()).throw(AssertionError("polled")))
    finally:
        restore()


def test_a_cold_router_start_is_reported_as_progress():
    from lusmaker import progress
    restore = _with_startup_env(60)
    events, checks = [], []
    try:
        with progress.capture(events.append):
            gh.wait_until_ready(health=lambda _url: checks.append(1) or len(checks) >= 3, sleep=lambda _s: None)
    finally:
        restore()
    assert [event["stage"] for event in events] == ["router_start"]


def test_area_evs_come_from_the_custom_areas_directory_without_router_calls():
    import json
    import tempfile
    from pathlib import Path
    with tempfile.TemporaryDirectory() as tmp:
        features = [{"type": "Feature", "id": key, "properties": {}, "geometry": None}
                    for key in ("druk_tvl", "kassei_tvl", "popular", "popular_trail")]
        Path(tmp, "popular.geojson").write_text(json.dumps({"type": "FeatureCollection", "features": features}))
        available = gh.available_area_evs(areas_dir=tmp)
    assert available == {"in_kassei_tvl", "in_druk_tvl", "in_popular_trail"}


def test_area_evs_fall_back_to_probes_without_a_directory():
    import tempfile
    probed = []

    def present(_path, body):
        probed.append(body["custom_model"]["priority"][0]["if"])
        return {"paths": []}

    with tempfile.TemporaryDirectory() as tmp:
        # Lege map: geen bruikbare kennis, dus probes; offline faalt elke probe zonder crash.
        assert gh.available_area_evs(areas_dir=tmp) == frozenset()
    assert gh.available_area_evs(present)  # expliciete probe blijft werken
    assert probed


def test_a_point_never_gets_both_a_heading_and_a_point_hint():
    sent = []

    def post(_path, body):
        sent.append(body)
        return {"paths": [{"distance": 1000, "time": 60_000, "points": {"coordinates": [[3.6, 50.8], [3.61, 50.81]]}}]}

    points = [(50.80, 3.60), (50.81, 3.61), (50.82, 3.62)]
    gh.route(points, point_hints=["Berendries", "Kerkstraat", ""], headings=[90.0, None, None], area_evs=set(), post_fn=post)
    assert sent[-1]["headings"] == [90.0]
    assert sent[-1]["point_hints"] == ["", "Kerkstraat", ""]
    gh.route(points, point_hints=["Berendries", "", ""], headings=[90.0, None, None], area_evs=set(), post_fn=post)
    assert "point_hints" not in sent[-1]  # alleen een lege hint over: niets meesturen
