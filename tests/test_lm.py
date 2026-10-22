import importlib.util
import itertools

import yaml

from lusmaker import activities, gh, gh_config, pack_manifest


def test_generated_graphhopper_config_prepares_lm_profiles():
    document = yaml.safe_load(gh_config.GH_CONFIG_YML.format(
        pbf_name="region.osm.pbf", gh_port=8989, admin_port=8990
    ))["graphhopper"]
    assert {item["profile"] for item in document["profiles_lm"]} == {"quiet", "trail"}
    assert document["prepare.lm.landmarks"] == 16


def test_all_custom_model_rules_keep_landmarks_eligible():
    optional = importlib.util.find_spec("lusmaker.criteria_routing")
    criteria_routing = __import__("lusmaker.criteria_routing", fromlist=["*"]) if optional else None
    flags = list(itertools.product((False, True), repeat=6))
    areas = (
        frozenset(),
        frozenset({"in_kassei_tvl", "in_druk_tvl", "in_niet_autovrij_tvl",
                   "in_popular_koersfiets", "in_popular_gravel", "in_popular_mtb",
                   "in_popular_trail", "in_onverhard"}),
    )
    for activity in activities.ACCEPTED:
        for strict, cobbles, concrete, busy, cycleways, paved in flags:
            for heat in (None, "koersfiets", "gravel", "mtb", "trail"):
                for area_evs in areas:
                    model = gh._custom_model(
                        strict=strict, avoid_cobbles=cobbles, avoid_concrete=concrete,
                        avoid_busy=busy, prefer_cycleways=cycleways, prefer_paved=paved,
                        activity=activity, heat_activity=heat,
                        area_evs=area_evs,
                    )
                    rules = model.get("priority", [])
                    if criteria_routing:
                        for metric in criteria_routing.METRICS:
                            rules += criteria_routing.priority_rules(metric)
                    for rule in rules:
                        if "multiply_by" in rule:
                            assert float(rule["multiply_by"]) <= 1
                        assert not ("speed" in rule and float(rule["speed"]) > 1)


def test_benchmark_runs_each_call_type_n_times_without_network():
    calls = []

    def record(name):
        def call(*args, **kwargs):
            calls.append(name)
            return {}
        return call

    result = gh.bench_router(
        2, route_fn=record("route"), round_trip_fn=record("round_trip"),
        circle_round_trip_fn=record("circle_round_trip"),
    )
    assert calls.count("route") == calls.count("round_trip") == calls.count("circle_round_trip") == 2
    assert set(result) == {"route", "round_trip", "circle_round_trip"}
    assert all(row["n"] == 2 and row["p95_ms"] >= row["p50_ms"] for row in result.values())


def test_pack_profile_config_version_requires_lm_rebuild():
    assert pack_manifest.PROFILE_CONFIG_VERSION == 2
    for version in (None, 1):
        manifest = {"pack_format_version": 2, "profile_config_version": version}
        try:
            pack_manifest.validate(manifest)
        except ValueError:
            pass
        else:
            raise AssertionError("oud pack zonder LM-config werd aanvaard")
