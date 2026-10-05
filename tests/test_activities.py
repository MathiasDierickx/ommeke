"""Activiteitencatalogus en request-time custom models (offline)."""
import re

from lusmaker import activities, gh, intents, profiles, quick_plan

ALLOWED_VARIABLES = {
    "surface", "road_class", "smoothness", "track_type", "mtb_rating",
    "bike_network", "max_speed", "road_environment",
}


def test_catalogue_has_the_eight_activities_and_legacy_aliases():
    assert activities.KEYS == (
        "wandelen", "trail", "wegloop", "stadsfiets", "toerfiets",
        "koersfiets", "gravel", "mtb",
    )
    assert activities.canonical("fietsen") == "toerfiets"
    assert activities.canonical("trail") == "trail"
    assert activities.canonical("zweefvliegen") is None
    assert activities.graph_profile("fietsen") == "quiet"
    for key in ("wandelen", "trail", "wegloop"):
        assert activities.graph_profile(key) == "trail" and activities.is_foot(key)
    for key in ("stadsfiets", "toerfiets", "koersfiets", "gravel", "mtb"):
        assert activities.graph_profile(key) == "quiet" and not activities.is_foot(key)


def test_fragments_only_penalise_with_floor_and_known_encoded_values():
    for key in activities.KEYS:
        if key == "trail":
            continue  # bewaart het oorspronkelijke, hardere trailgedrag
        for rule in activities.priority_fragment(key):
            factor = float(rule["multiply_by"])
            assert activities.MIN_FACTOR <= factor <= 1.0, (key, rule)
            condition = rule.get("if") or rule.get("else_if")
            variables = set(re.findall(r"[a-z_]+(?= [=<>!])", condition))
            assert variables <= ALLOWED_VARIABLES, (key, variables)


def _body(**kwargs):
    return gh._custom_model(area_evs=set(), **kwargs)["priority"]


def test_legacy_trail_profile_keeps_its_hardwired_model_without_activity():
    assert _body(profile="trail") == gh.TRAIL_OFFROAD_PRIORITY
    assert _body(profile="trail", activity="trail") == gh.TRAIL_OFFROAD_PRIORITY
    assert _body(profile="quiet") == []
    assert _body(profile="quiet", activity="fietsen") == []
    assert _body(profile="quiet", activity="toerfiets") == []


def test_new_activities_add_their_own_fragment_instead_of_the_trail_branch():
    walk = _body(profile="trail", activity="wandelen")
    assert walk == activities.priority_fragment("wandelen")
    assert not any("RESIDENTIAL" in rule.get("else_if", "") for rule in walk)
    assert any("ASPHALT" in rule["if"] for rule in _body(profile="quiet", activity="mtb"))
    assert any("smoothness" in rule["if"] for rule in _body(profile="quiet", activity="koersfiets"))


def test_profiles_accept_every_activity_and_route_to_the_right_graph_profile():
    for key in activities.ACCEPTED:
        document = profiles.default_document("x")
        document["activiteit"] = key
        checked = profiles._validate(document)
        assert profiles.routing_prefs(checked)["profile"] == activities.graph_profile(key)
    document = profiles.default_document("x")
    document["activiteit"] = "zweefvliegen"
    try:
        profiles._validate(document)
    except profiles.ProfileError:
        pass
    else:
        raise AssertionError("onbekende activiteit moet falen")


def test_quick_plan_accepts_new_and_legacy_activities():
    for key in activities.ACCEPTED:
        values = quick_plan.parameters({"start": "Gent", "target_km": 20, "activiteit": key})
        assert values["activiteit"] == key
        assert values["kasseien"] is None and values["strict"] is None
    try:
        quick_plan.parameters({"start": "Gent", "target_km": 20, "activiteit": "kajak"})
    except ValueError:
        pass
    else:
        raise AssertionError("onbekende activiteit moet falen")


def test_hosted_evals_cover_every_activity():
    from lusmaker import mcp_evals

    cases = mcp_evals.load("evals/hosted_intents.json")
    covered = {c.get("expected_arguments", {}).get("activiteit") for c in cases}
    assert set(activities.KEYS) <= covered


def test_plan_route_rejects_unknown_activity_and_names_walks_and_runs():
    try:
        intents.plan_route("Gent", target_km=5, activiteit="kajak")
    except intents.IntentError as exc:
        assert "wandelen" in str(exc)
    else:
        raise AssertionError("onbekende activiteit moet falen")
    name = intents.suggest_route_name
    assert name("Gent", target_km=5, max_km=None, doel="toeren", activiteit="wegloop").startswith("Looplus")
    assert name("Gent", target_km=5, max_km=None, doel="toeren", activiteit="wandelen").startswith("Wandellus")
