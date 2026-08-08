"""Pure tests voor de provider-onafhankelijke MCP-evalscorer."""

import json
from pathlib import Path

from lusmaker import mcp_evals


CASES = Path(__file__).parents[1] / "evals" / "route_intents.json"


def test_eval_corpus_has_unique_ids_and_covers_conversation_flow():
    cases = mcp_evals.load(CASES)

    assert len(cases) >= 10
    assert len({case["id"] for case in cases}) == len(cases)
    assert {case["expected_tool"] for case in cases} >= {
        "plan_route",
        "adjust_route",
        "update_profile",
        "ensure_region",
        "region_status",
    }


def test_eval_scorer_accepts_subsets_and_reports_actionable_failures():
    cases = [
        {
            "id": "goed",
            "prompt": "Maak 50 km",
            "expected_tool": "plan_route",
            "expected_arguments": {"target_km": 50},
            "required_arguments": ["request_id"],
        },
        {
            "id": "fout",
            "prompt": "Pas een route aan",
            "expected_tool": "adjust_route",
            "expected_arguments": {"draft_id": "abc123"},
        },
    ]
    calls = [
        {
            "id": "goed",
            "tool": "plan_route",
            "arguments": {
                "target_km": 50,
                "request_id": "retry-1",
                "doel": "hoogtemeters",
            },
        },
        {"id": "fout", "tool": "plan_route", "arguments": {}},
    ]

    result = mcp_evals.score(cases, calls)

    assert result["geslaagd"] == 1
    assert result["totaal"] == 2
    assert result["score_pct"] == 50.0
    assert "verwacht 'adjust_route'" in result["cases"][1]["fouten"][0]
    assert json.dumps(result, ensure_ascii=False)
