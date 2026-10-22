"""Tests for model question composition and its deterministic fallback."""

import json
from unittest.mock import patch

from lusmaker import criteria, profiles, question_composer, readiness, intents
from lusmaker.conversation_context import USER_TEXT


def _candidates():
    return [
        {"id": "plek_afstand", "prioriteit": 0, "vraag": "oud", "reden": "meting", "opties": {"ruimer": {"antwoord": {"plek_afstand": "ruimer"}}}},
        {"id": "kasseien", "prioriteit": 1, "vraag": "oud", "reden": "kassei", "opties": {"graag": {"patch": {"x": 1}}}},
        {"id": "beton", "prioriteit": 2, "vraag": "oud", "reden": "beton", "opties": {"ok": {"patch": {"y": 2}}}},
        {"id": "steenwegen", "prioriteit": 3, "vraag": "oud", "reden": "steenweg", "opties": {}},
    ]


class _FakeClient:
    def __init__(self, body):
        self.body = body
        self.calls = []

    def converse(self, **kwargs):
        self.calls.append(kwargs)
        return {"output": {"message": {"content": [{"text": self.body}]}}, "usage": {"inputTokens": 10, "outputTokens": 5}}


def _patch_bedrock(body):
    client = _FakeClient(body)
    return client, patch("lusmaker.aws_chat._bedrock_client", return_value=client)


def test_bedrock_selects_and_rephrases_while_preserving_options_and_priority_place():
    client, mocked = _patch_bedrock(json.dumps({"vragen": [
        {"id": "beton", "vraag": "Beton oké voor jou?"},
        {"id": "plek_afstand", "vraag": "Deze plek vraagt meer kilometers; wil je dat?"},
    ]}))
    with mocked:
        result = question_composer.compose(_candidates(), {"wenstekst": ""}, provider=question_composer._bedrock)
    assert [q["id"] for q in result] == ["plek_afstand", "beton"]
    assert result[0]["opties"] == _candidates()[0]["opties"]
    assert result[1]["opties"] == _candidates()[2]["opties"]
    assert result[1]["reden"] == "beton"
    assert client.calls[0]["inferenceConfig"]["maxTokens"] == 400


def test_invalid_model_responses_fall_back_to_rules():
    for body in (
        '{"vragen":[{"id":"onbekend","vraag":"Hoi"}]}',
        '{"vragen":[{"id":"kasseien","vraag":"x"},{"id":"kasseien","vraag":"y"}]}',
        '{"vragen":[{"id":"kasseien","vraag":""}]}',
        '{"vragen":[{"id":"kasseien","vraag":"' + "x" * 201 + '"}]}',
        "geen json",
    ):
        client, mocked = _patch_bedrock(body)
        with mocked:
            result = question_composer.compose(_candidates(), {}, provider=question_composer._bedrock)
        assert result == question_composer.deterministic(_candidates())


def test_provider_timeout_falls_back():
    def timeout(_candidates, _context):
        raise TimeoutError()
    assert question_composer.compose(_candidates(), {}, provider=timeout) == question_composer.deterministic(_candidates())


def test_readiness_passes_chat_wish_context_and_child_poi_questions():
    profile = profiles.default_document()
    profile["activiteit"] = "wandelen"
    d = {"_probe": {"km": 10, "hm": 0, "kwaliteit": {}, "terrein": {"pois_langs_route": {"speeltuin": 2, "toilet": 1}}}}
    seen = {}
    def provider(candidates, context):
        seen["candidates"] = candidates
        seen["context"] = context
        return question_composer.deterministic(candidates, context)
    token = USER_TEXT.set("wandelen met de kinderen")
    try:
        result = readiness.assess(d, profile, {}, composer=provider)
    finally:
        USER_TEXT.reset(token)
    assert {q["id"] for q in seen["candidates"]} >= {"speeltuin", "toilet"}
    assert seen["context"]["wenstekst"] == "wandelen met de kinderen"
    assert "2 speeltuinen" in next(q["reden"] for q in seen["candidates"] if q["id"] == "speeltuin")
    assert {"graag", "ok"} == set(next(q["opties"] for q in seen["candidates"] if q["id"] == "toilet"))
    assert "speeltuin" in result["onbekend"]


def test_answers_for_child_pois_map_to_criteria():
    assert "graag" in intents.ANSWER_VALUES["speeltuin"]
    assert "graag" in intents.ANSWER_VALUES["toilet"]
    mapped = criteria.from_answers({"speeltuin": "graag", "toilet": "graag"})
    assert {c["metriek"] for c in mapped} == {"speeltuin", "toilet"}

