"""Bewaakt docs/CONTRACTS.md: elke genoemde parameter moet in de code bestaan."""
import inspect
import re
from pathlib import Path

from lusmaker import aws_api, aws_chat, cli, mcp_server, quick_plan
from lusmaker.chat_contracts import (
    ADJUST_ROUTE_SCHEMA, PLAN_ROUTE_SCHEMA, REROUTE_SCHEMA,
)

DOC = Path(__file__).resolve().parents[1] / "docs" / "CONTRACTS.md"
INTERFACES = ("CLI", "MCP", "Chat", "Web")


def _sections():
    """{operatie: [(parameter, {interface: [namen]})]} uit de markdowntabellen."""
    sections, current, header = {}, None, None
    for line in DOC.read_text(encoding="utf-8").splitlines():
        if line.startswith("## "):
            current, header = line[3:].strip(), None
            continue
        if not line.startswith("|") or current is None:
            continue
        cells = [c.strip() for c in line.strip().strip("|").split("|")]
        if cells[0] == "Parameter":
            header = cells
            continue
        if header is None or set(cells[0]) <= {"-", " "}:
            continue
        row = {}
        for name in INTERFACES:
            cell = cells[header.index(name)]
            row[name] = re.findall(r"`([^`]+)`", cell)
        sections.setdefault(current, []).append((cells[0], row))
    return sections


def _chat_tool_schema(name):
    for tool in aws_chat.TOOL_CONFIG["tools"]:
        if tool["toolSpec"]["name"] == name:
            return tool["toolSpec"]["inputSchema"]["json"]
    raise AssertionError(f"chattool {name} ontbreekt")


def _source(*modules):
    return "\n".join(inspect.getsource(m) for m in modules)


def _targets(operation):
    """Per interface een predicaat dat zegt of een naam in de code bestaat."""
    cli_src = _source(cli)
    web_src = _source(aws_api, quick_plan)

    def in_source(src, name):
        return f'"{name}"' in src or f"'{name}'" in src

    def cli_has(name):
        return in_source(cli_src, name)

    def web_has(name):
        return in_source(web_src, name)

    def signature(fn):
        params = set(inspect.signature(fn).parameters)
        return lambda name: name in params

    def schema(sch):
        return lambda name: name in sch.get("properties", {})

    def either(a, b):
        return lambda name: a(name) or b(name)

    mcp = {
        "plan_route": signature(mcp_server.plan_route),
        "adjust_route": signature(mcp_server.adjust_route),
        "reroute_from": signature(mcp_server.reroute_from),
        "update_profile": signature(mcp_server.update_profile),
    }
    chat = {
        "plan_route": schema(PLAN_ROUTE_SCHEMA),
        "adjust_route": schema(ADJUST_ROUTE_SCHEMA),
        "reroute_from": schema(REROUTE_SCHEMA),
        "update_profile": schema(_chat_tool_schema("update_profile")),
    }
    web = {
        "plan_route": web_has,
        "adjust_route": web_has,
        "apply_answers": web_has,
        "reroute_from": either(web_has, schema(REROUTE_SCHEMA)),
    }

    def cli_name(name):
        return cli_has(name) if name.startswith("--") else cli_has(name)

    return {
        "CLI": cli_name,
        "MCP": mcp.get(operation),
        "Chat": chat.get(operation),
        "Web": web.get(operation),
    }


def test_matrix_parses_all_operations():
    sections = _sections()
    for operation in ("plan_route", "adjust_route", "apply_answers",
                      "reroute_from", "update_profile"):
        assert operation in sections, f"{operation} ontbreekt in CONTRACTS.md"
        assert len(sections[operation]) >= 3


