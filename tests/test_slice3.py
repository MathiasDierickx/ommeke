"""Slice 3 van #29: chat-intenthints en verse voorstellen na een adjust."""

import asyncio
import json
from unittest import mock

from starlette.requests import Request

from lusmaker import aws_api, aws_chat, intents


def test_route_detail_payload_returns_saved_questions_only_for_pending_routes():
    questions = [{"id": "heuvels", "vraag": "Hoeveel heuvels?", "reden": "Onbekend", "opties": {"zoek": {}, "vlak": {}}}]
    item = {"id": "abc123", "revision": 1, "name": "Concept", "computed": None,
            "route_request": {"target_km": 60}, "open_vragen": questions}
    payload = aws_api._route_detail_payload(item)
    assert payload["vragen"] == questions and payload["ready"] is False
    item["computed"] = {"total_km": 60, "ascend_m": 500}
    assert aws_api._route_detail_payload(item)["vragen"] == []


def _plan_calls(user_text, arguments, *, via_agent=False):
    calls = []

    def fake_plan_route(**kwargs):
        calls.append(kwargs)
        return {"status": "ready", "draft": "d1"}

    with mock.patch.object(intents, "plan_route", fake_plan_route):
        executor = aws_chat.RouteToolExecutor()
        if via_agent:
            class Model:
                def __init__(self):
                    self.turn = 0

                def converse(self, **_kwargs):
                    self.turn += 1
                    if self.turn == 1:
                        block = {"toolUse": {"toolUseId": "t1", "name": "plan_route", "input": arguments}}
                    else:
                        block = {"text": "Klaar."}
                    return {"output": {"message": {"content": [block]}}}

            with mock.patch("lusmaker.quotas.consume", lambda *a, **k: None):
                aws_chat.BedrockRouteAgent(client=Model(), tool_executor=executor).reply(
                    [{"role": "user", "content": "eerder bericht"}, {"role": "assistant", "content": "ok"},
                     {"role": "user", "content": user_text}],
                    request_id="r",
                )
        else:
            executor.execute("plan_route", arguments, request_id="r", user_text=user_text)
    assert len(calls) == 1
    return calls[0]


def test_chat_fills_only_null_preferences_from_the_user_message():
    values = _plan_calls("Een vlakke rit met de racefiets, liever geen kasseien", {"start": "Gent", "target_km": 40})
    assert values["activiteit"] == "koersfiets"
    assert values["heuvels"] == "vlak"
    assert values["kasseien"] is False          # False = vermijden
    assert values["ondergrond"] is None         # niet genoemd: onbekend blijft onbekend


def test_chat_hints_never_override_what_the_model_already_chose():
    values = _plan_calls(
        "Vlakke mtb-rit zonder kasseien",
        {"start": "Gent", "activiteit": "gravel", "heuvels": "ok", "kasseien": None},
    )
    assert values["activiteit"] == "gravel"
    assert values["heuvels"] == "ok"
    assert values["kasseien"] is False          # null = onbekend: wel aangevuld


def test_chat_without_matching_phrases_keeps_the_neutral_defaults():
    values = _plan_calls("Een mooie lus vanuit Gent", {"start": "Gent"})
    assert values["activiteit"] == "toerfiets"
    assert values["heuvels"] is None and values["kasseien"] is None and values["ondergrond"] is None


def test_agent_passes_the_latest_user_message_to_the_executor():
    values = _plan_calls("Wandeling met de kinderwagen", {"start": "Gent"}, via_agent=True)
    assert values["activiteit"] == "wandelen"
    assert values["ondergrond"] == "verhard" and values["heuvels"] == "vlak"
    assert aws_chat._latest_user_text([{"role": "user", "content": "a"}, {"role": "assistant", "content": "b"}]) == "a"
    assert aws_chat._USER_TEXT.get() is None    # contextvar wordt na de beurt hersteld


# -- verse voorstellen na adjust ------------------------------------------

def _adjust(item, proposals_fn):
    request = Request({
        "type": "http", "method": "POST", "path": "/api/routes/d1/adjust", "headers": [],
        "path_params": {"draft_id": "d1"},
    })

    async def body():
        return json.dumps({"voeg_klimmen_toe": ["molenberg"]}).encode()

    request.body = body
    with mock.patch.object(aws_api.draft, "load", lambda _id: item), \
            mock.patch.object(aws_api.intents, "adjust_route", lambda *a, **k: {}), \
            mock.patch.object(aws_api, "_quick", lambda fn: fn), \
            mock.patch.object(aws_api, "_route_detail_payload", lambda d: {"id": d["id"]}), \
            mock.patch.object(aws_api.climbs, "all_climbs", lambda: {}), \
            mock.patch.object(aws_api.proposals, "build", proposals_fn):
        response = asyncio.run(aws_api.route_adjust(request))
    return response.status_code, json.loads(response.body)


def test_adjust_returns_fresh_router_free_proposals_for_the_new_route():
    item = {"id": "d1", "route_request": {"activiteit": "toerfiets"}, "computed": {"total_km": 42.6}}
    seen = []
    proposal = {"titel": "Voeg Kapelmuur toe", "uitleg": "x", "adjust_route": {"voeg_klimmen_toe": ["kapelmuur"]}}

    def build(d, climb_db, request=None):
        seen.append((d, request))
        return [proposal]

    status, payload = _adjust(item, build)
    assert status == 200
    assert payload == {"route": {"id": "d1"}, "voorstellen": [proposal]}
    assert seen == [(item, {"activiteit": "toerfiets"})]    # de herlaadde route, niet de oude


def test_adjust_omits_voorstellen_when_empty_or_failing():
    item = {"id": "d1", "route_request": {}}
    status, payload = _adjust(item, lambda *a, **k: [])
    assert status == 200 and payload == {"route": {"id": "d1"}}

    def boom(*_a, **_k):
        raise RuntimeError("gazetteer ontbreekt")

    status, payload = _adjust(item, boom)
    assert status == 200 and payload == {"route": {"id": "d1"}}
