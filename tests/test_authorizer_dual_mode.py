"""
Tests for the dual-mode JWT authorizer.

Covers:
- Per-user JWT (claims include email + userId): Allow + populated context.
- Legacy static token (no email/userId): Allow + tokenType=legacy only.
- Mixed JWT (email present, userId missing): Allow + tokenType=legacy.
- Invalid signature: Deny.
- Expired JWT: Deny.
- Missing / malformed Authorization header: Deny.

Note: conftest.py mocks `lambdas.common.ssm_helpers` so `API_SECRET_KEY` is
"test-api-secret-key". We mint test JWTs against that same key so signature
verification succeeds for the happy paths.
"""

from datetime import datetime, timedelta, timezone
from typing import Any
from unittest.mock import MagicMock

import jwt
import pytest

from lambdas.authorizer.handler import generate_policy, handler

API_SECRET_KEY = "test-api-secret-key"
METHOD_ARN = (
    "arn:aws:execute-api:us-east-1:123456789012:abc123def4/prod/GET/user/profile"
)
EXPECTED_RESOURCE_ARN = (
    "arn:aws:execute-api:us-east-1:123456789012:abc123def4/prod/*"
)


def _mint(payload: dict[str, Any], secret: str = API_SECRET_KEY) -> str:
    """Mint an HS256 JWT for tests."""
    return jwt.encode(payload, secret, algorithm="HS256")


def _event(token: str | None) -> dict[str, Any]:
    """Build a minimal authorizer event."""
    event: dict[str, Any] = {"methodArn": METHOD_ARN}
    if token is not None:
        event["authorizationToken"] = f"Bearer {token}"
    return event


@pytest.fixture
def lambda_context() -> Any:
    """Lightweight Lambda context — authorizer doesn't read fields off it."""
    ctx = MagicMock()
    ctx.aws_request_id = "test-request-id"
    return ctx


# ---------------------------------------------------------------------------
# generate_policy unit tests
# ---------------------------------------------------------------------------


def test_generate_policy_without_context_omits_context_key() -> None:
    response = generate_policy("Allow", EXPECTED_RESOURCE_ARN)
    assert "context" not in response
    assert response["principalId"] == "xomify"
    assert response["policyDocument"]["Statement"][0]["Effect"] == "Allow"
    assert response["policyDocument"]["Statement"][0]["Resource"] == EXPECTED_RESOURCE_ARN


def test_generate_policy_with_context_includes_context_key() -> None:
    ctx = {"email": "x@y.com", "userId": "abc", "tokenType": "user"}
    response = generate_policy("Allow", EXPECTED_RESOURCE_ARN, context=ctx)
    assert response["context"] == ctx


# ---------------------------------------------------------------------------
# Allow path — per-user JWT
# ---------------------------------------------------------------------------


def test_per_user_jwt_allows_and_populates_context(lambda_context) -> None:
    payload = {
        "email": "user@example.com",
        "userId": "spotify123",
        "iat": int(datetime.now(timezone.utc).timestamp()),
        "exp": int((datetime.now(timezone.utc) + timedelta(days=7)).timestamp()),
    }
    token = _mint(payload)

    response = handler(_event(token), lambda_context)

    assert response["policyDocument"]["Statement"][0]["Effect"] == "Allow"
    assert response["policyDocument"]["Statement"][0]["Resource"] == EXPECTED_RESOURCE_ARN
    assert response["context"] == {
        "email": "user@example.com",
        "userId": "spotify123",
        "tokenType": "user",
    }


# ---------------------------------------------------------------------------
# Allow path — legacy static token (no email/userId claims)
# ---------------------------------------------------------------------------


def test_legacy_token_allows_with_tokentype_legacy_only(lambda_context) -> None:
    # Mirrors today's static token: no email, no userId, just iat.
    payload = {"iat": int(datetime.now(timezone.utc).timestamp())}
    token = _mint(payload)

    response = handler(_event(token), lambda_context)

    assert response["policyDocument"]["Statement"][0]["Effect"] == "Allow"
    assert response["context"] == {"tokenType": "legacy"}
    assert "email" not in response["context"]
    assert "userId" not in response["context"]


