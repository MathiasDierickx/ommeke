"""Herhaalbare, automatisch gescoorde routebenchmark."""
from __future__ import annotations

import json
import math
import statistics
import time
from pathlib import Path

from . import draft as draft_module, geo, intents, quality


def run(cases, *, planner=intents.plan_route, answer=intents.apply_answers,
        load=draft_module.load, clock=time.monotonic) -> dict:
    rows = []
    for case in cases:
        started = clock()
        errors, measurements = [], {}
        try:
            plan = {**case["plan"], "check_readiness": True,
                    "profiel_naam": "standaard", "naam": f"Benchmark {case['id']}",
                    "request_id": f"bench-{case['id']}"}
            result = planner(**plan)
            answered = False
            chose_place = False
            while result.get("status") == "needs_input":
                place_question = "startplaats" in (result.get("onbekend") or [])
                if place_question and not chose_place:
                    answers = {"startplaats": "0"}
                    chose_place = True
                elif not answered:
                    answers = dict(case.get("antwoorden") or {})
                    answered = True
                else:
                    answers = {}
                if not answers:
                    result = answer(result.get("draft") or result.get("id"), {}, klaar=True)
                else:
                    result = answer(result.get("draft") or result.get("id"), answers)
            draft_id = result.get("draft") or result.get("id")
            item = load(draft_id)
            computed = item.get("computed") or {}
            route_request = item.get("route_request") or {}
            route_quality = quality.evaluate(item, {"loop": not route_request.get("eind")})
            geometry = item.get("_geometry") or []
            points = [point[:2] for leg in geometry for point in leg]
            km = route_quality.get("metrics", {}).get("km")
            spread = (max(geo.haversine(*points[0], *point) for point in points) / (km * 1000)
                      if points and km else None)
            why = intents.explain_route(item)
            criteria_ok = sorted(row.get("id") for row in why if row.get("ok"))
            measurements = {"km": km, "doel_km": route_request.get("target_km") or route_request.get("max_km"),
                            "hm": computed.get("ascend_m"), "sluiting_m": route_quality.get("metrics", {}).get("closure_m"),
                            "heen_en_weer_m": geo.self_retrace_m(geometry), "spreiding": spread,
                            "criteria_ok": criteria_ok, "waarom": why, "kwaliteit": route_quality.get("metrics", {}),
                            "status": result.get("status", "ready"), "seconden": round(clock() - started, 3),
                            "draft": draft_id}
            expected = case["verwacht"]
            target = route_request.get("target_km")
            # Alleen een expliciet maximum is hard; doel + tolerantie is een zacht plafond.
            maximum = route_request.get("max_km") if route_request.get("max_km_explicit", True) else None
            if target and km is not None and abs(km - target) / target * 100 > expected["km_tolerantie_pct"]:
                errors.append(f"afstand {km} km buiten tolerantie van {target} km")
            elif maximum and km is not None and km > maximum:
                errors.append(f"afstand {km} km overschrijdt maximum van {maximum} km")
            if measurements["heen_en_weer_m"] > expected.get("max_heen_en_weer_m", math.inf):
                errors.append("te veel heen-en-weer")
            if route_request.get("eind") is None and measurements["sluiting_m"] is not None and measurements["sluiting_m"] > expected.get("max_sluiting_m", math.inf):
                errors.append("lus sluit onvoldoende")
            if spread is not None and spread > expected.get("max_spreiding", math.inf):
                errors.append("lus is onvoldoende gespreid")
            missing = set(expected.get("criteria_ok", [])) - set(criteria_ok)
            if missing:
                errors.append("criteria niet ok: " + ", ".join(sorted(missing)))
            if measurements["seconden"] > expected["max_seconden"]:
                errors.append("duurtijd overschreden")
            if not route_quality.get("metrics", {}).get("km"):
                errors.extend(route_quality.get("failures", []))
        except Exception as exc:  # Eén slechte route mag de batch niet stoppen.
            errors.append(str(exc))
            measurements["seconden"] = round(clock() - started, 3)
        rows.append({"id": case["id"], "regio": case.get("regio"), "ok": not errors,
                     "fouten": errors, "metingen": measurements})
    durations = [r["metingen"]["seconden"] for r in rows]
    regions = {}
    activities = {}
    for row, case in zip(rows, cases):
        for group, name in ((regions, row.get("regio")), (activities, case.get("plan", {}).get("activiteit"))):
            if name:
                group.setdefault(name, {"geslaagd": 0, "totaal": 0})
                group[name]["totaal"] += 1
                group[name]["geslaagd"] += int(row["ok"])
    return {"cases": rows, "summary": {"geslaagd": sum(r["ok"] for r in rows), "totaal": len(rows),
            "per_regio": regions, "per_activiteit": activities,
            "p50_seconden": _percentile(durations, .5), "p95_seconden": _percentile(durations, .95)}}


def _percentile(values, fraction):
    if not values:
        return None
    ordered = sorted(values)
    return round(ordered[max(0, math.ceil(fraction * len(ordered)) - 1)], 3)


def markdown(report: dict) -> str:
    lines = ["| id | regio | km/doel | hm | spreiding | criteria ok | duur | ok |",
             "|---|---|---:|---:|---:|---|---:|:---:|"]
    for case in report.get("cases", []):
        m = case.get("metingen", {})
        lines.append(f"| {case['id']} | {case.get('regio', '')} | {m.get('km', '—')} / {m.get('doel_km', '—')} | {m.get('hm', '—')} | {m.get('spreiding', '—')} | {', '.join(m.get('criteria_ok', []))} | {m.get('seconden', '—')} s | {'✓' if case.get('ok') else '✗'} |")
    return "\n".join(lines) + "\n"


def load_cases(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))
