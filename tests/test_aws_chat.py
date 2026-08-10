"""Offline tests voor DynamoDB-chatopslag en de Bedrock tool-loop."""

from __future__ import annotations

from copy import deepcopy

from lusmaker import tenant
from lusmaker.aws_chat import (
    ADJUST_ROUTE_SCHEMA,
    PLAN_ROUTE_SCHEMA,
    SYSTEM_PROMPT,
    BedrockRouteAgent,
    ConversationStore,
)


class FakeDynamo:
    def __init__(self):
        self.items = {}

    @staticmethod
    def _key(item):
        return item["pk"]["S"], item["sk"]["S"]

    def put_item(self, **kwargs):
        key = self._key(kwargs["Item"])
        if kwargs.get("ConditionExpression") and key in self.items:
            raise RuntimeError("conditional write failed")
        self.items[key] = deepcopy(kwargs["Item"])
        return {}

    def get_item(self, **kwargs):
        item = self.items.get(self._key(kwargs["Key"]))
        return {"Item": deepcopy(item)} if item else {}

    def query(self, **kwargs):
        values = kwargs["ExpressionAttributeValues"]
        pk = values[":pk"]["S"]
        prefix = values.get(":prefix", {}).get("S", "")
        items = [
            deepcopy(item)
            for (item_pk, item_sk), item in sorted(self.items.items())
            if item_pk == pk and item_sk.startswith(prefix)
        ]
        if kwargs.get("ScanIndexForward") is False:
            items.reverse()
        if kwargs.get("Limit"):
            items = items[: kwargs["Limit"]]
        if kwargs.get("ProjectionExpression"):
            items = [{"pk": item["pk"], "sk": item["sk"]} for item in items]
        return {"Items": items}

    def update_item(self, **kwargs):
        key = self._key(kwargs["Key"])
        item = self.items[key]
        values = kwargs["ExpressionAttributeValues"]
        item["updated_at"] = values[":updated"]
        item["preview"] = values[":preview"]
        if ":title" in values:
            item["title"] = values[":title"]
        return {}

    def batch_write_item(self, **kwargs):
        for requests in kwargs["RequestItems"].values():
            for request in requests:
                self.items.pop(self._key(request["DeleteRequest"]["Key"]), None)
        return {"UnprocessedItems": {}}


class FakeBedrock:
    def __init__(self):
        self.calls = []

    def converse(self, **kwargs):
        self.calls.append(deepcopy(kwargs))
        if len(self.calls) == 1:
            return {
                "output": {
                    "message": {
                        "role": "assistant",
                        "content": [
                            {
                                "toolUse": {
                                    "toolUseId": "tool-1",
                                    "name": "plan_route",
                                    "input": {"start": "Wetteren", "target_km": 50},
                                }
                            }
                        ],
                    }
                },
                "stopReason": "tool_use",
                "usage": {"inputTokens": 10, "outputTokens": 4, "totalTokens": 14},
            }
        return {
            "output": {
                "message": {
                    "role": "assistant",
                    "content": [{"text": "Je route van 49,6 km staat klaar."}],
                }
            },
            "stopReason": "end_turn",
            "usage": {"inputTokens": 15, "outputTokens": 8, "totalTokens": 23},
        }


class FakeTools:
    def __init__(self):
        self.calls = []

    def execute(self, name, arguments, *, request_id):
        self.calls.append((name, arguments, request_id, tenant.current()))
        return {"status": "ready", "draft": "abc123", "route": {"total_km": 49.6}}


def test_conversation_store_is_tenant_scoped_and_orders_messages():
    client = FakeDynamo()
    with tenant.use("user-one"):
        store = ConversationStore(client=client, table_name="chat")
        conversation = store.create()
        first = store.add_message(conversation["id"], "user", "Maak 50 km")
        second = store.add_message(conversation["id"], "assistant", "Komt in orde")
        messages = store.messages(conversation["id"])
        assert [item["id"] for item in messages] == [first["id"], second["id"]]
        assert store.list()[0]["title"] == "Maak 50 km"

    with tenant.use("user-two"):
        other_store = ConversationStore(client=client, table_name="chat")
        assert other_store.list() == []
        try:
            other_store.get(conversation["id"])
        except Exception as exc:
            assert "niet gevonden" in str(exc)
        else:
            raise AssertionError("gesprek van andere tenant werd zichtbaar")


def test_conversation_delete_removes_metadata_and_messages():
    client = FakeDynamo()
    with tenant.use("user-one"):
        store = ConversationStore(client=client, table_name="chat")
        conversation = store.create("Weekendrit")
        store.add_message(conversation["id"], "user", "Hallo")
        assert store.delete(conversation["id"]) == 2
        assert store.list() == []


def test_bedrock_agent_executes_whitelisted_tool_and_accumulates_usage():
    bedrock = FakeBedrock()
    tools = FakeTools()
    agent = BedrockRouteAgent(
        client=bedrock,
        tool_executor=tools,
        model_id="eu.anthropic.claude-sonnet-4-6",
    )
    with tenant.use("user-one"):
        result = agent.reply(
            [{"role": "user", "content": "50 km vanuit Wetteren"}],
            request_id="conversation:message",
        )

    assert result["content"] == "Je route van 49,6 km staat klaar."
    assert result["route_ids"] == ["abc123"]
    assert result["usage"] == {
        "inputTokens": 25,
        "outputTokens": 12,
        "totalTokens": 37,
    }
    assert tools.calls[0][0:3] == (
        "plan_route",
        {"start": "Wetteren", "target_km": 50},
        "conversation:message",
    )
    assert tools.calls[0][3] == "user-one"
    tool_result = bedrock.calls[1]["messages"][-1]["content"][0]["toolResult"]
    assert tool_result["toolUseId"] == "tool-1"
    assert tool_result["content"][0]["json"]["draft"] == "abc123"


def test_route_tool_contract_exposes_landmark_anchor_instruction():
    assert PLAN_ROUTE_SCHEMA["properties"]["rond_plaats"]["minLength"] == 1
    assert ADJUST_ROUTE_SCHEMA["properties"]["rond_plaats"]["minLength"] == 1
    assert "zet die plek in rond_plaats" in SYSTEM_PROMPT
