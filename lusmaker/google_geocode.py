"""Optionele Google Maps-fallback voor specifieke plaatsen en zaken."""

from __future__ import annotations

import json
import os
import urllib.request
from functools import lru_cache
from urllib.parse import urlencode


PLACES_URL = "https://places.googleapis.com/v1/places:searchText"
GEOCODING_URL = "https://maps.googleapis.com/maps/api/geocode/json"
TIMEOUT_SECONDS = 5


def _http_fetch(request: urllib.request.Request, timeout: float = TIMEOUT_SECONDS):
    with urllib.request.urlopen(request, timeout=timeout) as response:
        return response.read()


def _fetch_json(fetch, request: urllib.request.Request) -> dict:
    try:
        value = fetch(request, timeout=TIMEOUT_SECONDS)
    except TypeError:
        # Kleine one-argument fetchers houden unit-tests eenvoudig.
        value = fetch(request)
    if hasattr(value, "read"):
        value = value.read()
    if isinstance(value, bytes):
        value = value.decode("utf-8")
    if isinstance(value, str):
        value = json.loads(value)
    if not isinstance(value, dict):
        raise ValueError("Google Maps gaf geen JSON-object terug")
    return value


def _places_result(query: str, key: str, fetch) -> dict | None:
    request = urllib.request.Request(
        PLACES_URL,
        data=json.dumps(
            {
                "textQuery": query,
                "regionCode": "BE",
                "languageCode": "nl",
            }
        ).encode("utf-8"),
        headers={
            "Content-Type": "application/json",
            "X-Goog-Api-Key": key,
            "X-Goog-FieldMask": (
                "places.displayName,places.formattedAddress,places.location"
            ),
        },
        method="POST",
    )
    payload = _fetch_json(fetch, request)
    places = payload.get("places")
    if not isinstance(places, list) or not places:
        return None
    place = places[0]
    if not isinstance(place, dict):
        return None
    location = place.get("location")
    if not isinstance(location, dict):
        return None
    display_name = place.get("displayName")
    if isinstance(display_name, dict):
        display_name = display_name.get("text")
    label = display_name or place.get("formattedAddress")
    if not isinstance(label, str) or not label.strip():
        return None
    return {
        "label": label.strip(),
        "lat": float(location["latitude"]),
        "lon": float(location["longitude"]),
        "type": "google",
        "source": "places",
    }


def _geocoding_result(query: str, key: str, fetch) -> dict | None:
    url = f"{GEOCODING_URL}?{urlencode({
        'address': query,
        'components': 'country:BE',
        'language': 'nl',
        'key': key,
    })}"
    payload = _fetch_json(fetch, urllib.request.Request(url, method="GET"))
    results = payload.get("results")
    if not isinstance(results, list) or not results:
        return None
    result = results[0]
    if not isinstance(result, dict):
        return None
    geometry = result.get("geometry")
    location = geometry.get("location") if isinstance(geometry, dict) else None
    label = result.get("formatted_address")
    if (
        not isinstance(location, dict)
        or not isinstance(label, str)
        or not label.strip()
    ):
        return None
    return {
        "label": label.strip(),
        "lat": float(location["lat"]),
        "lon": float(location["lng"]),
        "type": "google",
        "source": "geocoding",
    }


def _resolve(query: str, key: str, fetch) -> dict | None:
    try:
        result = _places_result(query, key, fetch)
    except Exception:
        result = None
    if result is not None:
        return result
    try:
        return _geocoding_result(query, key, fetch)
    except Exception:
        return None


@lru_cache(maxsize=256)
def _resolve_cached(query: str, key: str, fetch) -> dict | None:
    return _resolve(query, key, fetch)


def resolve(query: str, *, fetch=_http_fetch) -> dict | None:
    """Zoek ``query`` via Google Maps wanneer de API-key geconfigureerd is."""
    key = os.environ.get("LUSMAKER_GOOGLE_MAPS_KEY", "").strip()
    query = query.strip()
    if not key or not query:
        return None
    return _resolve_cached(query, key, fetch)


resolve.cache_clear = _resolve_cached.cache_clear
