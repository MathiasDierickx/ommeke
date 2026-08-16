"""Pure tests voor plaatsdetectie uit de lokale gazetteer."""

import pickle
import tempfile
import warnings
from pathlib import Path

from lusmaker import config, geocode


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


def test_exact_landmark_wins_over_street_and_place_for_one_part_query():
    gazetteer = {
        "places": [("Blaarmeersen", "suburb", 51.0543, 3.7250)],
        "streets": {
            "blaarmeersen": [(51.0600, 3.7300, "Blaarmeersen")],
        },
        "landmarks": [
            ("Blaarmeérsen", "leisure:recreation_ground", 51.0390, 3.7000),
        ],
    }

    hits = geocode.geocode("BLAARMEERSEN", gazetteer=gazetteer)

    assert hits == [
        {
            "label": "Blaarmeérsen",
            "type": "landmark",
            "kind": "leisure:recreation_ground",
            "lat": 51.0390,
            "lon": 3.7000,
        }
    ]


def test_landmark_with_place_context_wins_over_place_fallback_within_8_km():
    gazetteer = {
        "places": [("Gent", "city", 51.0543, 3.7250)],
        "streets": {},
        "landmarks": [
            ("Blaarmeersen", "leisure:recreation_ground", 51.0390, 3.7000),
            ("Blaarmeersen", "natural:water", 50.8000, 4.0000),
        ],
    }

    hits = geocode.geocode("Blaarmeersen, Gent", gazetteer=gazetteer)

    assert len(hits) == 1
    assert hits[0]["type"] == "landmark"
    assert hits[0]["kind"] == "leisure:recreation_ground"
    assert (hits[0]["lat"], hits[0]["lon"]) == (51.0390, 3.7000)


def test_old_gazetteer_defaults_landmarks_and_requests_force_rebuild():
    with tempfile.TemporaryDirectory() as temp_dir:
        path = Path(temp_dir) / "gazetteer.pkl"
        with path.open("wb") as handle:
            pickle.dump({"places": [], "streets": {}}, handle)
        previous = config.__dict__.get("GAZETTEER_PKL")
        config.GAZETTEER_PKL = path
        try:
            with warnings.catch_warnings(record=True) as caught:
                warnings.simplefilter("always")
                gazetteer = geocode._load()
        finally:
            if previous is None:
                del config.GAZETTEER_PKL
            else:
                config.GAZETTEER_PKL = previous

    assert gazetteer["landmarks"] == []
    assert gazetteer["waterways"] == {}
    assert "lus build --force" in str(caught[0].message)
    assert any("waterlopen" in str(warning.message) for warning in caught)


def test_waterway_segments_matches_normalised_name_and_tolerates_old_data():
    segments = [
        [(51.00, 3.70), (51.01, 3.71)],
        [(51.01, 3.71), (51.02, 3.72)],
    ]
    gazetteer = {"waterways": {"de schelde": segments}}

    assert geocode.waterway_segments(
        "  De Schélde ", gazetteer=gazetteer
    ) == segments
    assert geocode.waterway_segments("De Schelde", gazetteer={}) == []


def test_resolve_falls_back_to_google_when_local_geocoder_has_no_hits():
    gazetteer = {"places": [], "streets": {}, "landmarks": []}
    calls = []
    google_hit = {
        "label": "Café Tonneke",
        "lat": 50.9956,
        "lon": 3.8786,
        "type": "google",
        "source": "places",
    }

    def google_resolver(query):
        calls.append(query)
        return google_hit

    primary, alternatives = geocode.resolve(
        "café Tonneke Wetteren",
        gazetteer=gazetteer,
        google_resolver=google_resolver,
    )

    assert primary == google_hit
    assert alternatives == []
    assert calls == ["café Tonneke Wetteren"]


def test_resolve_uses_google_for_weak_local_place_fallback():
    gazetteer = {
        "places": [("Wetteren", "town", 51.006, 3.884)],
        "streets": {},
        "landmarks": [],
    }
    google_hit = {
        "label": "Café Tonneke",
        "lat": 50.9956,
        "lon": 3.8786,
        "type": "google",
        "source": "places",
    }

    primary, alternatives = geocode.resolve(
        "Café Tonneke, Wetteren",
        gazetteer=gazetteer,
        google_resolver=lambda _query: google_hit,
    )

    assert primary == google_hit
    assert alternatives == []


def test_resolve_does_not_bill_google_for_strong_local_hit():
    gazetteer = {
        "places": [],
        "streets": {},
        "landmarks": [
            ("Blaarmeersen", "leisure:recreation_ground", 51.039, 3.7)
        ],
    }

    def google_resolver(_query):
        raise AssertionError("Google mag voor een lokale landmark-hit niet draaien")

    primary, alternatives = geocode.resolve(
        "Blaarmeersen",
        gazetteer=gazetteer,
        google_resolver=google_resolver,
    )

    assert primary == {"label": "Blaarmeersen", "lat": 51.039, "lon": 3.7}
    assert alternatives == []
