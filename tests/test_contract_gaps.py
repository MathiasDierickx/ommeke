"""Contractgaten uit de matrix: adjust-schema, request_id, reroute-codes en CLI-vlaggen."""
import asyncio
import contextlib
import io
import json
from unittest import mock

from pydantic import TypeAdapter, ValidationError
from starlette.requests import Request

from lusmaker import aws_api, aws_chat, aws_state, cli, coverage, draft, intents, mcp_server, requests, tenant
from lusmaker.chat_contracts import ADJUST_ROUTE_SCHEMA
from lusmaker.mcp_contracts import RequestId
from tests.test_aws_state import _FakeS3, _aws_bucket


def _chat_adjust(arguments, request_id="conv:msg-1"):
    seen = []
    with mock.patch.object(intents, "adjust_route", lambda **kw: seen.append(kw) or {"status": "ready"}):
        aws_chat.RouteToolExecutor().execute("adjust_route", arguments, request_id=request_id)
    return seen[0]


def test_chat_adjust_schema_and_executor_know_allow_places_and_profile():
    assert {"sta_plaatsen_toe", "profiel_naam"} <= set(ADJUST_ROUTE_SCHEMA["properties"])
    values = _chat_adjust({"draft_id": "d1", "sta_plaatsen_toe": ["Zottegem"], "profiel_naam": "gravel"})
    assert values["sta_plaatsen_toe"] == ["Zottegem"] and values["profiel_naam"] == "gravel"


def test_chat_adjust_supplies_a_stable_valid_request_id():
    first = _chat_adjust({"draft_id": "d1", "voeg_klimmen_toe": ["molenberg"]})
    again = _chat_adjust({"draft_id": "d1", "voeg_klimmen_toe": ["molenberg"]})
    other = _chat_adjust({"draft_id": "d1", "voeg_klimmen_toe": ["berendries"]})
    assert first["request_id"] == again["request_id"] != other["request_id"]
    requests.request_path("adjust:d1", first["request_id"])      # geldig receiptformaat
    assert "request_id" not in ADJUST_ROUTE_SCHEMA["properties"]  # model kiest het niet


def test_mcp_adjust_forwards_request_id_and_validates_format():
    seen = {}
    with mock.patch.object(intents, "adjust_route", lambda **kw: seen.update(kw) or {"status": "ready"}):
        mcp_server.adjust_route(draft_id="d1", request_id="retry-0001")
    assert seen["request_id"] == "retry-0001"
    adapter = TypeAdapter(RequestId)
    assert adapter.validate_python("abcd-1234_XYZ") == "abcd-1234_XYZ"
    for bad in ("kort", "met:dubbelepunt", "met spatie 123", "x" * 129, ".beginpunt1"):
        try:
            adapter.validate_python(bad)
        except ValidationError:
            continue
        raise AssertionError(f"{bad!r} had afgewezen moeten worden")


def test_mcp_request_id_pattern_matches_the_receipt_rule():
    adapter = TypeAdapter(RequestId)
    for good in ("a" * 8, "A1_-b2c3", "x" * 128):
        requests.request_path("adjust:d1", good)
        adapter.validate_python(good)


def test_engine_adjust_with_request_id_runs_once_and_rejects_other_input():
    calls = []

    def fake_load(draft_id):
        calls.append(draft_id)
        raise draft.DraftError("stop")

    with _aws_bucket(), aws_state.use_client(_FakeS3()), tenant.use("one"):
        # een mislukte uitvoering wordt 'interrupted' en nooit stilzwijgend herhaald
        try:
            intents.adjust_route("d1", load_fn=fake_load, request_id="retry-0001")
        except draft.DraftError:
            pass
        try:
            intents.adjust_route("d1", load_fn=fake_load, request_id="retry-0001")
        except requests.RequestConflict:
            pass
        else:
            raise AssertionError("tweede poging had niet opnieuw mogen draaien")
        assert calls == ["d1"]
        # zonder request_id: gewoon uitvoeren
        try:
            intents.adjust_route("d1", load_fn=fake_load)
        except draft.DraftError:
            pass
        assert calls == ["d1", "d1"]


