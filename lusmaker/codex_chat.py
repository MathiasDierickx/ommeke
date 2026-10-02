"""Codex CLI-provider: eigen login, lokale MCP, geen Bedrock-fallback."""
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys

from .aws_chat import SYSTEM_PROMPT


class CodexRouteAgent:
    def __init__(self, workspace, *, model=None, executable="codex", timeout=600, runner=subprocess.run):
        self.workspace = Path(workspace).resolve()
        self.model = model
        self.executable = executable
        self.timeout = timeout
        if timeout <= 0:
            raise ValueError("timeout moet positief zijn")
        self.runner = runner

    def reply(self, history, *, request_id):
        binary = shutil.which(self.executable)
        if not binary:
            raise RuntimeError("Codex CLI ontbreekt; installeer Codex en voer codex login uit")
        run_dir = self.workspace / "codex" / request_id
        run_dir.mkdir(parents=True, exist_ok=False)
        schema = run_dir / "answer.schema.json"
        schema.write_text(json.dumps({"type": "object", "properties": {"content": {"type": "string"}},
                                      "required": ["content"], "additionalProperties": False}))
        output = run_dir / "answer.json"
        trace = run_dir / "tools.jsonl"
        env = {key: value for key, value in os.environ.items() if not key.startswith("AWS_")}
        settings = {
            "features.shell_tool": False,
            "features.multi_agent": False,
            "mcp_servers.lusmaker.command": sys.executable,
            "mcp_servers.lusmaker.args": ["-m", "lusmaker.chat_mcp"],
            "mcp_servers.lusmaker.required": True,
            "mcp_servers.lusmaker.default_tools_approval_mode": "approve",
            "mcp_servers.lusmaker.tool_timeout_sec": 300,
            "mcp_servers.lusmaker.env.LUSMAKER_HOME": str(self.workspace),
            "mcp_servers.lusmaker.env.LUSMAKER_STATE_BUCKET": "",
            "mcp_servers.lusmaker.env.LUSMAKER_CHAT_TRACE": str(trace),
            "mcp_servers.lusmaker.env.LUSMAKER_CHAT_REQUEST": request_id,
            "mcp_servers.lusmaker.env.PYTHONPATH": str(Path(__file__).resolve().parent.parent),
        }
        for key in ("LUSMAKER_GH_URL", "LUSMAKER_REGION"):
            if key in env:
                settings[f"mcp_servers.lusmaker.env.{key}"] = env[key]
        command = [binary, "--search", "exec", "--ignore-user-config", "--ephemeral", "--skip-git-repo-check",
                   "--sandbox", "read-only", "--cd", str(run_dir), "--json", "--color", "never",
                   "--output-schema", str(schema), "--output-last-message", str(output)]
        for key, value in settings.items():
            command.extend(["-c", f"{key}={json.dumps(value)}"])
        if self.model:
            command.extend(["--model", self.model])
        command.append("-")
        instructions = SYSTEM_PROMPT.replace("Je hebt geen algemene webzoektool.", "Gebruik webzoeken voor officiële plaatsinformatie en citeer de bronnen.")
        prompt = instructions + "\nJe bent routeplanner, geen programmeur. Gebruik uitsluitend webzoeken en lusmaker MCP; geen shell, codewijzigingen of runtimebeheer. Alle routetools lopen via route_tool(name, arguments).\nGesprek:\n" + json.dumps(history, ensure_ascii=False)
        try:
            with (run_dir / "events.jsonl").open("w") as stdout, (run_dir / "stderr.log").open("w") as stderr:
                result = self.runner(command, input=prompt, text=True, stdout=stdout, stderr=stderr, env=env, timeout=self.timeout)
        except subprocess.TimeoutExpired as exc:
            raise RuntimeError(f"Codex antwoordde niet binnen {self.timeout} seconden; log: {run_dir}") from exc
        if result.returncode != 0 or not output.exists():
            raise RuntimeError(f"Codex kon het verzoek niet afronden (exit {result.returncode}); log: {run_dir}")
        answer = json.loads(output.read_text())
        if not isinstance(answer.get("content"), str) or not answer["content"].strip():
            raise RuntimeError("Codex gaf geen geldig tekstantwoord")
        events = [json.loads(line) for line in trace.read_text().splitlines()] if trace.exists() else []
        routes, ready = set(), set()
        for event in events:
            value = event.get("output", {})
            route_id = value.get("draft")
            if isinstance(route_id, str):
                routes.add(route_id)
                if value.get("status") == "ready":
                    ready.add(route_id)
                elif value.get("status") == "needs_input":
                    ready.discard(route_id)
        return {"content": answer["content"], "route_ids": sorted(routes), "ready_route_ids": sorted(ready),
                "provider": "codex", "trace": events, "provider_log": str(run_dir)}
