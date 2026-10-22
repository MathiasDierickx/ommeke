import json
import os
import tempfile
from pathlib import Path

from lusmaker import analysis, criteria, criteria_routing, geo, omgeving
from lusmaker.chat_contracts import CRITERIA_SCHEMA
from lusmaker.mcp_contracts import Criterium


def test_polygon_and_lit_line_rasterize_to_cells():
    ring = [(50.0, 4.0), (50.003, 4.0), (50.003, 4.003), (50.0, 4.003), (50.0, 4.0)]
    forest = omgeving.polygon_cells(ring)
    assert forest and geo.cell(50.0015, 4.0015) in forest
    lit = omgeving.line_cells([(50.0, 4.0), (50.004, 4.0)])
    assert lit and geo.cell(50.002, 4.0) in lit


def test_route_stats_environment_cache_optional_and_steps_from_details():
    coords = [[50.0, 4.0, 0], [50.001, 4.0, 0], [50.002, 4.0, 0]]
    with tempfile.TemporaryDirectory() as tmp:
        previous = os.environ.get("LUSMAKER_HOME")
        os.environ["LUSMAKER_HOME"] = tmp
        path = Path(tmp) / "omgeving_cells.json"
        original_cache_path = omgeving.cache_path
        omgeving.cache_path = lambda: path
        assert omgeving.load(path) is None
        stats = analysis.route_stats([coords], [{"road_class": [[0, 1, "steps"], [1, 2, "residential"]]}])
        assert stats["trappen_m"] > 100 and "bos_pct" not in stats
        cells = [geo.cell(*point[:2]) for point in coords]
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps({"bos": [list(c) for c in cells], "verlicht": [list(c) for c in cells]}))
        stats = analysis.route_stats([coords], [{}])
        assert stats["bos_pct"] == 100 and stats["verlicht_pct"] == 100
        if previous is None:
            os.environ.pop("LUSMAKER_HOME", None)
        else:
            os.environ["LUSMAKER_HOME"] = previous
        omgeving.cache_path = original_cache_path


def test_new_criteria_directions_explanation_and_routing_rule():
    spec = criteria.parse([
        {"metriek": "bos"}, {"metriek": "verlicht"}, {"metriek": "trappen"},
        {"metriek": "trappen", "id": "buggy", "hard": True, "drempel": 0},
    ])
    assert [c["richting"] for c in spec] == ["hoog", "hoog", "laag", "laag"]
    why = criteria.explain(spec[:3], {"bos_pct": 62, "verlicht_pct": 80, "trappen_m": 120}, {"total_km": 4})
    assert [item["tekst"] for item in why] == ["62 % door bos", "80 % verlicht", "120 m trappen"]
    rule = criteria_routing.priority_rules(criteria.parse([{"metriek": "trappen"}]), profile="quiet")
    assert rule == [{"if": "road_class == STEPS", "multiply_by": "0.4"}]
    hard = criteria_routing.priority_rules(criteria.parse([{"metriek": "trappen", "hard": True, "drempel": 0}]), profile="quiet")
    assert hard[0]["multiply_by"] == "0.05"
    enum = CRITERIA_SCHEMA["items"]["properties"]["metriek"]["enum"]
    assert all(metric in enum for metric in ("bos", "verlicht", "trappen"))
    assert Criterium.__annotations__["metriek"]
