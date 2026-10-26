"""Offline tests voor DynamoDB-chatopslag en de Bedrock tool-loop."""

from __future__ import annotations

from copy import deepcopy

from lusmaker import tenant
from lusmaker.aws_chat import (
    ADJUST_ROUTE_SCHEMA,
    ANSWER_QUESTIONS_SCHEMA,
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


def test_bedrock_agent_executes_answer_questions_and_exposes_open_question_context():
    class AnswerModel:
        def __init__(self):
            self.calls = []
        def converse(self, **kwargs):
            self.calls.append(deepcopy(kwargs))
            if len(self.calls) == 1:
                return {"output": {"message": {"content": [{"toolUse": {
                    "toolUseId": "answer-1", "name": "answer_questions",
                    "input": {"draft_id": "draft-1", "antwoorden": {"oversteken": "vermijd"}},
                }}]}}, "stopReason": "tool_use", "usage": {}}
            return {"output": {"message": {"content": [{"text": "Ik pas dat toe."}]}}, "stopReason": "end_turn", "usage": {}}
    class AnswerTools:
        def __init__(self): self.calls = []
        def execute(self, name, arguments, *, request_id):
            self.calls.append((name, arguments, request_id))
            return {"status": "needs_input", "draft": "draft-1", "vragen": [
                {"id": "kasseien", "opties": {"graag": {"label": "Graag"}, "ok": {"label": "Oké"}, "vermijd": {"label": "Vermijd"}}}
            ]}
    model, tools = AnswerModel(), AnswerTools()
    result = BedrockRouteAgent(client=model, tool_executor=tools).reply(
        [{"role": "user", "content": "vermijden ja"}], request_id="answers-test")
    assert tools.calls == [("answer_questions", {"draft_id": "draft-1", "antwoorden": {"oversteken": "vermijd"}}, "answers-test")]
    assert result["route_ids"] == ["draft-1"]
    context = model.calls[1]["messages"][-1]["content"][0]["toolResult"]["content"][0]["json"]
    assert context["vragen"][0]["id"] == "kasseien"
    assert set(context["vragen"][0]["opties"]) == {"graag", "ok", "vermijd"}
    assert "draft_id" in ANSWER_QUESTIONS_SCHEMA["properties"]


def test_active_route_context_is_prepended_to_the_latest_user_message():
    class Model:
        def __init__(self): self.calls = []
        def converse(self, **kwargs):
            self.calls.append(deepcopy(kwargs))
            return {"output": {"message": {"content": [{"text": "Oké."}]}}, "stopReason": "end_turn", "usage": {}}
    class NoTools:
        def execute(self, *a, **k): raise AssertionError("geen tool verwacht")
    looked_up = []
    def context(draft_id):
        looked_up.append(draft_id)
        return {"draft_id": draft_id, "revision": 3, "status": "wacht op antwoorden",
                "open_vragen": [{"id": "startplaats", "vraag": "Welke Markt Wetteren bedoel je?",
                                 "opties": {"0": "Markt, Wetteren (Wetteren)", "1": "Markt, Lede (Lede)"}}]}
    model = Model()
    history = [
        {"role": "user", "content": "Wandeling van 4 km vanaf Markt Wetteren"},
        {"role": "assistant", "content": "Nog één korte vraag.", "route_ids": ["oud-1", "draft-9"]},
        {"role": "user", "content": "de Markt in het centrum van Wetteren zelf"},
    ]
    BedrockRouteAgent(client=model, tool_executor=NoTools(), context_fn=context).reply(history, request_id="ctx-test")
    assert looked_up == ["draft-9"]
    sent = model.calls[0]["messages"]
    assert sent[-1]["role"] == "user"
    text = sent[-1]["content"][0]["text"]
    assert text.startswith("[Actieve route ") and '"draft_id": "draft-9"' in text and '"startplaats"' in text
    assert text.endswith("de Markt in het centrum van Wetteren zelf")
    # Zonder eerdere route komt er geen blok.
    model2 = Model()
    BedrockRouteAgent(client=model2, tool_executor=NoTools(), context_fn=context).reply(
        [{"role": "user", "content": "Lus van 30 km"}], request_id="ctx-test-2")
    assert model2.calls[0]["messages"][-1]["content"][0]["text"] == "Lus van 30 km"
    assert "[Actieve route" in SYSTEM_PROMPT and 'answer_questions met antwoorden {"startplaats"' in SYSTEM_PROMPT


def test_route_context_reads_open_questions_from_the_draft():
    from lusmaker import aws_chat, draft
    original = draft.load
    draft.load = lambda _id: {"id": "d1", "revision": 4, "name": "Wandeling", "computed": None,
                              "open_vragen": [{"id": "startplaats", "vraag": "Welke?", "opties": {"0": {"label": "A"}, "1": {"label": "B"}}}]}
    try:
        context = aws_chat._route_context("d1")
    finally:
        draft.load = original
    assert context == {"draft_id": "d1", "revision": 4, "naam": "Wandeling", "status": "wacht op antwoorden",
                       "open_vragen": [{"id": "startplaats", "vraag": "Welke?", "opties": {"0": "A", "1": "B"}}]}


def test_answer_questions_executor_calls_motor():
    from lusmaker.aws_chat import RouteToolExecutor
    from lusmaker import intents
    calls = []
    original = intents.apply_answers
    intents.apply_answers = lambda draft_id, antwoorden, *, klaar=False: calls.append(
        (draft_id, antwoorden, klaar)
    ) or {"status": "ready", "draft": draft_id}
    executor = RouteToolExecutor()
    result = executor.execute("answer_questions", {
        "draft_id": "draft-1", "antwoorden": {"oversteken": "vermijd"}, "klaar": True,
    }, request_id="answers-test")
    assert calls == [("draft-1", {"oversteken": "vermijd"}, True)]
    assert result == {"status": "ready", "draft": "draft-1"}
    intents.apply_answers = original


def test_route_tool_contract_exposes_landmark_anchor_instruction():
    assert PLAN_ROUTE_SCHEMA["properties"]["rond_plaats"]["minLength"] == 1
    assert ADJUST_ROUTE_SCHEMA["properties"]["rond_plaats"]["minLength"] == 1
    assert PLAN_ROUTE_SCHEMA["properties"]["langs_water"]["maxLength"] == 120
    assert ADJUST_ROUTE_SCHEMA["properties"]["langs_water"]["maxLength"] == 120
    assert "zet die plek in rond_plaats" in SYSTEM_PROMPT
    assert "zet die naam in `langs_water`" in SYSTEM_PROMPT


def test_iteration_limit_does_not_present_needs_input_as_ready():
    class RepeatingModel:
        def converse(self, **kwargs):
            return {'output': {'message': {'content': [{'toolUse': {'toolUseId': 'pending', 'name': 'plan_route', 'input': {}}}]}}}
    class PendingTools:
        def execute(self, *args, **kwargs):
            return {'status': 'needs_input', 'draft': 'pending-route'}
    result = BedrockRouteAgent(client=RepeatingModel(), tool_executor=PendingTools()).reply(
        [{'role': 'user', 'content': 'Een kindvriendelijke strandwandeling van 3 km'}], request_id='test')
    assert result['route_ids'] == ['pending-route']
    assert result['ready_route_ids'] == []
    assert 'nog niet klaar' in result['content']
    assert 'Je route staat klaar' not in result['content']


def test_needs_input_prompt_refers_to_buttons_without_raw_answer_instructions():
    assert "herhaal de vragen niet" in SYSTEM_PROMPT
    assert "kaarten met knoppen" in SYSTEM_PROMPT
    assert "geen indexnummers en geen coördinaten" in SYSTEM_PROMPT
    assert "vraag nooit om sleutel = waarde te typen" in SYSTEM_PROMPT
    assert "Vrije tekstantwoorden" in SYSTEM_PROMPT
    assert "answer_questions" in SYSTEM_PROMPT
    assert "geen voorkeurenvragen als tekst" in SYSTEM_PROMPT
    assert "klaar: true" in SYSTEM_PROMPT


def test_web_chat_removes_internal_files_from_the_model_context():
    from lusmaker.aws_chat import _clean_answer

    output = {
        "status": "ready", "draft": "abc123", "km": 49.6,
        "bestanden": {"gpx": "/tmp/lusmaker/exports/abc123/route.gpx", "preview": "/tmp/lusmaker/exports/abc123/preview.html"},
        "artifacts": [{"uri": "lusmaker://drafts/abc123/route.gpx"}],
        "route": {"file": "/home/service/route.gpx", "km": 49.6},
        "metadata": [{"preview": "/var/exports/preview.html", "melding": "Bestand /tmp/lusmaker/route.gpx is klaar"}],
        "voorstellen": [{"titel": "Voeg Chemin du Bois toe", "uitleg": "2,1 km extra", "adjust_route": {"voeg_klimmen_toe": ["auto-chemin-du-bois"], "target_km": 55}}],
    }
    original = deepcopy(output)

    class FileTools:
        def execute(self, *args, **kwargs):
            return output

    model = FakeBedrock()
    result = BedrockRouteAgent(client=model, tool_executor=FileTools()).reply(
        [{"role": "user", "content": "50 km vanuit Wetteren"},
         {"role": "assistant", "content": "Oude preview: /tmp/lusmaker/preview.html"},
         {"role": "user", "content": "Pas mijn route aan"}], request_id="files-test")
    context = model.calls[1]["messages"][-1]["content"][0]["toolResult"]["content"][0]["json"]
    assert "bestanden" not in context and "artifacts" not in context
    assert context["route"] == {"km": 49.6}
    assert context["metadata"] == [{"melding": "Bestand [intern bestand] is klaar"}]
    assert context["voorstellen"] == output["voorstellen"]
    assert output == original  # de originele tool-output blijft intact voor andere interfaces
    assert "/tmp/" not in str(model.calls)
    assert "/home/service/" not in str(model.calls)
    assert result["route_ids"] == ["abc123"]
    assert "/tmp/" not in _clean_answer("GPX: [/tmp/lusmaker/exports/abc123/route.gpx]")
    assert "Noem nooit bestandspaden of toolnamen/-syntaxis" in SYSTEM_PROMPT
    assert '"Download GPX/FIT" op de routekaart' in SYSTEM_PROMPT
    assert "zonder adjust_route(...)-syntaxis" in SYSTEM_PROMPT
