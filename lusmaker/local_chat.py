"""Lokale promptflow met dezelfde agent en routetools als de hosted app."""
from contextlib import contextmanager, redirect_stdout
import json
import os
from pathlib import Path
import shutil
import sys
import uuid

from . import config
from .aws_chat import BedrockRouteAgent, MAX_PROMPT_CHARS, RouteToolExecutor


class TraceTools(RouteToolExecutor):
    def __init__(self):
        self.events = []

    def execute(self, name, arguments, *, request_id):
        event = {"name": name, "input": arguments}
        self.events.append(event)
        try:
            result = super().execute(name, arguments, request_id=request_id)
            event["output"] = result
            return result
        except Exception as exc:
            event["error"] = str(exc)
            raise


@contextmanager
def workspace_context(workspace, *, region=None, gh_url=None):
    """Kopieer caches eenmalig; schrijf nooit in de bestaande runtime."""
    target = Path(workspace).expanduser().resolve()
    source = config.home_path().resolve()
    if target == source or target.is_relative_to(source):
        raise ValueError("kies een werkmap buiten de bestaande LUSMAKER_HOME")
    original = config.get_region(region)
    target.mkdir(parents=True, exist_ok=True)
    if not (target / config.REGISTRY_FILENAME).exists():
        local = config.register_region(original.slug, original.geofabrik,
                                       original.bbox, original.gh_port, home=target)
        if original.cache.exists():
            shutil.copytree(original.cache, local.cache, dirs_exist_ok=True)
    keys = {"LUSMAKER_HOME": str(target), "LUSMAKER_STATE_BUCKET": ""}
    if gh_url:
        keys["LUSMAKER_GH_URL"] = gh_url
    previous = {key: os.environ.get(key) for key in keys}
    os.environ.update(keys)
    try:
        with config.use_region(region):
            yield target
    finally:
        for key, value in previous.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value


def run_prompt(prompt, workspace, *, session=None, agent=None, trace=None):
    prompt = prompt.strip()
    if not prompt or len(prompt) > MAX_PROMPT_CHARS:
        raise ValueError(f"geef een bericht van 1 tot {MAX_PROMPT_CHARS} tekens")
    session_id = str(uuid.UUID(session)) if session else str(uuid.uuid4())
    directory = Path(workspace) / "conversations"
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / f"{session_id}.json"
    if session and not path.exists():
        raise ValueError("lokaal gesprek niet gevonden")
    state = json.loads(path.read_text()) if path.exists() else {"id": session_id, "messages": [], "runs": []}
    tools = trace if trace is not None else TraceTools()
    # Ook initialisatiefouten bewaren; de oorspronkelijke prompt blijft reproduceerbaar.
    turn = {"prompt": prompt, "request_id": str(uuid.uuid4())}
    state["messages"].append({"role": "user", "content": prompt})
    try:
        with redirect_stdout(sys.stderr):
            result = (agent or BedrockRouteAgent(tool_executor=tools)).reply(
                state["messages"], request_id=turn["request_id"])
        state["messages"].append({"role": "assistant", "content": result["content"]})
        turn["result"] = result
    except Exception as exc:
        turn["error"] = str(exc)
        raise RuntimeError(f"{exc} (gesprek: {session_id}; log: {path})") from exc
    finally:
        turn["trace"] = turn.get("result", {}).get("trace", tools.events)
        state["runs"].append(turn)
        temporary = path.with_suffix(".tmp")
        temporary.write_text(json.dumps(state, ensure_ascii=False, indent=2) + "\n")
        temporary.replace(path)
    return {"session": session_id, "log": str(path), **result, "trace": turn["trace"]}


def command(args):
    with workspace_context(args.workspace, region=args.region, gh_url=args.gh_url) as workspace:
        if args.provider == "codex":
            from .codex_chat import CodexRouteAgent
            agent = CodexRouteAgent(workspace, model=args.model, timeout=args.timeout)
            return run_prompt(args.prompt, workspace, session=args.session, agent=agent)
        client = None
        if args.aws_profile or args.aws_region:
            import boto3
            client = boto3.Session(profile_name=args.aws_profile, region_name=args.aws_region).client("bedrock-runtime")
        tools = TraceTools()
        agent = BedrockRouteAgent(client=client, model_id=args.model, tool_executor=tools)
        return run_prompt(args.prompt, workspace, session=args.session, agent=agent, trace=tools)