# ---------------------------------------------------------------------------
# Allow path — mixed: email present, userId missing => legacy
# ---------------------------------------------------------------------------


def test_mixed_payload_email_only_falls_back_to_legacy(lambda_context) -> None:
    payload = {
        "email": "user@example.com",
        # userId intentionally omitted
        "iat": int(datetime.now(timezone.utc).timestamp()),
    }
    token = _mint(payload)

    response = handler(_event(token), lambda_context)

    assert response["policyDocument"]["Statement"][0]["Effect"] == "Allow"
    assert response["context"] == {"tokenType": "legacy"}


def test_mixed_payload_userid_only_falls_back_to_legacy(lambda_context) -> None:
    payload = {
        "userId": "spotify123",
        # email intentionally omitted
        "iat": int(datetime.now(timezone.utc).timestamp()),
    }
    token = _mint(payload)

    response = handler(_event(token), lambda_context)

    assert response["policyDocument"]["Statement"][0]["Effect"] == "Allow"
    assert response["context"] == {"tokenType": "legacy"}


def test_empty_string_claims_fall_back_to_legacy(lambda_context) -> None:
    payload = {
        "email": "",
        "userId": "",
        "iat": int(datetime.now(timezone.utc).timestamp()),
    }
    token = _mint(payload)

    response = handler(_event(token), lambda_context)

    assert response["policyDocument"]["Statement"][0]["Effect"] == "Allow"
    assert response["context"] == {"tokenType": "legacy"}


# ---------------------------------------------------------------------------
# Deny paths
# ---------------------------------------------------------------------------


def test_invalid_signature_denies(lambda_context) -> None:
    payload = {
        "email": "user@example.com",
        "userId": "spotify123",
        "exp": int((datetime.now(timezone.utc) + timedelta(days=7)).timestamp()),
    }
    # Sign with the WRONG secret.
    token = _mint(payload, secret="not-the-real-secret")

    response = handler(_event(token), lambda_context)

    assert response["policyDocument"]["Statement"][0]["Effect"] == "Deny"
    assert "context" not in response


def test_expired_jwt_denies(lambda_context) -> None:
    payload = {
        "email": "user@example.com",
        "userId": "spotify123",
        # Expired one hour ago.
        "exp": int((datetime.now(timezone.utc) - timedelta(hours=1)).timestamp()),
    }
    token = _mint(payload)

    response = handler(_event(token), lambda_context)

    assert response["policyDocument"]["Statement"][0]["Effect"] == "Deny"
    assert "context" not in response


def test_missing_authorization_header_denies(lambda_context) -> None:
    # Event has methodArn but no authorizationToken at all.
    response = handler({"methodArn": METHOD_ARN}, lambda_context)

    assert response["policyDocument"]["Statement"][0]["Effect"] == "Deny"
    assert "context" not in response


def test_empty_authorization_header_denies(lambda_context) -> None:
    event = {"methodArn": METHOD_ARN, "authorizationToken": ""}

    response = handler(event, lambda_context)

    assert response["policyDocument"]["Statement"][0]["Effect"] == "Deny"
    assert "context" not in response


def test_malformed_token_denies(lambda_context) -> None:
    event = {"methodArn": METHOD_ARN, "authorizationToken": "Bearer not.a.jwt"}

    response = handler(event, lambda_context)

    assert response["policyDocument"]["Statement"][0]["Effect"] == "Deny"
    assert "context" not in response


def test_missing_method_arn_denies(lambda_context) -> None:
    payload = {
        "email": "user@example.com",
        "userId": "spotify123",
        "exp": int((datetime.now(timezone.utc) + timedelta(days=7)).timestamp()),
    }
    token = _mint(payload)
    # No methodArn — handler should not attempt to mint an Allow.
    event = {"authorizationToken": f"Bearer {token}"}

    response = handler(event, lambda_context)

    assert response["policyDocument"]["Statement"][0]["Effect"] == "Deny"
    assert "context" not in response
