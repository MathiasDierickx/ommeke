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
