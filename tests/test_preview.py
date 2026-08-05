"""Pure tests voor de zelfstandige HTML-kaartpreview."""

import tempfile
from pathlib import Path

from lusmaker import draft as draft_mod
from lusmaker import preview


def _draft():
    return {
        "id": "abc123",
        "name": "Ronde van <Wetteren>",
        "start": {"lat": 50.98, "lon": 3.87, "label": "Wetteren"},
        "climbs": ["testklim"],
        "computed": {
            "total_km": 2.4,
            "ascend_m": 61,
            "legs": [
                {"from": "start", "to": "Testklim (voet)", "km": 1.2, "ascend_m": 11},
                {
                    "from": "Testklim (voet)",
                    "to": "Testklim (top)",
                    "km": 1.2,
                    "ascend_m": 50,
                    "climb": "testklim",
                },
            ],
            "kwaliteit": {"kassei_m": 25, "steenweg_m": 100, "steenweg_kruisingen": 2},
        },
        "_geometry": [
            [[50.98, 3.87, 10], [50.981, 3.871, 21]],
            [[50.981, 3.871, 21], [50.982, 3.872, 45], [50.983, 3.873, 71]],
        ],
    }


def _climbs():
    return {
        "testklim": {
            "name": "Testklim",
            "top": [50.983, 3.873],
            "length_m": 1200,
            "avg_pct": 4.2,
            "max_pct": 8.1,
        }
    }


def test_render_contains_route_climb_and_profile():
    document = preview.render(_draft(), _climbs())

    assert "Ronde van &lt;Wetteren&gt;" in document
    assert "Testklim" in document
    assert document.count("L.polyline(") == 2
    assert document.count("<svg ") == 1
    assert "#dc2626" in document
    assert "fitBounds" in document


def test_render_handles_missing_elevations_and_popularity():
    draft = _draft()
    draft["_geometry"][0][0][2] = None
    draft["computed"]["kwaliteit"].pop("populair_pct", None)

    document = preview.render(draft, _climbs())

    assert "Hoogteprofiel" in document
    assert "populair" not in document


def test_render_requires_a_routed_draft():
    draft = _draft()
    draft.pop("_geometry")

    try:
        preview.render(draft, _climbs())
    except draft_mod.DraftError as exc:
        assert str(exc) == "routeer eerst: `lus draft route <id>`"
    else:
        raise AssertionError("ongerouteerde draft kreeg een preview")


def test_export_writes_html_and_returns_route_totals():
    with tempfile.TemporaryDirectory() as temp_dir:
        path = str(Path(temp_dir) / "preview.html")
        result = preview.export(_draft(), _climbs(), path)

        assert Path(path).read_text(encoding="utf-8").startswith("<!doctype html>")
        assert result == {"file": path, "total_km": 2.4, "ascend_m": 61}


def test_downsample_uses_one_global_point_budget():
    legs = [
        [[50.0 + i / 10000, 3.0, None] for i in range(1000)],
        [[51.0 + i / 10000, 4.0, None] for i in range(1000)],
    ]

    sampled = preview._downsample(legs)

    assert sum(len(leg) for leg in sampled) == preview.MAX_ROUTE_POINTS
    assert sampled[0][0] == legs[0][0]
    assert sampled[1][-1] == legs[1][-1]
