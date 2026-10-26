"""Pure tests voor publieke route-index en veilige payloads."""

from lusmaker import aws_sharing
from lusmaker.aws_api import public_route_payload


def test_share_reference_helpers_use_minimal_global_index():
    stored = {}

    def put(path, value, *, create_only=False):
        assert create_only is True
        stored[path] = value

    token = "a" * 32
    reference = aws_sharing.store_reference(
        token, "user-123", "route-1", put_fn=put
    )

    assert reference == {"uid": "user-123", "draft_id": "route-1"}
    assert stored == {
        f"shares/{token}.json": {"uid": "user-123", "draft_id": "route-1"}
    }
    assert aws_sharing.load_reference(
        token, get_fn=lambda path: stored.get(path)
    ) == reference

    deleted = []
    aws_sharing.delete_reference(token, delete_fn=deleted.append)
    assert deleted == [f"shares/{token}.json"]


def test_public_route_payload_is_an_explicit_pii_free_allowlist():
    item = {
        "id": "privé-id",
        "name": "Rondje Vlaamse Ardennen",
        "profile": "quiet",
        "region": "belgium",
        "owner_email": "fietser@example.com",
        "share_token": "geheim",
        "start": {
            "lat": 50.8,
            "lon": 3.7,
            "label": "Kerkstraat 12, Zottegem",
        },
        "climbs": ["berg-1"],
        "computed": {
            "total_km": 42.1,
            "ascend_m": 620,
            "kwaliteit": {"offroad_pct": 12},
            "legs": [],
        },
        "_geometry": [[[50.8, 3.7, 31], [50.81, 3.71, 44]]],
        "stop_onderweg": {"kind": "speeltuin", "name": "speeltuin", "at_km": 3.2, "lat": 50.805, "lon": 3.705, "id": "tvl:1", "leg_index": 0},
    }

    payload = public_route_payload(item)

    # De stop is een publieke plek, geen PII: de kaart mag er een marker voor tonen.
    assert payload["geometry"]["stop"] == {"soort": "speeltuin", "naam": "speeltuin", "km": 3.2, "lat": 50.805, "lon": 3.705}

    assert set(payload) == {
        "name",
        "activity",
        "region",
        "climbs",
        "total_km",
        "elevation_gain_m",
        "geometry",
        "kwaliteit",
    }
    assert payload["geometry"]["start"] == {"lat": 50.8, "lon": 3.7}
    serialized = repr(payload)
    assert "Kerkstraat" not in serialized
    assert "fietser@example.com" not in serialized
    assert "geheim" not in serialized
    assert "privé-id" not in serialized
