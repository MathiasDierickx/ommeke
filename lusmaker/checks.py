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
    "engine": ["analysis", "climbs", "gh", "intents", "optimize", "probe", "profiles", "readiness", "suggest", "regression", "quality"],
    "data": ["discover", "geocode", "google_geocode", "heat", "osm", "provision", "regions", "recording"],
    "api": ["aws_app", "aws_chat", "aws_sharing", "aws_state", "draft_storage", "user_scope", "oauth", "quotas", "account", "pagination", "telemetry", "requests"],
    "mcp": ["mcp", "mcp_evals", "appsdk", "artifacts", "preview", "contracts"],
    "infra": ["aws_deploy"],
    "tooling": ["checks", "e2e_prod"],
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
    parser.add_argument("component", nargs="?", default="all", choices=["all", *GROUPS, "web", "list"])
    parser.add_argument("--timeout", type=int, default=600)
    try:
        args = parser.parse_args(argv)
        if args.timeout <= 0:
            raise ValueError("timeout moet positief zijn")
        result = {"components": {**available(), "web": ["typecheck", "test:unit", "build"]}} if args.component == "list" else run(args.component, timeout=args.timeout)
        if result.get("ok") is False:
            result["error"] = "componentcontrole mislukt"
        print(json.dumps(result, ensure_ascii=False, indent=2))
        if result.get("ok") is False:
            raise SystemExit(1)
    except ValueError as exc:
        print(json.dumps({"error": str(exc)}, ensure_ascii=False, indent=2))
        raise SystemExit(1)


if __name__ == "__main__":
    main()