def test_every_documented_parameter_exists_in_code():
    problems = []
    for operation, rows in _sections().items():
        if operation not in {"plan_route", "adjust_route", "apply_answers",
                             "reroute_from", "update_profile"}:
            continue
        targets = _targets(operation)
        for parameter, row in rows:
            for interface in INTERFACES:
                for name in row[interface]:
                    check = targets[interface]
                    if check is None:
                        problems.append(
                            f"{operation}: {interface} documenteert `{name}` maar kent de operatie niet"
                        )
                    elif not check(name):
                        problems.append(
                            f"{operation}/{parameter}: `{name}` bestaat niet meer op {interface}"
                        )
    assert not problems, "\n".join(problems)


def test_documented_mcp_and_chat_parameters_are_complete():
    """Nieuwe parameters in MCP-signatuur of chatschema moeten gedocumenteerd worden."""
    sections = _sections()
    missing = []
    for operation, fn, sch in (
        ("plan_route", mcp_server.plan_route, PLAN_ROUTE_SCHEMA),
        ("adjust_route", mcp_server.adjust_route, ADJUST_ROUTE_SCHEMA),
        ("reroute_from", mcp_server.reroute_from, REROUTE_SCHEMA),
    ):
        documented_mcp = {n for _, row in sections[operation] for n in row["MCP"]}
        documented_chat = {n for _, row in sections[operation] for n in row["Chat"]}
        for name in inspect.signature(fn).parameters:
            if name not in documented_mcp:
                missing.append(f"{operation}: MCP-parameter {name} ongedocumenteerd")
        for name in sch["properties"]:
            if name not in documented_chat:
                missing.append(f"{operation}: chatparameter {name} ongedocumenteerd")
    assert not missing, "\n".join(missing)


def test_documented_error_codes_exist_in_code():
    text = DOC.read_text(encoding="utf-8")
    codes = set(re.findall(r"^\| `([a-z_]+)` \| \d{3} \|", text, flags=re.M))
    assert {"buiten_gebied", "quota_exceeded", "request_conflict",
            "route_conflict"} <= codes
    source = _source(aws_api) + inspect.getsource(
        __import__("lusmaker.coverage", fromlist=["x"])
    )
    for code in codes - {"bad_request"}:
        assert f'"{code}"' in source, f"foutcode {code} ontbreekt in de code"


def test_stop_underway_contract_is_typed_and_available_everywhere():
    from pydantic import TypeAdapter, ValidationError
    from lusmaker import intents
    from lusmaker.mcp_contracts import StopOnderweg
    from lusmaker.chat_contracts import STOP_SCHEMA
    assert 'stop_onderweg' in inspect.signature(intents.plan_route).parameters
    assert 'stop_onderweg' in inspect.signature(mcp_server.plan_route).parameters
    assert PLAN_ROUTE_SCHEMA['properties']['stop_onderweg'] == STOP_SCHEMA
    assert set(STOP_SCHEMA['properties']) == {'soort', 'rond_km'}
    assert any(name == 'stop_onderweg' for name, _ in _sections()['plan_route'])
    adapter = TypeAdapter(StopOnderweg)
    assert adapter.validate_python({'soort':'cafe', 'rond_km':20})['rond_km'] == 20
    for bad in ({'soort':'onbekend','rond_km':20}, {'soort':'cafe','rond_km':-1}, {'soort':'cafe','rond_km':float('inf')}):
        try:
            adapter.validate_python(bad)
        except ValidationError:
            continue
        raise AssertionError('Ongeldige MCP-stop aanvaard')


def test_stop_is_forwarded_by_cli_and_chat():
    from unittest.mock import patch
    from lusmaker import intents
    from tests.test_contract_gaps import _cli_plan
    wanted = {'soort':'cafe', 'rond_km':20}
    seen, _ = _cli_plan('--stop-onderweg', '{"soort":"cafe","rond_km":20}')
    assert seen['stop_onderweg'] == wanted
    calls = []
    with patch.object(intents, 'plan_route', lambda **kw: calls.append(kw) or {'status':'ready'}):
        aws_chat.RouteToolExecutor().execute('plan_route', {'start':'Test', 'target_km':40, 'stop_onderweg':wanted}, request_id='stop-test-123')
    assert calls[0]['stop_onderweg'] == wanted
