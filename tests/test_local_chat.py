import json
from pathlib import Path
from tempfile import TemporaryDirectory

from lusmaker.local_chat import run_prompt
from lusmaker.aws_chat import lookup_place
from lusmaker.codex_chat import CodexRouteAgent
import sys
from types import SimpleNamespace


class Agent:
    def __init__(self):
        self.histories = []

    def reply(self, history, *, request_id):
        self.histories.append(list(history))
        print("diagnostiek hoort niet in stdout")
        return {"content": "De parking is niet geverifieerd.", "route_ids": [], "ready_route_ids": []}


def test_local_conversation_preserves_prompt_and_followup():
    with TemporaryDirectory() as root:
        agent = Agent()
        first = run_prompt("Een wandeling van 3 km", root, agent=agent)
        result = run_prompt("Graag langs het strand", root, session=first["session"], agent=agent)
        state = json.loads(Path(result["log"]).read_text())
        assert len(state["messages"]) == 4
        assert agent.histories[1][0]["content"] == "Een wandeling van 3 km"
        assert result["ready_route_ids"] == []
        assert len(state["runs"]) == 2


def test_local_failure_retains_prompt_for_diagnosis():
    class Broken:
        def reply(self, history, *, request_id):
            raise RuntimeError("router niet bereikbaar")
    with TemporaryDirectory() as root:
        try:
            run_prompt("Bredene", root, agent=Broken())
            assert False
        except RuntimeError as exc:
            assert "log:" in str(exc)
        state = json.loads(next(Path(root).glob("conversations/*.json")).read_text())
        assert state["runs"][0]["error"] == "router niet bereikbaar"
        assert state["messages"][0]["content"] == "Bredene"


def test_local_session_cannot_escape_directory():
    with TemporaryDirectory() as root:
        try:
            run_prompt("Hallo", root, session="../../outside", agent=Agent())
            assert False
        except ValueError:
            pass
        assert not list(Path(root).iterdir())


def test_lookup_does_not_infer_access_from_a_geocoded_point():
    result = lookup_place("hotel", resolver=lambda q: ({"lat": 51.25, "lon": 2.97}, []))
    assert result["candidate"]["lat"] == 51.25
    assert all(v == "unknown" for v in result["verification"].values())


def test_codex_provider_uses_mcp_evidence_and_never_bedrock():
    def runner(command, **kwargs):
        assert "--ignore-user-config" in command
        assert command[command.index("--sandbox") + 1] == "read-only"
        assert not any(key.startswith("AWS_") for key in kwargs["env"])
        output = Path(command[command.index("--output-last-message") + 1])
        output.write_text(json.dumps({"content": "De route is klaar."}))
        (output.parent / "tools.jsonl").write_text(json.dumps({"name": "plan_route", "output": {"draft": "real-id", "status": "needs_input"}}) + "\n")
        return SimpleNamespace(returncode=0)
    with TemporaryDirectory() as root:
        result = run_prompt("Een wandeling", root, agent=CodexRouteAgent(root, executable=sys.executable, runner=runner))
        assert result["provider"] == "codex"
        assert result["route_ids"] == ["real-id"]
        assert result["ready_route_ids"] == []  # Modelproza is geen bewijs.
        assert len(result["trace"]) == 1


def test_codex_failure_does_not_fallback_to_bedrock():
    with TemporaryDirectory() as root:
        agent = CodexRouteAgent(root, executable=sys.executable, runner=lambda *a, **kw: SimpleNamespace(returncode=7))
        try:
            run_prompt("Een wandeling", root, agent=agent)
            assert False
        except RuntimeError as exc:
            assert "exit 7" in str(exc)


def test_nearby_places_preserves_private_access_and_center_uncertainty():
    from lusmaker.place_search import nearby_places
    payload = {"elements": [{"type": "way", "id": 123,
        "center": {"lat": 51.25, "lon": 2.97}, "tags": {"amenity": "parking", "access": "private"}}]}
    result = nearby_places(51.25, 2.97, "parking", fetch=lambda query: payload)
    candidate = result["candidates"][0]
    assert candidate["tags"]["access"] == "private"
    assert candidate["coordinate_kind"] == "area_center"
    assert candidate["source"].endswith("/way/123")
    assert "geen geverifieerde ingangen" in result["warning"]


def test_nearby_places_rejects_invalid_queries_before_fetch():
    from lusmaker.place_search import nearby_places
    for values in [(float("nan"), 2, "parking", 500), (91, 2, "parking", 500), (51, 2, "anything", 500), (51, 2, "parking", 3000)]:
        try:
            nearby_places(*values, fetch=lambda q: (_ for _ in ()).throw(AssertionError("geen netwerk")))
            assert False
        except ValueError:
            pass
