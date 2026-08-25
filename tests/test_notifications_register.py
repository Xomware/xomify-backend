"""
Tests for `lambdas.notifications_register.handler`.

Verifies the (1f) auth-identity migration:
- Caller email is read from `requestContext.authorizer` via `get_caller_email`,
  not from the request body.
- `deviceToken` continues to be read from the body (it is the target token, not
  the caller identity).
- Missing caller identity returns 401 (MissingCallerIdentityError).
- Missing `deviceToken` returns 400 (ValidationError).
- Short / non-string `deviceToken` returns 400.
"""

import json
from typing import Any
from unittest.mock import patch

from lambdas.notifications_register.handler import handler


def _post_event(base: dict, body: dict) -> dict:
    """Apply httpMethod/path/body overrides to a base event dict."""
    return {
        **base,
        "httpMethod": "POST",
        "path": "/notifications/register",
        "body": json.dumps(body),
    }


@patch("lambdas.notifications_register.handler.upsert_token")
def test_register_happy_path_uses_caller_email_from_context(
    mock_upsert: Any, mock_context: Any, authorized_event: Any
) -> None:
    """
    CONTRACT CHANGE (per-type preferences, B2): a registration that mentions no
    flags now writes no flags. It used to coerce both legacy flags to True and
    persist them, which would freeze today's defaults onto the row and destroy
    the absent-means-registry-default fallback every new kind depends on.
    """
    mock_upsert.return_value = {"email": "alice@example.com"}

    event = _post_event(
        authorized_event(email="alice@example.com"),
        {"deviceToken": "abcdef0123456789"},
    )

    response = handler(event, mock_context)

    assert response["statusCode"] == 200
    body = json.loads(response["body"])
    assert body["ok"] is True
    assert body["email"] == "alice@example.com"

    # Effective map is returned, resolved against the registry defaults.
    assert body["preferences"]["queueNotificationsEnabled"] is True
    assert body["preferences"]["digestEnabled"] is False
    assert body["queueNotificationsEnabled"] is True

    mock_upsert.assert_called_once_with(
        email="alice@example.com",
        device_token="abcdef0123456789",
        preferences={},
        digest_enabled=None,
        queue_notifications_enabled=None,
    )


@patch("lambdas.notifications_register.handler.upsert_token")
def test_register_ignores_email_in_body_prefers_context(
    mock_upsert: Any, mock_context: Any, authorized_event: Any
) -> None:
    """Spoofed body email must NOT win over the trusted authorizer context."""
    mock_upsert.return_value = {"email": "trusted@example.com"}
    event = _post_event(
        authorized_event(email="trusted@example.com"),
        {"email": "spoofed@evil.com", "deviceToken": "abcdef0123456789"},
    )

    response = handler(event, mock_context)

    assert response["statusCode"] == 200
    body = json.loads(response["body"])
    assert body["email"] == "trusted@example.com"
    mock_upsert.assert_called_once()
    assert mock_upsert.call_args.kwargs["email"] == "trusted@example.com"


@patch("lambdas.notifications_register.handler.upsert_token")
def test_register_honors_optional_flags(
    mock_upsert: Any, mock_context: Any, authorized_event: Any
) -> None:
    event = _post_event(
        authorized_event(email="alice@example.com"),
        {
            "deviceToken": "abcdef0123456789",
            "digestEnabled": False,
            "queueNotificationsEnabled": False,
        },
    )

    # The response echoes what is STORED, not what was asked for, so the
    # stubbed row has to look like the row DynamoDB would return.
    mock_upsert.return_value = {
        "email": "alice@example.com",
        "digestEnabled": False,
        "queueNotificationsEnabled": False,
    }

    response = handler(event, mock_context)

    assert response["statusCode"] == 200
    body = json.loads(response["body"])
    assert body["digestEnabled"] is False
    assert body["queueNotificationsEnabled"] is False
    mock_upsert.assert_called_once_with(
        email="alice@example.com",
        device_token="abcdef0123456789",
        preferences={},
        digest_enabled=False,
        queue_notifications_enabled=False,
    )


@patch("lambdas.notifications_register.handler.upsert_token")
def test_register_falls_back_to_query_email_when_context_empty(
    mock_upsert: Any, mock_context: Any, legacy_event: Any
) -> None:
    """During the migration window, legacy callers send `email` as a query param."""
    event = _post_event(
        legacy_event(email="legacy@example.com"),
        {"deviceToken": "abcdef0123456789"},
    )

    response = handler(event, mock_context)

    assert response["statusCode"] == 200
    body = json.loads(response["body"])
    assert body["email"] == "legacy@example.com"
    mock_upsert.assert_called_once()
    assert mock_upsert.call_args.kwargs["email"] == "legacy@example.com"


@patch("lambdas.notifications_register.handler.upsert_token")
def test_register_returns_401_when_caller_identity_missing(
    mock_upsert: Any, mock_context: Any, legacy_event: Any
) -> None:
    """No context AND no fallback email -> MissingCallerIdentityError -> 401."""
    event = _post_event(legacy_event(), {"deviceToken": "abcdef0123456789"})

    response = handler(event, mock_context)

    assert response["statusCode"] == 401
    mock_upsert.assert_not_called()


@patch("lambdas.notifications_register.handler.upsert_token")
def test_register_returns_400_when_device_token_missing(
    mock_upsert: Any, mock_context: Any, authorized_event: Any
) -> None:
    event = _post_event(authorized_event(email="alice@example.com"), {})

    response = handler(event, mock_context)

    assert response["statusCode"] == 400
    mock_upsert.assert_not_called()


@patch("lambdas.notifications_register.handler.upsert_token")
def test_register_returns_400_when_device_token_too_short(
    mock_upsert: Any, mock_context: Any, authorized_event: Any
) -> None:
    event = _post_event(
        authorized_event(email="alice@example.com"),
        {"deviceToken": "short"},
    )

    response = handler(event, mock_context)

    assert response["statusCode"] == 400
    mock_upsert.assert_not_called()
