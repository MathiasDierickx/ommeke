"""ASGI-entrypoint voor de serverless AWS-runtime."""

from __future__ import annotations

import asyncio
import base64
import hashlib
import json
import os
import time
from collections.abc import Awaitable, Callable
from functools import lru_cache
from typing import Any

from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.routing import Mount, Route

from . import __version__, tenant
from .mcp_server import hosted_mcp


ASGIApp = Callable[[dict, Callable[[], Awaitable[dict]], Callable[[dict], Awaitable[None]]], Awaitable[None]]
PUBLIC_PATHS = {
    "/health",
    "/.well-known/oauth-protected-resource",
    "/.well-known/oauth-protected-resource/mcp",
}


def _header(scope: dict, name: str) -> str | None:
    wanted = name.lower().encode("ascii")
    for key, value in scope.get("headers", []):
        if key.lower() == wanted:
            return value.decode("latin-1")
    return None


def _request_origin(scope: dict) -> str:
    configured = os.environ.get("LUSMAKER_PUBLIC_URL", "").rstrip("/")
    if configured:
        return configured
    scheme = _header(scope, "x-forwarded-proto") or scope.get("scheme", "https")
    host = _header(scope, "x-forwarded-host") or _header(scope, "host")
    return f"{scheme}://{host or 'localhost'}"


def _resource_url(scope: dict) -> str:
    configured = os.environ.get("LUSMAKER_RESOURCE_URL", "").rstrip("/")
    return configured or f"{_request_origin(scope)}/mcp"


def _metadata_url(scope: dict) -> str:
    return f"{_request_origin(scope)}/.well-known/oauth-protected-resource"


@lru_cache(maxsize=1)
def _cognito_client():
    try:
        import boto3
    except ImportError as exc:
        raise RuntimeError(
            "Cognito-authenticatie is actief maar boto3 ontbreekt"
        ) from exc
    return boto3.client("cognito-idp")


class CognitoAuthMiddleware:
    """Valideer Cognito access tokens en zet de tenantcontext op ``sub``."""

    def __init__(
        self,
        app: ASGIApp,
        *,
        client: Any | None = None,
        auth_mode: str | None = None,
        cache_seconds: int = 60,
    ) -> None:
        self.app = app
        self.client = client
        self.auth_mode = (
            auth_mode or os.environ.get("LUSMAKER_AUTH_MODE", "cognito")
        ).casefold()
        if self.auth_mode not in {"cognito", "none"}:
            raise ValueError("LUSMAKER_AUTH_MODE moet 'cognito' of 'none' zijn")
        self.cache_seconds = max(0, cache_seconds)
        self._token_cache: dict[str, tuple[float, str]] = {}

    async def _unauthorized(self, scope, receive, send) -> None:
        required_scope = os.environ.get(
            "LUSMAKER_OAUTH_SCOPE", "aws.cognito.signin.user.admin"
        )
        response = JSONResponse(
            {"error": "Geldige Cognito access token vereist."},
            status_code=401,
            headers={
                "WWW-Authenticate": (
                    'Bearer resource_metadata="'
                    f"{_metadata_url(scope)}"
                    f'", scope="{required_scope}"'
                )
            },
        )
        await response(scope, receive, send)

    async def _tenant_for_token(self, token: str) -> str | None:
        digest = hashlib.sha256(token.encode()).hexdigest()
        now = time.monotonic()
        cached = self._token_cache.get(digest)
        if cached and cached[0] > now:
            return cached[1]
        try:
            client = self.client or _cognito_client()
            result = await asyncio.to_thread(client.get_user, AccessToken=token)
        except Exception:
            return None
        try:
            encoded_claims = token.split(".")[1]
            padding = "=" * (-len(encoded_claims) % 4)
            claims = json.loads(
                base64.urlsafe_b64decode(encoded_claims + padding)
            )
        except (IndexError, ValueError, json.JSONDecodeError):
            claims = {}
        expected_client = os.environ.get("LUSMAKER_OAUTH_CLIENT_ID")
        if expected_client and claims.get("client_id") != expected_client:
            return None
        required_scope = os.environ.get("LUSMAKER_OAUTH_SCOPE")
        if (
            required_scope
            and required_scope not in str(claims.get("scope", "")).split()
        ):
            return None
        attributes = {
            item.get("Name"): item.get("Value")
            for item in result.get("UserAttributes", [])
        }
        tenant_id = attributes.get("sub") or result.get("Username")
        if not tenant_id:
            return None
        if len(self._token_cache) >= 512:
            self._token_cache.clear()
        self._token_cache[digest] = (now + self.cache_seconds, tenant_id)
        return tenant_id

    async def __call__(self, scope, receive, send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        path = scope.get("path", "")
        method = scope.get("method", "GET")
        if (
            self.auth_mode == "none"
            or method == "OPTIONS"
            or path in PUBLIC_PATHS
        ):
            with tenant.use("anonymous" if self.auth_mode == "none" else None):
                await self.app(scope, receive, send)
            return
        authorization = _header(scope, "authorization") or ""
        scheme, _, token = authorization.partition(" ")
        if scheme.casefold() != "bearer" or not token.strip():
            await self._unauthorized(scope, receive, send)
            return
        tenant_id = await self._tenant_for_token(token.strip())
        if not tenant_id:
            await self._unauthorized(scope, receive, send)
            return
        with tenant.use(tenant_id):
            await self.app(scope, receive, send)


async def health(_request: Request) -> JSONResponse:
    """Lichte readiness check; GraphHopper start vóór de ASGI-server."""
    return JSONResponse({"status": "ok", "version": __version__})


async def oauth_protected_resource(request: Request) -> JSONResponse:
    issuer = os.environ.get("LUSMAKER_OAUTH_ISSUER", "").rstrip("/")
    scope = os.environ.get(
        "LUSMAKER_OAUTH_SCOPE", "aws.cognito.signin.user.admin"
    )
    payload: dict[str, Any] = {
        "resource": _resource_url(request.scope),
        "bearer_methods_supported": ["header"],
        "scopes_supported": [scope],
        "token_endpoint_auth_methods_supported": [
            item.strip()
            for item in os.environ.get(
                "LUSMAKER_TOKEN_AUTH_METHODS",
                "client_secret_basic,client_secret_post",
            ).split(",")
            if item.strip()
        ],
    }
    if issuer:
        payload["authorization_servers"] = [issuer]
    return JSONResponse(payload)


def create_app(
    *, cognito_client: Any | None = None, auth_mode: str | None = None
) -> ASGIApp:
    mcp_app = hosted_mcp.streamable_http_app(
        streamable_http_path="/mcp",
        stateless_http=True,
        json_response=True,
        host="0.0.0.0",
    )
    routed = Starlette(
        routes=[
            Route("/health", health, methods=["GET"]),
            Route(
                "/.well-known/oauth-protected-resource",
                oauth_protected_resource,
                methods=["GET"],
            ),
            Route(
                "/.well-known/oauth-protected-resource/mcp",
                oauth_protected_resource,
                methods=["GET"],
            ),
            Mount("/", app=mcp_app),
        ]
    )
    return CognitoAuthMiddleware(
        routed, client=cognito_client, auth_mode=auth_mode
    )


app = create_app()
