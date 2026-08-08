"""Pure MCP-tests in een proces met een geïsoleerde Lusmaker-home."""

import importlib.util
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path
from unittest import SkipTest


EXPECTED_TOOLS = {
    "status",
    "get_profile",
    "update_profile",
    "list_profiles",
    "list_regions",
    "ensure_region",
    "region_status",
    "geocode",
    "list_climbs",
    "new_draft",
    "list_drafts",
    "get_draft",
    "add_climb",
    "remove_climb",
    "avoid_place",
    "unavoid_place",
    "route_draft",
    "route_readiness",
    "suggest_climbs",
    "plan_route",
    "adjust_route",
    "optimize_draft",
    "export_gpx",
    "preview_draft",
}

EXPECTED_LITE_TOOLS = {
    "plan_route",
    "adjust_route",
    "suggest_climbs",
    "route_details",
    "route_readiness",
    "get_profile",
    "update_profile",
    "ensure_region",
    "region_status",
    "list_drafts",
}


def _require_mcp() -> None:
    if importlib.util.find_spec("mcp") is None:
        raise SkipTest("mcp-package ontbreekt; installeer projectdependencies")


def _run_isolated(code: str, home: Path) -> None:
    env = os.environ.copy()
    env["LUSMAKER_HOME"] = str(home)
    result = subprocess.run(
        [sys.executable, "-c", code],
        env=env,
        text=True,
        capture_output=True,
    )
    if result.returncode:
        raise AssertionError(
            f"geïsoleerde MCP-test faalde\nstdout:\n{result.stdout}\n"
            f"stderr:\n{result.stderr}"
        )


def _write_climbs(home: Path) -> None:
    cache = home / "cache"
    cache.mkdir(parents=True)
    climb = {
        "id": "testklim",
        "name": "Testklim",
        "town": "Teststad",
        "length_m": 500,
        "gain_m": 40,
        "avg_pct": 8.0,
        "max_pct": 12.0,
        "warnings": [],
        "foot": [50.8, 3.7],
        "mid": [50.801, 3.7],
        "top": [50.802, 3.7],
    }
    (cache / "climbs.json").write_text(
        json.dumps({"climbs": {"testklim": climb}, "failed": []})
    )


def test_server_has_exact_tools():
    _require_mcp()
    with tempfile.TemporaryDirectory() as temp_dir:
        expected = repr(EXPECTED_TOOLS)
        _run_isolated(
            f"""
import asyncio
from lusmaker import mcp_server

expected = {expected}
server = mcp_server.mcp
if hasattr(server, "_tool_manager"):
    actual = set(server._tool_manager._tools)
else:
    from mcp import Client

    async def tool_names():
        async with Client(server) as client:
            return {{tool.name for tool in await client.list_tools()}}

    actual = asyncio.run(tool_names())
assert actual == expected, (actual, expected)
assert len(actual) == 24
""",
            Path(temp_dir),
        )


def test_lite_server_has_exact_tools():
    _require_mcp()
    with tempfile.TemporaryDirectory() as temp_dir:
        expected = repr(EXPECTED_LITE_TOOLS)
        _run_isolated(
            f"""
import asyncio
from lusmaker import mcp_server

expected = {expected}
server = mcp_server.lite_mcp
if hasattr(server, "_tool_manager"):
    actual = set(server._tool_manager._tools)
else:
    from mcp import Client

    async def tool_names():
        async with Client(server) as client:
            return {{tool.name for tool in await client.list_tools()}}

    actual = asyncio.run(tool_names())
assert actual == expected, (actual, expected)
assert len(actual) == 10
""",
            Path(temp_dir),
        )


