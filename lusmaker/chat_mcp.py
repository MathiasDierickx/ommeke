"""Beperkte stdio-MCP voor dezelfde routetools als de webchat."""
from contextlib import redirect_stdout
import json
import os
from pathlib import Path
import sys
from typing import Literal

try:
    from mcp.server.fastmcp import FastMCP
except ImportError:
    from mcp.server import MCPServer as FastMCP

from .aws_chat import RouteToolExecutor, TOOL_CONFIG


def create_server(executor=None, trace_path=None):
    executor = executor or RouteToolExecutor()
    server = FastMCP("lusmaker-chat", instructions="Gebruik de route-tool met deze contracten: " + json.dumps(TOOL_CONFIG, ensure_ascii=False))

    @server.tool()
    def route_tool(name: Literal["reroute_from", "get_profile", "update_profile", "lookup_place", "nearby_places", "plan_route", "adjust_route", "list_routes", "route_details"], arguments: dict) -> dict:
        """Voer een routetool uit volgens het JSON-contract in de serverinstructies."""
        event = {"name": name, "input": arguments}
        try:
            with redirect_stdout(sys.stderr):
                result = executor.execute(name, arguments, request_id=os.environ.get("LUSMAKER_CHAT_REQUEST", "local"))
            event["output"] = result
            return result
        except Exception as exc:
            event["error"] = str(exc)
            from . import coverage
            return coverage.error_payload(exc)
        finally:
            if trace_path:
                with Path(trace_path).open("a", encoding="utf-8") as handle:
                    handle.write(json.dumps(event, ensure_ascii=False) + "\n")

    return server


if __name__ == "__main__":
    create_server(trace_path=os.environ.get("LUSMAKER_CHAT_TRACE")).run(transport="stdio")
