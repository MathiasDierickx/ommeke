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
    "list_regions",
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
    "suggest_climbs",
    "optimize_draft",
    "export_gpx",
    "preview_draft",
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
""",
            Path(temp_dir),
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
assert shown["avoid_cobbles"] is True

try:
    mcp_server.add_climb(created["id"], "onbekend")
except draft.DraftError as exc:
    assert "onbekende klim 'onbekend'" in str(exc)
else:
    raise AssertionError("onbekende klim werd aanvaard")
""",
            home,
        )