def test_lite_server_advertises_typed_contract_and_annotations():
    _require_mcp()
    with tempfile.TemporaryDirectory() as temp_dir:
        _run_isolated(
            """
import asyncio
from lusmaker import mcp_server

async def inspect_contract():
    tools = {tool.name: tool for tool in await mcp_server.lite_mcp.list_tools()}
    plan = tools["plan_route"]
    assert plan.input_schema["properties"]["doel"]["enum"] == [
        "hoogtemeters", "kort", "toeren"
    ]
    max_km = plan.input_schema["properties"]["max_km"]["anyOf"][0]
    assert max_km["exclusiveMinimum"] == 0
    target_km = plan.input_schema["properties"]["target_km"]["anyOf"][0]
    assert target_km["exclusiveMinimum"] == 0
    assert plan.input_schema["properties"]["tolerance_km"]["minimum"] == 0
    assert plan.input_schema["properties"]["profiel_naam"]["default"] == "standaard"
    assert plan.input_schema["properties"]["kasseien"]["default"] is None
    request_id = plan.input_schema["properties"]["request_id"]["anyOf"][0]
    assert request_id["maxLength"] == 128
    adjust = tools["adjust_route"]
    expected_revision = adjust.input_schema["properties"]["expected_revision"][
        "anyOf"
    ][0]
    assert expected_revision["minimum"] == 0
    assert plan.output_schema["properties"]["status"]["enum"] == [
        "ready", "needs_input"
    ]
    assert plan.output_schema["properties"]["draft"]["type"] == "string"
    assert plan.annotations.read_only_hint is False
    assert plan.annotations.open_world_hint is True

    profile = tools["update_profile"]
    profile_schema = profile.input_schema["$defs"]["ProfilePatch"]
    preference_schema = profile.input_schema["$defs"]["PreferencePatch"]
    assert profile_schema["additionalProperties"] is False
    assert preference_schema["additionalProperties"] is False
    assert preference_schema["properties"]["kasseien"]["anyOf"][0]["enum"] == [
        "vermijd", "ok", "graag"
    ]

    drafts = tools["list_drafts"]
    assert drafts.annotations.read_only_hint is True
    assert drafts.annotations.destructive_hint is False
    assert mcp_server.lite_mcp.instructions
    assert mcp_server.lite_mcp.version

asyncio.run(inspect_contract())
""",
            Path(temp_dir),
        )


def test_tool_call_returns_structured_content():
    _require_mcp()
    with tempfile.TemporaryDirectory() as temp_dir:
        _run_isolated(
            """
import asyncio
from lusmaker import mcp_server

async def call_profile():
    result = await mcp_server.lite_mcp.call_tool("get_profile", {})
    assert result.is_error is False
    assert result.structured_content["naam"] == "standaard"
    assert result.content[0].type == "text"

asyncio.run(call_profile())
""",
            Path(temp_dir),
        )


def test_lite_server_exposes_route_artifact_resources():
    _require_mcp()
    with tempfile.TemporaryDirectory() as temp_dir:
        home = Path(temp_dir)
        artifact_dir = home / "exports" / "abc123"
        artifact_dir.mkdir(parents=True)
        (artifact_dir / "route.gpx").write_text("<gpx/>", encoding="utf-8")
        (artifact_dir / "preview.html").write_text("<html></html>", encoding="utf-8")
        _run_isolated(
            """
import asyncio
from lusmaker import mcp_server

async def inspect_resources():
    templates = await mcp_server.lite_mcp.list_resource_templates()
    uris = {str(template.uri_template) for template in templates}
    assert "lusmaker://drafts/{draft_id}/route.gpx" in uris
    assert "lusmaker://drafts/{draft_id}/preview.html" in uris

    contents = await mcp_server.lite_mcp.read_resource(
        "lusmaker://drafts/abc123/route.gpx"
    )
    assert contents[0].content == b"<gpx/>"
    assert contents[0].mime_type == "application/gpx+xml"

asyncio.run(inspect_resources())
""",
            home,
        )


