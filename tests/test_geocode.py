"""Pure tests voor plaatsdetectie uit de lokale gazetteer."""

from lusmaker import geocode


def test_places_near_route_uses_synthetic_gazetteer_and_400_meter_limit():
    gazetteer = {
        "places": [
            ("Dichtdorp", "village", 50.001, 4.005),
            ("Verweg", "town", 50.010, 4.005),
        ],
        "streets": {},
    }
    route = [(50.0, 4.0), (50.0, 4.01)]

    nearby = geocode.places_near_route(route, gazetteer=gazetteer)

    assert [place["label"] for place in nearby] == ["Dichtdorp"]
    assert nearby[0]["afstand_m"] < 400


def test_places_near_route_is_deterministic_and_handles_empty_route():
    gazetteer = {
        "places": [
            ("Zulu", "hamlet", 50.0, 4.005),
            ("Alfa", "village", 50.0, 4.005),
        ]
    }

    nearby = geocode.places_near_route(
        [(50.0, 4.0), (50.0, 4.01)], gazetteer=gazetteer
    )

    assert [place["label"] for place in nearby] == ["Alfa", "Zulu"]
    assert geocode.places_near_route([], gazetteer=gazetteer) == []
