"""Pure JWT-tests met een lokaal gemaakte RSA/JWKS-fixture."""

import asyncio
import time

import jwt
from cryptography.hazmat.primitives.asymmetric import rsa

from lusmaker.oauth import JWTTokenVerifier, OAuthConfig, OAuthError


def _fixture():
    private_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    jwk = jwt.algorithms.RSAAlgorithm.to_jwk(private_key.public_key(), as_dict=True)
    jwk.update({"kid": "test-key", "use": "sig", "alg": "RS256"})
    oauth = OAuthConfig(
        issuer="https://login.example.test",
        jwks_url="https://login.example.test/.well-known/jwks.json",
        audience="lusmaker-mcp",
    )
    return private_key, {"keys": [jwk]}, oauth


def _token(private_key, oauth, **overrides):
    now = int(time.time())
    claims = {
        "sub": "user-123",
        "iss": oauth.issuer,
        "aud": oauth.audience,
        "iat": now,
        "exp": now + 300,
        "scope": "routes:read routes:write",
        **overrides,
    }
    return jwt.encode(
        claims,
        private_key,
        algorithm="RS256",
        headers={"kid": "test-key"},
    )


def test_jwt_verifier_accepts_valid_rs256_token_and_preserves_subject():
    private_key, jwks, oauth = _fixture()
    verifier = JWTTokenVerifier(oauth, jwks=jwks)
    encoded = _token(private_key, oauth)

    claims = verifier.validate(encoded)
    access_token = asyncio.run(verifier.verify_token(encoded))

    assert claims["sub"] == "user-123"
    assert access_token is not None
    assert access_token.subject == "user-123"
    assert access_token.scopes == ["routes:read", "routes:write"]


def test_jwt_verifier_rejects_expired_token():
    private_key, jwks, oauth = _fixture()
    encoded = _token(private_key, oauth, exp=int(time.time()) - 1)

    try:
        JWTTokenVerifier(oauth, jwks=jwks).validate(encoded)
    except OAuthError as exc:
        assert "ongeldig of verlopen" in str(exc)
    else:
        raise AssertionError("verlopen token werd aanvaard")


def test_jwt_verifier_rejects_wrong_audience():
    private_key, jwks, oauth = _fixture()
    encoded = _token(private_key, oauth, aud="ander-publiek")

    verifier = JWTTokenVerifier(oauth, jwks=jwks)
    assert asyncio.run(verifier.verify_token(encoded)) is None
    try:
        verifier.validate(encoded)
    except OAuthError as exc:
        assert "ongeldig of verlopen" in str(exc)
    else:
        raise AssertionError("token voor verkeerde audience werd aanvaard")


def test_jwt_verifier_rejects_non_rs256_algorithm_before_decode():
    _private_key, jwks, oauth = _fixture()
    encoded = jwt.encode(
        {
            "sub": "user-123",
            "iss": oauth.issuer,
            "aud": oauth.audience,
            "exp": int(time.time()) + 300,
        },
        "test-secret-that-is-definitely-long-enough",
        algorithm="HS256",
        headers={"kid": "test-key"},
    )

    try:
        JWTTokenVerifier(oauth, jwks=jwks).validate(encoded)
    except OAuthError as exc:
        assert "RS256" in str(exc)
    else:
        raise AssertionError("niet-RS256-token werd aanvaard")
