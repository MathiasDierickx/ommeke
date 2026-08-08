"""Netwerkloze scorer voor opgenomen MCP-toolkeuzes van een LLM."""

from __future__ import annotations

import argparse
import json
from pathlib import Path


def _contains(actual, expected) -> bool:
    if isinstance(expected, dict):
        return isinstance(actual, dict) and all(
            key in actual and _contains(actual[key], value)
            for key, value in expected.items()
        )
    if isinstance(expected, list):
        return actual == expected
    return actual == expected


def score(cases: list[dict], calls: list[dict]) -> dict:
    """Score toolnaam, verwachte argumentsubset en verplichte argumenten."""
    calls_by_id = {call.get("id"): call for call in calls}
    results = []
    for case in cases:
        call = calls_by_id.get(case["id"])
        errors = []
        if call is None:
            errors.append("toolcall ontbreekt")
        else:
            if call.get("tool") != case["expected_tool"]:
                errors.append(
                    f"tool is {call.get('tool')!r}, verwacht {case['expected_tool']!r}"
                )
            arguments = call.get("arguments")
            if not isinstance(arguments, dict):
                errors.append("arguments is geen object")
            else:
                expected = case.get("expected_arguments", {})
                if not _contains(arguments, expected):
                    errors.append("verwachte argumentsubset ontbreekt of wijkt af")
                for name in case.get("required_arguments", []):
                    if arguments.get(name) in (None, "", []):
                        errors.append(f"verplicht argument {name!r} ontbreekt")
        results.append(
            {
                "id": case["id"],
                "prompt": case["prompt"],
                "geslaagd": not errors,
                "fouten": errors,
            }
        )
    passed = sum(result["geslaagd"] for result in results)
    total = len(results)
    return {
        "geslaagd": passed,
        "totaal": total,
        "score_pct": round(passed / max(total, 1) * 100, 1),
        "cases": results,
    }


def load(path: str | Path) -> list[dict]:
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(data, list):
        raise ValueError("evalbestand moet een JSON-lijst zijn")
    return data


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(prog="python -m lusmaker.mcp_evals")
    parser.add_argument("calls", help="JSON met opgenomen toolcalls per case-id")
    parser.add_argument(
        "--cases",
        default=str(Path(__file__).parents[1] / "evals" / "route_intents.json"),
    )
    args = parser.parse_args(argv)
    result = score(load(args.cases), load(args.calls))
    print(json.dumps(result, ensure_ascii=False, indent=2))
    raise SystemExit(0 if result["geslaagd"] == result["totaal"] else 1)


if __name__ == "__main__":
    main()
