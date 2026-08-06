"""GraphHopper-antwoorden opnemen en deterministisch opnieuw afspelen."""
import copy
import hashlib
import json

from . import gh


REPLAY_MISS = (
    "engine-gedrag gewijzigd t.o.v. cassette — herrecord met "
    "tests/record_fixtures.py of controleer je wijziging"
)


def hash_body(body: dict) -> str:
    """Hash een requestbody als canonieke JSON."""
    canonical = json.dumps(
        body,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    ).encode("utf-8")
    return hashlib.sha256(canonical).hexdigest()


def _rounded_coordinates(value, *, in_coordinates: bool = False):
    """Rond alleen getallen onder een GeoJSON/GraphHopper-coordinates-sleutel."""
    if isinstance(value, dict):
        return {
            key: _rounded_coordinates(item, in_coordinates=key == "coordinates")
            for key, item in value.items()
        }
    if isinstance(value, list):
        return [
            _rounded_coordinates(item, in_coordinates=in_coordinates)
            for item in value
        ]
    if in_coordinates and isinstance(value, float):
        return round(value, 5)
    return value


class RecordingPost:
    """Callable wrapper die responses per canonieke requesthash verzamelt."""

    def __init__(self, post_fn=gh._post):
        self.post_fn = post_fn
        self.responses: dict[str, dict] = {}

    def __call__(self, path: str, body: dict) -> dict:
        response = _rounded_coordinates(self.post_fn(path, body))
        self.responses[hash_body(body)] = copy.deepcopy(response)
        return response


class ReplayPost:
    """Callable GraphHopper-vervanger die antwoorden uit een fixture serveert."""

    def __init__(self, fixture: dict):
        self.responses = fixture.get("responses", fixture)
        self.used_hashes: set[str] = set()

    def __call__(self, path: str, body: dict) -> dict:
        request_hash = hash_body(body)
        try:
            response = self.responses[request_hash]
        except KeyError as exc:
            raise gh.GhError(f"{REPLAY_MISS} (request {request_hash})") from exc
        self.used_hashes.add(request_hash)
        return copy.deepcopy(response)

    @property
    def unused_hashes(self) -> set[str]:
        return set(self.responses) - self.used_hashes
