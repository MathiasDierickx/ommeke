"""Lokale componentcontrole zonder routing, deployment of cloudcredentials."""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time

ROOT = Path(__file__).resolve().parent.parent
GROUPS = {
    "engine": ["analysis", "climbs", "gh", "intents", "optimize", "probe", "profiles", "readiness", "suggest", "regression", "quality", "acceptance"],
    "data": ["discover", "geocode", "google_geocode", "heat", "osm", "provision", "regions", "recording", "pack_manifest", "route_sources"],
    "api": ["aws_app", "aws_chat", "aws_sharing", "aws_state", "draft_storage", "user_scope", "oauth", "quotas", "account", "pagination", "telemetry", "requests", "pilot", "route_library"],
    "mcp": ["mcp", "mcp_evals", "appsdk", "artifacts", "preview", "contracts"],
    "infra": ["aws_deploy"],
    "tooling": ["checks", "e2e_prod", "metrics", "local_chat"],
}


class JsonParser(argparse.ArgumentParser):
    def error(self, message):
        raise ValueError(message)


def available() -> dict:
    modules = {p.stem.removeprefix("test_") for p in (ROOT / "tests").glob("test_*.py")}
    return {name: [m for m in names if m in modules] for name, names in GROUPS.items()}


def commands(component: str) -> list[list[str]]:
    if component == "all":
        return [[sys.executable, "-m", "tests.run", "--json"]]
    if component == "scenarios":
        return [[sys.executable, "-m", "tests.scenarios"]]
    if component == "web":
        return [["npm", "run", "typecheck"], ["npm", "run", "test:unit"], ["npm", "run", "build"]]
    groups = available()
    if component not in groups:
        raise ValueError(f"onbekende component: {component}")
    if not groups[component]:
        raise ValueError(f"geen tests voor component: {component}")
    return [[sys.executable, "-m", "tests.run", "--json", *groups[component]]]


def run(component: str, *, runner=subprocess.run, timeout: int = 600) -> dict:
    results = []
    with tempfile.TemporaryDirectory(prefix="lus-check-") as home:
        env = {k: v for k, v in os.environ.items() if not k.startswith(("LUSMAKER_", "AWS_", "GOOGLE_"))}
        env.update(LUSMAKER_HOME=home, AWS_EC2_METADATA_DISABLED="true", NEXT_TELEMETRY_DISABLED="1")
        for command in commands(component):
            started = time.monotonic()
            try:
                result = runner(command, cwd=ROOT / "web" if component == "web" else ROOT,
                                env=env, text=True, capture_output=True, timeout=timeout)
                output = result.stdout
                try:
                    output = json.loads(output)
                except (ValueError, TypeError):
                    pass
                results.append({"command": command, "ok": result.returncode == 0,
                                "seconds": round(time.monotonic() - started, 3),
                                "output": output, "stderr": result.stderr})
            except (OSError, subprocess.TimeoutExpired) as exc:
                results.append({"command": command, "ok": False, "error": str(exc)})
    return {"component": component, "ok": all(r["ok"] for r in results), "checks": results}


def main(argv=None):
    parser = JsonParser(description="Test Ommeke-componenten afzonderlijk; geen live routing of deployment.")
    parser.add_argument("component", nargs="?", default="all", choices=["all", *GROUPS, "web", "list", "quality", "metrics", "scenarios"])
    parser.add_argument("--input", type=Path, help="route-JSON of geëxporteerde JSON-logevents")
    parser.add_argument("--constraints", type=Path, help="acceptatievoorwaarden als JSON")
    parser.add_argument("--input-per-million", type=float, default=0)
    parser.add_argument("--output-per-million", type=float, default=0)
    parser.add_argument("--timeout", type=int, default=600)
    try:
        args = parser.parse_args(argv)
        if args.timeout <= 0:
            raise ValueError("timeout moet positief zijn")
        if args.component in {"quality", "metrics"}:
            if args.input is None:
                raise ValueError("--input is vereist")
            if args.component == "quality":
                from .quality import evaluate
                if not args.constraints:
                    raise ValueError("--constraints is vereist voor routeacceptatie")
                result = evaluate(json.loads(args.input.read_text()), json.loads(args.constraints.read_text()))
            else:
                from .metrics import read_events, summarize
                result = summarize(read_events(args.input), input_per_million=args.input_per_million, output_per_million=args.output_per_million)
        else:
            result = {"components": {**available(), "web": ["typecheck", "test:unit", "build"]}} if args.component == "list" else run(args.component, timeout=args.timeout)

        if result.get("ok") is False:
            result["error"] = "componentcontrole mislukt"
        print(json.dumps(result, ensure_ascii=False, indent=2))
        if result.get("ok") is False:
            raise SystemExit(1)
    except (ValueError, OSError, TypeError, KeyError) as exc:
        print(json.dumps({"error": str(exc)}, ensure_ascii=False, indent=2))
        raise SystemExit(1)


if __name__ == "__main__":
    main()
