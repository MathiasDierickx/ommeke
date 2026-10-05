import inspect
from typing import get_args
from lusmaker import mcp_server, mcp_contracts, intents
from lusmaker.chat_contracts import PLAN_ROUTE_SCHEMA, ADJUST_ROUTE_SCHEMA


def test_location_and_goal_contracts_are_available_in_chat_mcp_and_engine():
    for fn, schema in [(mcp_server.plan_route, PLAN_ROUTE_SCHEMA), (mcp_server.adjust_route, ADJUST_ROUTE_SCHEMA)]:
        params = inspect.signature(fn).parameters
        assert {'rond_plaats', 'langs_water'} <= set(params)
        assert {'rond_plaats', 'langs_water'} <= set(schema['properties'])
        assert set(schema['properties']['doel']['enum']) == set(get_args(mcp_contracts.Goal))
    for fn in (intents.plan_route, intents.adjust_route):
        assert {'rond_plaats', 'langs_water'} <= set(inspect.signature(fn).parameters)


def _annotation_kind(annotation):
    import types
    import typing
    kinds = set()
    union = typing.get_origin(annotation) in (typing.Union, types.UnionType)
    for arg in (typing.get_args(annotation) if union else (annotation,)):
        if arg is type(None):
            continue
        if typing.get_origin(arg) is typing.Annotated:
            arg = typing.get_args(arg)[0]
        kinds.add({int: "number", float: "number", str: "string", dict: "object", bool: "boolean"}[arg])
    return frozenset(kinds)


def _json_kind(tp):
    return frozenset("number" if t == "integer" else t for t in (tp if isinstance(tp, list) else [tp]))


def test_reroute_from_parity_between_mcp_chat_and_engine():
    import asyncio
    from lusmaker import aws_chat, reroute
    from lusmaker.chat_contracts import REROUTE_SCHEMA

    tools = {t.name: t for t in asyncio.run(mcp_server.mcp.list_tools())}
    mcp_schema = tools["reroute_from"].input_schema
    chat_spec = next(t["toolSpec"] for t in aws_chat.TOOL_CONFIG["tools"] if t["toolSpec"]["name"] == "reroute_from")
    assert chat_spec["inputSchema"]["json"] is REROUTE_SCHEMA

    injectable = {"load_fn", "save_fn", "route_fn", "climbs_fn", "export_fn"}
    engine = {n: p for n, p in inspect.signature(reroute.reroute_from).parameters.items() if n not in injectable}
    engine_required = {n for n, p in engine.items() if p.default is inspect.Parameter.empty}
    mcp_params = inspect.signature(mcp_server.reroute_from).parameters

    chat_props, mcp_props = REROUTE_SCHEMA["properties"], mcp_schema["properties"]
    # Bewust verschil: request_id wordt in chat en HTTP door de uitvoerder meegegeven, niet door het model gekozen.
    assert set(mcp_props) - {"request_id"} == set(chat_props)
    assert set(engine) == set(mcp_props) == set(mcp_params)
    assert set(REROUTE_SCHEMA["required"]) == set(mcp_schema.get("required", [])) == engine_required == {"draft_id", "lat", "lon"}
    assert REROUTE_SCHEMA["additionalProperties"] is False
    for name, prop in chat_props.items():
        assert _json_kind(prop["type"]) == _annotation_kind(mcp_params[name].annotation), name
    assert set(chat_props["closure"]["required"]) == {"lat", "lon"}
    for name in ("rest_km", "expected_revision", "closure", "request_id"):
        assert mcp_params[name].default == engine[name].default, name


def test_chat_executor_forwards_request_id_to_reroute():
    from lusmaker import aws_chat, reroute
    seen = {}
    original = reroute.reroute_from
    reroute.reroute_from = lambda *a, **kw: seen.update(kw) or {"status": "ready"}
    try:
        aws_chat.RouteToolExecutor().execute(
            "reroute_from", {"draft_id": "abc", "lat": 51.0, "lon": 3.7, "closure": {"lat": 51.0, "lon": 3.71}}, request_id="req-12345678")
    finally:
        reroute.reroute_from = original
    assert seen["request_id"] == "req-12345678" and seen["closure"] == {"lat": 51.0, "lon": 3.71}
