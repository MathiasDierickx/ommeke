"""Offline tests voor de Lambda-ASGI-laag en Cognito-tenantisolatie."""

from __future__ import annotations

import asyncio
import base64
import json
import os

from lusmaker import tenant
from lusmaker.aws_app import CognitoAuthMiddleware, create_app


class FakeCognito:
    def __init__(self, valid_token: str = "geldig"):
        self.valid_token = valid_token
        self.calls = []

    def get_user(self, *, AccessToken: str):
        self.calls.append(AccessToken)
        if AccessToken != self.valid_token:
            raise ValueError("ongeldige token")
        return {
            "Username": "fallback",
            "UserAttributes": [{"Name": "sub", "Value": "user-123"}],
        }


def _access_token(client_id: str, scope: str) -> str:
    claims = json.dumps({"client_id": client_id, "scope": scope}).encode()
    encoded = base64.urlsafe_b64encode(claims).rstrip(b"=").decode()
    return f"header.{encoded}.signature"


async def _invoke(app, path="/", *, headers=None, method="GET"):
    messages = []
    request_sent = False

    async def receive():
        nonlocal request_sent
        if not request_sent:
            request_sent = True
            return {"type": "http.request", "body": b"", "more_body": False}
        return {"type": "http.disconnect"}

    async def send(message):
        messages.append(message)

    encoded_headers = [(b"host", b"routes.example")]
    encoded_headers.extend(
        (key.lower().encode(), value.encode())
        for key, value in (headers or {}).items()
    )
    await app(
        {
            "type": "http",
            "asgi": {"version": "3.0"},
            "http_version": "1.1",
            "scheme": "https",
            "method": method,
            "path": path,
            "raw_path": path.encode(),
            "query_string": b"",
            "headers": encoded_headers,
            "client": ("127.0.0.1", 1234),
            "server": ("routes.example", 443),
            "root_path": "",
        },
        receive,
        send,
    )
    start = next(item for item in messages if item["type"] == "http.response.start")
    body = b"".join(
        item.get("body", b"")
        for item in messages
        if item["type"] == "http.response.body"
    )
    return start, body


def _json_response(app, *args, **kwargs):
    start, body = asyncio.run(_invoke(app, *args, **kwargs))
    return start, json.loads(body)


def test_health_and_oauth_metadata_are_public():
    previous_issuer = os.environ.get("LUSMAKER_OAUTH_ISSUER")
    os.environ["LUSMAKER_OAUTH_ISSUER"] = (
        "https://cognito-idp.eu-west-1.amazonaws.com/eu-west-1_pool"
    )
    try:
        app = create_app(cognito_client=FakeCognito(), auth_mode="cognito")
        health_start, health_body = _json_response(app, "/health")
        assert health_start["status"] == 200
        assert health_body["status"] == "ok"

        metadata_start, metadata = _json_response(
            app, "/.well-known/oauth-protected-resource"
        )
        assert metadata_start["status"] == 200
        assert metadata["resource"] == "https://routes.example/mcp"
        assert metadata["authorization_servers"] == [
            "https://cognito-idp.eu-west-1.amazonaws.com/eu-west-1_pool"
        ]
        assert metadata["bearer_methods_supported"] == ["header"]
    finally:
        if previous_issuer is None:
            os.environ.pop("LUSMAKER_OAUTH_ISSUER", None)
        else:
            os.environ["LUSMAKER_OAUTH_ISSUER"] = previous_issuer


def test_missing_bearer_token_returns_oauth_challenge():
    client = FakeCognito()

    async def private_app(scope, receive, send):
        raise AssertionError("private app mag niet worden aangeroepen")

    app = CognitoAuthMiddleware(
        private_app, client=client, auth_mode="cognito"
    )
    start, body = _json_response(app, "/mcp", method="POST")
    assert start["status"] == 401
    headers = dict(start["headers"])
    assert b"resource_metadata=" in headers[b"www-authenticate"]
    assert "access token" in body["error"]
    assert client.calls == []


