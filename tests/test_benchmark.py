"""Offline tests for the route benchmark."""
import json
from pathlib import Path

from lusmaker import activities, benchmark, criteria


def test_corpus_schema_and_coverage():
    cases = json.loads((Path(__file__).parents[1] / "evals/route_benchmark.json").read_text())
    assert len(cases) >= 28
    assert len({case["regio"] for case in cases}) >= 8
    assert set(activities.KEYS) <= {case["plan"]["activiteit"] for case in cases}
    assert {metric for case in cases for metric in (c["metriek"] for c in case["plan"]["criteria"])} == set(criteria.METRICS)
    for case in cases:
        assert {"id", "beschrijving", "regio", "plan", "verwacht"} <= case.keys()
        assert {"km_tolerantie_pct", "max_heen_en_weer_m", "max_seconden", "criteria_ok"} <= case["verwacht"].keys()
        if "eind" not in case["plan"]:
            assert {"max_sluiting_m", "max_spreiding"} <= case["verwacht"].keys()


def test_run_scores_and_handles_input_loop_and_case_errors():
    cases = [
        {"id": "pass", "regio": "Gent", "plan": {"start": "Gent"}, "antwoorden": {"heuvels": "ok"}, "verwacht": {"km_tolerantie_pct": 30, "max_seconden": 4, "criteria_ok": ["stil"]}},
        {"id": "fail", "regio": "Gent", "plan": {"start": "Gent"}, "verwacht": {"km_tolerantie_pct": 1, "max_seconden": 0}},
        {"id": "error", "regio": "Antwerpen", "plan": {"start": "Antwerpen"}, "verwacht": {"km_tolerantie_pct": 10, "max_seconden": 4}},
    ]
    calls, now = [], iter([0, 1, 2, 3, 4, 5])
    drafts = {}

    def plan(**kwargs):
        calls.append(("plan", kwargs))
        if kwargs["start"] == "Antwerpen":
            raise RuntimeError("buiten gebied")
        return {"status": "needs_input", "draft": kwargs["request_id"]}

    def answer(draft_id, answers, **kwargs):
        calls.append(("answer", answers, kwargs))
        return {"status": "ready", "draft": draft_id}

    def load(draft_id):
        drafts[draft_id] = {"id": draft_id, "computed": {"total_km": 20, "ascend_m": 100, "kwaliteit": {"heen_en_weer_m": 5, "stil_pct": 80}}, "_geometry": [[(51.0, 3.7), (51.05, 3.75), (51.1, 3.7), (51.0, 3.7)]], "route_request": {"target_km": 20, "activiteit": "toerfiets", "criteria": [{"id": "stil", "label": "stil", "metriek": "stil", "richting": "hoog", "gewicht": 1, "hard": False, "drempel": 0.4}]}}
        return drafts[draft_id]

    result = benchmark.run(cases, planner=plan, answer=answer, load=load, clock=lambda: next(now))
    assert result["summary"]["geslaagd"] == 1
    assert [row["ok"] for row in result["cases"]] == [True, False, False]
    assert calls[1][1] == {"heuvels": "ok"}
    assert calls[0][1]["request_id"].startswith("bench-")
    assert result["cases"][0]["metingen"]["criteria_ok"] == ["stil"]
    assert "buiten gebied" in result["cases"][2]["fouten"][0]


def test_reports_include_markdown_and_cli_arguments():
    md = benchmark.markdown({"cases": [{"id": "a", "regio": "Gent", "metingen": {"km": 10, "doel_km": 10, "hm": 20, "spreiding": 0.2, "criteria_ok": [], "seconden": 1}, "ok": True}]})
    assert "| id | regio | km/doel | hm | spreiding | criteria ok | duur | ok |" in md
    from lusmaker.cli import main
    import argparse
    from lusmaker import cli
    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers()
    cli.add_benchmark_parser(sub)
    args = parser.parse_args(["benchmark", "--only", "a,b", "--opruimen"])
    assert args.only == "a,b" and args.opruimen


def test_needs_input_place_selection_uses_first_candidate():
    answers = []
    case = {"id": "place", "plan": {"start": "Markt, Gent"}, "verwacht": {"km_tolerantie_pct": 100, "max_seconden": 3}}
    def planner(**_kwargs):
        return {"status": "needs_input", "draft": "bench-place", "onbekend": ["startplaats"]}
    def answer(_draft_id, values, **kwargs):
        answers.append((values, kwargs))
        return {"status": "ready", "draft": "bench-place"}
    def load(_draft_id):
        return {"id": "bench-place", "computed": {"total_km": 1, "ascend_m": 0}, "_geometry": [[(51, 3), (51.001, 3)]], "route_request": {"target_km": 1}}
    benchmark.run([case], planner=planner, answer=answer, load=load)
    assert answers == [({"startplaats": "0"}, {})]
