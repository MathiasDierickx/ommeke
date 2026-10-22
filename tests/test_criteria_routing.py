from lusmaker import activities, criteria, criteria_routing, gh


def _item(metric, direction, *, hard=False, weight=0.5):
    return {"metriek": metric, "richting": direction, "gewicht": weight, "hard": hard}


def test_metric_mapping_and_direction():
    cases = {
        ("stil", "hoog"): "road_class == PRIMARY || road_class == SECONDARY",
        ("autovrij", "hoog"): "road_class == PRIMARY || road_class == SECONDARY",
        ("steenweg", "laag"): "road_class == PRIMARY || road_class == SECONDARY",
        ("kassei", "laag"): "surface == COBBLESTONE",
        ("beton", "laag"): "surface == CONCRETE",
        ("onverhard", "laag"): "surface == GRAVEL || surface == DIRT || surface == GRASS || surface == SAND || surface == GROUND || surface == UNPAVED || surface == COMPACTED || surface == FINE_GRAVEL",
        ("fietspad", "hoog"): "road_class != CYCLEWAY && bike_network == MISSING",
    }
    for key, condition in cases.items():
        assert criteria_routing.priority_rules([_item(*key)], profile="quiet")[0]["if"] == condition
    assert criteria_routing.priority_rules([_item("kassei", "hoog")], profile="quiet") == []
    assert criteria_routing.priority_rules([_item("kort", "hoog")], profile="quiet") == []


def test_hard_soft_and_unpaved_preference_factors():
    assert criteria_routing.priority_rules([_item("kassei", "laag", hard=True)], profile="quiet")[0]["multiply_by"] == "0.15"
    assert criteria_routing.priority_rules([_item("kassei", "laag", weight=1)], profile="quiet")[0]["multiply_by"] == "0.4"
    assert criteria_routing.priority_rules([_item("offroad", "hoog", weight=1)], profile="quiet")[0]["multiply_by"] == "0.6"


def test_all_generated_factors_are_at_most_one():
    for metric in criteria.METRICS:
        for direction in criteria.RICHTINGEN:
            for activity in activities.ACCEPTED:
                spec = [{"metriek": metric, "richting": direction, "gewicht": 1, "hard": hard}
                        for hard in (False, True)]
                rules = criteria_routing.priority_rules(spec, profile=activities.graph_profile(activity))
                assert all(float(rule["multiply_by"]) <= 1 for rule in rules)
    assert criteria_routing.priority_rules([_item("knooppunt", "hoog")], profile="trail") == []
    assert criteria_routing.priority_rules([_item("knooppunt", "hoog")], profile="quiet")


def test_no_criteria_keeps_custom_model_unchanged():
    assert gh._custom_model(area_evs=set(), profile="quiet") == {
        "priority": [],
    }


def test_criteria_reach_route_and_round_trip_request_bodies():
    bodies = []
    def post(path, body):
        bodies.append(body)
        return {"paths": [{"distance": 1000, "time": 1000,
                            "points": {"coordinates": [[4.0, 51.0], [4.01, 51.01]]}}]}
    spec = criteria.parse([_item("stil", "hoog")])
    gh.route([(51.0, 4.0), (51.01, 4.01)], profile="quiet", criteria=spec,
             area_evs=set(), post_fn=post)
    gh.round_trip((51.0, 4.0), 5000, 1, profile="quiet", criteria=spec,
                  area_evs=set(), post_fn=post)
    assert len(bodies) == 2
    assert all(any("road_class == PRIMARY" in r["if"] for r in b["custom_model"]["priority"])
               for b in bodies)
