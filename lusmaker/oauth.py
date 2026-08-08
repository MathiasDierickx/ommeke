"""OAuth resource-serverconfiguratie en RS256-bearervalidatie."""

from __future__ import annotations

import asyncio
import os
from dataclasses import dataclass
from typing import Any

import jwt
from jwt import PyJWKClient
from mcp.server.auth.provider import AccessToken

from . import config


class OAuthError(RuntimeError):
    """Ontbrekende OAuth-configuratie of ongeldig bearer-token."""


@dataclass(frozen=True)
class OAuthConfig:
    issuer: str
    jwks_url: str
    audience: str

    @classmethod
    def from_env(cls) -> "OAuthConfig":
        values = {
            "issuer": os.environ.get("LUSMAKER_OAUTH_ISSUER", "").strip(),
            "jwks_url": os.environ.get("LUSMAKER_OAUTH_JWKS_URL", "").strip(),
            "audience": os.environ.get("LUSMAKER_OAUTH_AUDIENCE", "").strip(),
        }
        missing = [name for name, value in values.items() if not value]
        if missing:
            env_names = {
                "issuer": "LUSMAKER_OAUTH_ISSUER",
                "jwks_url": "LUSMAKER_OAUTH_JWKS_URL",
                "audience": "LUSMAKER_OAUTH_AUDIENCE",
            }
            raise OAuthError(
                "ontbrekende OAuth-configuratie: "
                + ", ".join(env_names[name] for name in missing)
            )
        return cls(**values)


def auth_disabled() -> bool:
    return os.environ.get("LUSMAKER_AUTH_DISABLED") == "1"


class JWTTokenVerifier:
    """Valideer externe RS256-JWT's en vertaal ze naar MCP-access tokens."""

    def __init__(
        self,
        oauth: OAuthConfig,
        *,
        jwks: dict[str, Any] | None = None,
        jwk_client: PyJWKClient | None = None,
    ):
        self.oauth = oauth
        self._jwks = jwks
        self._jwk_client = jwk_client or (
            None if jwks is not None else PyJWKClient(oauth.jwks_url)
        )

    def _fixture_key(self, token: str):
        try:
            header = jwt.get_unverified_header(token)
        except jwt.PyJWTError as exc:
            raise OAuthError("bearer-token heeft geen geldige JWT-header") from exc
        if header.get("alg") != "RS256":
            raise OAuthError("bearer-token moet RS256 gebruiken")
        kid = header.get("kid")
        if not isinstance(kid, str) or not kid:
            raise OAuthError("bearer-token mist een kid-header")
        keys = (self._jwks or {}).get("keys")
        if not isinstance(keys, list):
            raise OAuthError("JWKS-fixture mist een keys-lijst")
        matches = [key for key in keys if key.get("kid") == kid]
        if len(matches) != 1:
            raise OAuthError("geen unieke JWKS-sleutel voor bearer-token")
        try:
            return jwt.PyJWK.from_dict(matches[0], algorithm="RS256").key
        except (jwt.PyJWTError, ValueError) as exc:
            raise OAuthError("ongeldige JWKS-sleutel") from exc

    def _signing_key(self, token: str):
        if self._jwks is not None:
            return self._fixture_key(token)
        try:
            signing_key = self._jwk_client.get_signing_key_from_jwt(token)
        except jwt.PyJWTError as exc:
            raise OAuthError("ondertekeningssleutel voor bearer-token ontbreekt") from exc
        return signing_key.key

    def validate(self, token: str) -> dict[str, Any]:
        """Geef gevalideerde claims terug of werp een neutrale OAuthError."""
        try:
            claims = jwt.decode(
                token,
                self._signing_key(token),
                algorithms=["RS256"],
                audience=self.oauth.audience,
                issuer=self.oauth.issuer,
                options={"require": ["exp", "aud", "iss", "sub"]},
            )
        except OAuthError:
            raise
        except jwt.PyJWTError as exc:
            raise OAuthError("ongeldig of verlopen bearer-token") from exc
        subject = claims.get("sub")
        try:
            config.validate_user_id(subject)
        except ValueError as exc:
            raise OAuthError("bearer-token bevat een ongeldige subject-claim") from exc
        return claims

    async def verify_token(self, token: str) -> AccessToken | None:
        """FastMCP TokenVerifier-interface; ongeldige tokens leveren 401 op."""
        try:
            claims = await asyncio.to_thread(self.validate, token)
        except OAuthError:
            return None
        scopes = claims.get("scope", claims.get("scp", []))
        if isinstance(scopes, str):
            scopes = scopes.split()
        elif not isinstance(scopes, list):
            scopes = []
        client_id = (
            claims.get("client_id")
            or claims.get("azp")
            or self.oauth.audience
        )
        return AccessToken(
            token=token,
            client_id=str(client_id),
            scopes=[str(scope) for scope in scopes],
            expires_at=int(claims["exp"]),
            subject=claims["sub"],
            claims=claims,
        )
