"""Puur outputcontract voor klimsuggesties."""

from lusmaker import draft


def test_suggest_keeps_existing_fields_and_adds_compact_fields():
    routed = {
        "id": "abc123",
        "start": {"lat": 50.0, "lon": 4.0},
        "loop": True,
        "strict": False,
        "avoid_cobbles": False,
        "avoid_concrete": False,
        "avoid_places": [],
        "climbs": [],
        "computed": {
            "legs": [
                {
                    "from": "start",
                    "to": "start",
                    "km": 10.0,
                    "ascend_m": 20,
                    "climb": None,
                }
            ]
        },
        "_geometry": [[[50.0, 4.0, 10], [50.01, 4.01, 20]]],
    }
    climb_db = {
        "molenberg": {
            "id": "molenberg",
            "name": "Molenberg",
            "town": "Zwalm",
            "length_m": 1100,
            "gain_m": 50,
            "avg_pct": 4.0,
            "max_pct": 8.0,
            "warnings": [],
            "foot": [50.002, 4.002],
            "mid": [50.003, 4.003],
            "top": [50.004, 4.004],
        }
    }

    def router(_points, **_kwargs):
        return {"distance_m": 2000, "ascend_m": 30}

    suggestion = draft._candidates(
        routed,
        climb_db,
        max_detour_km=8,
        limit=1,
        router=router,
    )[0]

    assert suggestion["climb"]["id"] == "molenberg"
    assert suggestion["extra_hoogtemeters"] == suggestion["extra_hm"]
    assert suggestion["invoegen_op_positie"] == suggestion["pos"]
    assert suggestion["id"] == "molenberg"
    assert suggestion["label"] == "Molenberg (1.1 km @ 4%)"
