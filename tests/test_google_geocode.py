"""Offline tests voor de optionele Google Maps-geocoder."""

import json
import os
from contextlib import contextmanager
from urllib.parse import parse_qs, urlparse

from lusmaker import google_geocode


@contextmanager
def _google_key(value: str | None):
    previous = os.environ.get("LUSMAKER_GOOGLE_MAPS_KEY")
    if value is None:
        os.environ.pop("LUSMAKER_GOOGLE_MAPS_KEY", None)
    else:
        os.environ["LUSMAKER_GOOGLE_MAPS_KEY"] = value
    try:
        yield
    finally:
        if previous is None:
            os.environ.pop("LUSMAKER_GOOGLE_MAPS_KEY", None)
        else:
            os.environ["LUSMAKER_GOOGLE_MAPS_KEY"] = previous


def test_resolve_uses_first_places_hit():
    requests = []

    def fetch(request, timeout):
        requests.append((request, timeout))
        return json.dumps(
            {
                "places": [
                    {
                        "displayName": {"text": "Café Tonneke"},
                        "formattedAddress": "Massemsesteenweg 48, 9230 Wetteren",
                        "location": {"latitude": 50.9956, "longitude": 3.8786},
                    }
                ]
            }
        ).encode()

    with _google_key("test-key"):
        result = google_geocode.resolve("café Tonneke Wetteren", fetch=fetch)

    assert result == {
        "label": "Café Tonneke",
        "lat": 50.9956,
        "lon": 3.8786,
        "type": "google",
        "source": "places",
    }
    request, timeout = requests[0]
    assert len(requests) == 1
    assert request.full_url == google_geocode.PLACES_URL
    assert request.get_method() == "POST"
    assert timeout == 5
    assert request.get_header("X-goog-api-key") == "test-key"
    assert request.get_header("X-goog-fieldmask") == (
        "places.displayName,places.formattedAddress,places.location"
    )
    assert json.loads(request.data) == {
        "textQuery": "café Tonneke Wetteren",
        "regionCode": "BE",
        "languageCode": "nl",
    }


def test_resolve_falls_back_to_geocoding_when_places_is_empty():
    requests = []

    def fetch(request):
        requests.append(request)
        if request.get_method() == "POST":
            return {"places": []}
        return {
            "results": [
                {
                    "formatted_address": "Massemsesteenweg 48, 9230 Wetteren",
                    "geometry": {
                        "location": {"lat": 50.9956, "lng": 3.8786}
                    },
                }
            ]
        }

    with _google_key("test-key"):
        result = google_geocode.resolve("café Tonneke Wetteren", fetch=fetch)

    assert result == {
        "label": "Massemsesteenweg 48, 9230 Wetteren",
        "lat": 50.9956,
        "lon": 3.8786,
        "type": "google",
        "source": "geocoding",
    }
    assert [request.get_method() for request in requests] == ["POST", "GET"]
    query = parse_qs(urlparse(requests[1].full_url).query)
    assert query == {
        "address": ["café Tonneke Wetteren"],
        "components": ["country:BE"],
        "language": ["nl"],
        "key": ["test-key"],
    }


def test_resolve_returns_none_without_key_and_does_not_fetch():
    def fetch(_request, _timeout):
        raise AssertionError("fetch mag zonder key niet worden aangeroepen")

    with _google_key(""):
        assert google_geocode.resolve("café Tonneke Wetteren", fetch=fetch) is None


def test_resolve_swallows_network_errors():
    calls = []

    def fetch(request, timeout):
        calls.append(request)
        raise OSError("offline")

    with _google_key("test-key"):
        assert google_geocode.resolve("café Tonneke Wetteren", fetch=fetch) is None

    assert [request.get_method() for request in calls] == ["POST", "GET"]


def test_resolve_caches_repeated_queries():
    calls = []

    def fetch(request, timeout):
        calls.append(request)
        return {
            "places": [
                {
                    "displayName": {"text": "Café Tonneke"},
                    "location": {"latitude": 50.9956, "longitude": 3.8786},
                }
            ]
        }

    google_geocode.resolve.cache_clear()
    with _google_key("test-key"):
        first = google_geocode.resolve("café Tonneke Wetteren", fetch=fetch)
        second = google_geocode.resolve("café Tonneke Wetteren", fetch=fetch)

    assert first == second
    assert len(calls) == 1