def test_draft_tools_use_isolated_home_and_validate_climbs():
    _require_mcp()
    with tempfile.TemporaryDirectory() as temp_dir:
        home = Path(temp_dir)
        _write_climbs(home)
        _run_isolated(
            """
from lusmaker import draft, mcp_server

created = mcp_server.new_draft(
    start="50.8,3.7", name="mcp-test", vermijd_kasseien=True
)
shown = mcp_server.get_draft(created["id"])
assert shown["id"] == created["id"]
assert shown["name"] == "mcp-test"
assert shown["profile"] == "quiet"
assert shown["avoid_cobbles"] is True
assert shown["revision"] == 1

added = mcp_server.add_climb(
    created["id"], "testklim", expected_revision=shown["revision"]
)
assert added["revision"] == 2
try:
    mcp_server.remove_climb(
        created["id"], "testklim", expected_revision=shown["revision"]
    )
except draft.DraftError as exc:
    assert "huidige revisie 2" in str(exc)
else:
    raise AssertionError("verouderde MCP-mutatie werd aanvaard")

try:
    mcp_server.add_climb(created["id"], "onbekend")
except draft.DraftError as exc:
    assert "onbekende klim 'onbekend'" in str(exc)
else:
    raise AssertionError("onbekende klim werd aanvaard")
""",
            home,
        )


def test_profile_tools_persist_history_and_are_available_in_lite_toolset():
    _require_mcp()
    with tempfile.TemporaryDirectory() as temp_dir:
        _run_isolated(
            """
from lusmaker import mcp_server

default = mcp_server.get_profile()
assert default["naam"] == "standaard"
assert default["voorkeuren"]["kasseien"] is None

updated = mcp_server.update_profile(
    "standaard",
    {"voorkeuren": {"kasseien": "graag"}},
)
assert updated["historiek"][-1]["bron"] == "mcp"
assert mcp_server.list_profiles()["profielen"][0]["naam"] == "standaard"
""",
            Path(temp_dir),
        )


def test_route_readiness_uses_cached_probe_without_routing():
    _require_mcp()
    with tempfile.TemporaryDirectory() as temp_dir:
        home = Path(temp_dir)
        _write_climbs(home)
        _run_isolated(
            """
from lusmaker import draft, mcp_server

d = draft.new(
    start={"lat": 50.8, "lon": 3.7, "label": "Start"},
    name="readiness",
    loop=True,
    end=None,
)
d["_probe"] = {
    "km": 12,
    "hm": 100,
    "kwaliteit": {"kassei_m": 600},
    "terrein": {
        "kassei_aanwezig_m": 600,
        "beton_m": 0,
        "offroad_beschikbaar_pct": 0,
        "heat_dekking_pct": None,
        "plaatskernen": [],
    },
}
draft.save(d)

result = mcp_server.route_readiness(d["id"])
assert result["profiel"] == "standaard"
assert result["vragen"][0]["id"] == "kasseien"
assert result["klaar"] is False
""",
            home,
        )


def test_main_selects_stdio_or_streamable_http_without_starting_server():
    _require_mcp()
    with tempfile.TemporaryDirectory() as temp_dir:
        _run_isolated(
            """
from lusmaker import mcp_server

calls = []
mcp_server.mcp.run = lambda **kwargs: calls.append(("full", kwargs))
mcp_server.lite_mcp.run = lambda **kwargs: calls.append(("lite", kwargs))

mcp_server.main([])
mcp_server.main([
    "--lite",
    "--transport", "streamable-http",
    "--host", "127.0.0.1",
    "--port", "8123",
    "--path", "/routes",
    "--stateless-http",
    "--json-response",
])

assert calls == [
    ("full", {"transport": "stdio"}),
    (
        "lite",
        {
            "transport": "streamable-http",
            "host": "127.0.0.1",
            "port": 8123,
            "streamable_http_path": "/routes",
            "stateless_http": True,
            "json_response": True,
        },
    ),
]
""",
            Path(temp_dir),
        )


def test_http_transport_refuses_unauthenticated_remote_bind_by_default():
    _require_mcp()
    with tempfile.TemporaryDirectory() as temp_dir:
        _run_isolated(
            """
from lusmaker import mcp_server

mcp_server.mcp.run = lambda **_kwargs: (_ for _ in ()).throw(
    AssertionError("server had niet mogen starten")
)
try:
    mcp_server.main([
        "--transport", "streamable-http", "--host", "0.0.0.0"
    ])
except SystemExit as exc:
    assert exc.code == 2
else:
    raise AssertionError("publieke bind zonder opt-in werd aanvaard")
""",
            Path(temp_dir),
        )