def test_valid_token_scopes_state_to_cognito_sub_and_is_cached():
    client = FakeCognito()

    async def echo_tenant(scope, receive, send):
        body = json.dumps({"tenant": tenant.current()}).encode()
        await send(
            {
                "type": "http.response.start",
                "status": 200,
                "headers": [(b"content-type", b"application/json")],
            }
        )
        await send({"type": "http.response.body", "body": body})

    app = CognitoAuthMiddleware(
        echo_tenant, client=client, auth_mode="cognito", cache_seconds=60
    )
    headers = {"authorization": "Bearer geldig"}
    first_start, first = _json_response(app, "/mcp", headers=headers, method="POST")
    second_start, second = _json_response(app, "/mcp", headers=headers, method="POST")
    assert first_start["status"] == second_start["status"] == 200
    assert first == second == {"tenant": "user-123"}
    assert client.calls == ["geldig"]
    assert tenant.current() == "anonymous"


def test_invalid_token_never_reaches_private_app():
    client = FakeCognito()

    async def private_app(scope, receive, send):
        raise AssertionError("private app mag niet worden aangeroepen")

    app = CognitoAuthMiddleware(
        private_app, client=client, auth_mode="cognito"
    )
    start, _body = _json_response(
        app,
        "/mcp",
        headers={"authorization": "Bearer fout"},
        method="POST",
    )
    assert start["status"] == 401
    assert client.calls == ["fout"]


def test_token_must_belong_to_configured_oauth_client_and_scope():
    required_scope = "aws.cognito.signin.user.admin"
    valid = _access_token("client-123", required_scope)
    wrong_client = _access_token("andere-client", required_scope)
    client = FakeCognito(valid_token=valid)
    previous_client = os.environ.get("LUSMAKER_OAUTH_CLIENT_ID")
    previous_scope = os.environ.get("LUSMAKER_OAUTH_SCOPE")
    os.environ["LUSMAKER_OAUTH_CLIENT_ID"] = "client-123"
    os.environ["LUSMAKER_OAUTH_SCOPE"] = required_scope

    async def private_app(scope, receive, send):
        await send(
            {"type": "http.response.start", "status": 204, "headers": []}
        )
        await send({"type": "http.response.body", "body": b""})

    try:
        app = CognitoAuthMiddleware(
            private_app, client=client, auth_mode="cognito"
        )
        accepted, _body = asyncio.run(
            _invoke(
                app,
                "/mcp",
                headers={"authorization": f"Bearer {valid}"},
                method="POST",
            )
        )
        assert accepted["status"] == 204

        client.valid_token = wrong_client
        rejected, _body = _json_response(
            app,
            "/mcp",
            headers={"authorization": f"Bearer {wrong_client}"},
            method="POST",
        )
        assert rejected["status"] == 401
    finally:
        if previous_client is None:
            os.environ.pop("LUSMAKER_OAUTH_CLIENT_ID", None)
        else:
            os.environ["LUSMAKER_OAUTH_CLIENT_ID"] = previous_client
        if previous_scope is None:
            os.environ.pop("LUSMAKER_OAUTH_SCOPE", None)
        else:
            os.environ["LUSMAKER_OAUTH_SCOPE"] = previous_scope


def test_token_accepts_one_of_multiple_configured_clients():
    required_scope = "aws.cognito.signin.user.admin"
    token = _access_token("web-client", required_scope)
    client = FakeCognito(valid_token=token)
    previous = os.environ.get("LUSMAKER_OAUTH_CLIENT_IDS")
    os.environ["LUSMAKER_OAUTH_CLIENT_IDS"] = "mcp-client,web-client"

    async def private_app(scope, receive, send):
        await send({"type": "http.response.start", "status": 204, "headers": []})
        await send({"type": "http.response.body", "body": b""})

    try:
        app = CognitoAuthMiddleware(
            private_app, client=client, auth_mode="cognito"
        )
        accepted, _body = asyncio.run(
            _invoke(
                app,
                "/api/me",
                headers={"authorization": f"Bearer {token}"},
            )
        )
        assert accepted["status"] == 204
    finally:
        if previous is None:
            os.environ.pop("LUSMAKER_OAUTH_CLIENT_IDS", None)
        else:
            os.environ["LUSMAKER_OAUTH_CLIENT_IDS"] = previous
