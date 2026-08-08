"""Pure tests voor de zelfstandige productie-E2E-runner."""

import json

from tests import e2e_prod


def _json(status, payload, headers=None):
    return e2e_prod.HTTPResponse(
        status,
        json.dumps(payload).encode(),
        headers or {},
    )


def _success_responses(*, anonymous_status=401, gpx=b"<?xml version='1.0'?><gpx/>"):
    return [
        _json(200, {"status": "ok"}),
        _json(anonymous_status, {"error": "token vereist"}),
        _json(
            200,
            {
                "resource": "https://api.example/mcp",
                "authorization_servers": ["https://auth.example/pool"],
                "bearer_methods_supported": ["header"],
            },
        ),
        _json(200, {"conversations": []}),
        _json(201, {"conversation": {"id": "gesprek-1"}}),
        _json(200, {"message": {"content": "klaar"}, "route_ids": ["route-1"]}),
        _json(
            200,
            {
                "route": {
                    "id": "route-1",
                    "download_url": "/api/routes/route-1/gpx",
                    "preview_url": "/api/routes/route-1/preview",
                }
            },
        ),
        e2e_prod.HTTPResponse(200, gpx),
        e2e_prod.HTTPResponse(200, b"<html>preview</html>"),
        _json(
            200,
            {
                "jsonrpc": "2.0",
                "id": 1,
                "result": {"protocolVersion": "2025-06-18"},
            },
            {"Mcp-Session-Id": "sessie-1"},
        ),
        e2e_prod.HTTPResponse(202),
        _json(
            200,
            {
                "jsonrpc": "2.0",
                "id": 2,
                "result": {
                    "tools": [
                        {"name": "plan_route"},
                        {"name": "list_drafts"},
                    ]
                },
            },
        ),
    ]


class StubHTTP:
    def __init__(self, responses, events=None):
        self.responses = list(responses)
        self.calls = []
        self.events = events

    def __call__(self, method, path, **kwargs):
        call = (method, path, kwargs)
        self.calls.append(call)
        if self.events is not None:
            self.events.append((method, path))
        if not self.responses:
            raise AssertionError(f"onverwachte request: {method} {path}")
        return self.responses.pop(0)


def _config():
    return e2e_prod.E2EConfig(
        api="https://api.example",
        pool_id="eu-west-1_pool",
        client_id="client",
        username="fietser@example.com",
        password="geheim",
    )


def test_orchestration_runs_in_order_and_reuses_mcp_session_header():
    events = []
    http = StubHTTP(_success_responses(), events)

    def authenticate(_config):
        events.append(("AUTH", "Cognito"))
        return "access-token"

    output = []
    report = e2e_prod.E2ERunner(
        _config(), request=http, authenticate=authenticate, printer=output.append
    ).run()

    assert report.exit_code == 0
    assert [step.status for step in report.steps] == ["OK"] * 9
    assert events == [
        ("GET", "/health"),
        ("POST", "/mcp"),
        ("GET", "/.well-known/oauth-protected-resource"),
        ("AUTH", "Cognito"),
        ("GET", "/api/conversations"),
        ("POST", "/api/conversations"),
        ("POST", "/api/conversations/gesprek-1/messages"),
        ("GET", "/api/routes/route-1"),
        ("GET", "/api/routes/route-1/gpx"),
        ("GET", "/api/routes/route-1/preview"),
        ("POST", "/mcp"),
        ("POST", "/mcp"),
        ("POST", "/mcp"),
    ]
    assert http.calls[5][2]["json_body"] == {"content": e2e_prod.PROMPT}
    assert http.calls[-2][2]["headers"]["Mcp-Session-Id"] == "sessie-1"
    assert http.calls[-1][2]["headers"]["Mcp-Session-Id"] == "sessie-1"
    assert output[-1] == "Resultaat: OK"


def test_model_unavailable_marks_message_failed_and_route_step_skipped():
    responses = _success_responses()
    responses[5:9] = [
        _json(
            502,
            {
                "error": "Claude kon dit bericht niet verwerken.",
                "code": "model_unavailable",
            },
        )
    ]
    http = StubHTTP(responses)
    report = e2e_prod.E2ERunner(
        _config(),
        request=http,
        authenticate=lambda _config: "access-token",
        printer=lambda _line: None,
    ).run()

    assert report.exit_code == 1
    assert report.steps[6].status == "FOUT"
    assert "Bedrock-modeltoegang" in report.steps[6].detail
    assert report.steps[7].status == "SKIP"
    assert report.steps[8].status == "OK"
    assert not any(
        path.startswith("/api/routes/") for _method, path, _kwargs in http.calls
    )


def test_anonymous_mcp_must_return_401_and_exit_code_reflects_failure():
    http = StubHTTP(_success_responses(anonymous_status=200))
    report = e2e_prod.E2ERunner(
        _config(),
        request=http,
        authenticate=lambda _config: "access-token",
        printer=lambda _line: None,
    ).run()

    assert report.steps[1].status == "FOUT"
    assert "verwacht HTTP 401" in report.steps[1].detail
    assert report.exit_code == 1


def test_gpx_validation_requires_xml_declaration():
    e2e_prod.validate_gpx(b"<?xml version='1.0'?><gpx/>")
    for payload in (b"", b"<gpx/>"):
        try:
            e2e_prod.validate_gpx(payload)
        except e2e_prod.CheckError:
            pass
        else:
            raise AssertionError("ongeldig GPX-bestand werd aanvaard")


def test_invalid_gpx_fails_artifact_step_and_the_run():
    responses = _success_responses(gpx=b"<gpx/>")
    responses.pop(8)  # routebestanden stopt vóór de preview-request
    http = StubHTTP(responses)
    report = e2e_prod.E2ERunner(
        _config(),
        request=http,
        authenticate=lambda _config: "access-token",
        printer=lambda _line: None,
    ).run()

    assert report.steps[7].status == "FOUT"
    assert "<?xml" in report.steps[7].detail
    assert report.exit_code == 1