def _web(handler, path, body, draft_id="d1"):
    request = Request({"type": "http", "method": "POST", "path": path, "headers": [],
                       "path_params": {"draft_id": draft_id}})

    async def read():
        return json.dumps(body).encode()

    request.body = read
    response = asyncio.run(handler(request))
    return response.status_code, json.loads(response.body)


def _web_adjust(body, adjust):
    item = {"id": "d1", "route_request": {}, "computed": {"total_km": 40}}
    with mock.patch.object(aws_api.draft, "load", lambda _id: item), \
            mock.patch.object(aws_api.intents, "adjust_route", adjust), \
            mock.patch.object(aws_api, "_quick", lambda fn: fn), \
            mock.patch.object(aws_api, "_route_detail_payload", lambda d: {"id": d["id"]}), \
            mock.patch.object(aws_api, "_fresh_proposals", lambda d: []):
        return _web(aws_api.route_adjust, "/api/routes/d1/adjust", body)


def test_web_adjust_replays_the_receipt_and_rejects_changed_input():
    calls = []
    body = {"voeg_klimmen_toe": ["molenberg"], "request_id": "adjust-0001"}
    with _aws_bucket(), aws_state.use_client(_FakeS3()), tenant.use("one"):
        for _ in range(2):
            status, payload = _web_adjust(body, lambda *a, **k: calls.append(1) or {})
            assert status == 200 and payload == {"route": {"id": "d1"}}
        assert calls == [1]
        status, payload = _web_adjust({**body, "voeg_klimmen_toe": ["berendries"]}, lambda *a, **k: {})
        assert status == 409 and payload["code"] == "request_conflict"


def test_web_adjust_rejects_an_invalid_request_id_and_stays_optional():
    status, payload = _web_adjust({"request_id": "kort"}, lambda *a, **k: {})
    assert status == 400 and payload["code"] == "bad_request"
    status, _ = _web_adjust({"voeg_klimmen_toe": ["molenberg"]}, lambda *a, **k: {})
    assert status == 200


def _web_reroute(error):
    body = {"lat": 51.0, "lon": 3.7, "rest_km": "kortste", "request_id": "reroute-0001"}

    def boom(*_a, **_k):
        raise error

    with mock.patch("lusmaker.reroute.reroute_from", boom):
        return _web(aws_api.route_reroute, "/api/routes/d1/reroute", body)


def test_web_reroute_distinguishes_revision_conflict_and_coverage():
    status, payload = _web_reroute(draft.DraftError("revisie komt niet overeen"))
    assert status == 409 and payload["code"] == "route_conflict"
    status, payload = _web_reroute(requests.RequestConflict("ander verzoek"))
    assert status == 409 and payload["code"] == "request_conflict"
    status, payload = _web_reroute(coverage.OutOfCoverage("buiten", {"naam": "Vlaanderen"}, {"lat": 1, "lon": 2}))
    assert status == 422 and payload["code"] == "buiten_gebied" and payload["punt"] == {"lat": 1, "lon": 2}


def _cli_plan(*argv):
    seen = {}
    out = io.StringIO()
    with mock.patch.object(intents, "plan_route", lambda **kw: seen.update(kw) or {"status": "ready"}), \
            contextlib.redirect_stdout(out):
        cli.main(["plan-route", "--start", "Wetteren", *argv])
    return seen, json.loads(out.getvalue())


def test_cli_plan_route_maps_preference_flags_and_readiness():
    seen, output = _cli_plan("--heuvels", "zoek", "--ondergrond", "onverhard", "--check-readiness")
    assert (seen["heuvels"], seen["ondergrond"], seen["check_readiness"]) == ("zoek", "onverhard", True)
    assert output == {"status": "ready"}


def test_cli_plan_route_defaults_stay_unknown_and_readiness_off():
    seen, _ = _cli_plan()
    assert seen["heuvels"] is None and seen["ondergrond"] is None and seen["check_readiness"] is False
    for flag, value in (("--heuvels", "steil"), ("--ondergrond", "zand")):
        try:
            with contextlib.redirect_stderr(io.StringIO()):
                _cli_plan(flag, value)
        except SystemExit as exc:
            assert exc.code == 2
        else:
            raise AssertionError(f"{flag} {value} had afgewezen moeten worden")
