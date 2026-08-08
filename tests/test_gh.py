"""Pure tests voor request-side GraphHopper-custom-modelregels."""

from lusmaker import gh


def _route_body(*, area_evs):
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
