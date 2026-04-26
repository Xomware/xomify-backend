"""
Tests for `lambdas.notifications_unregister.handler`.

Verifies the (1f) auth-identity migration:
- Caller email is read from `requestContext.authorizer` via `get_caller_email`,
  not from the request body.
- `deviceToken` continues to be read from the body (it is the target token, not
  the caller identity).
- Missing caller identity returns 401.
- Missing / non-string `deviceToken` returns 400.
"""

import json
from typing import Any
from unittest.mock import patch

from lambdas.notifications_unregister.handler import handler


def _post_event(base: dict, body: dict) -> dict:
    return {
        **base,
        "httpMethod": "POST",
        "path": "/notifications/unregister",
        "body": json.dumps(body),
    }


@patch("lambdas.notifications_unregister.handler.delete_token")
def test_unregister_happy_path_uses_caller_email_from_context(
    mock_delete: Any, mock_context: Any, authorized_event: Any
) -> None:
    event = _post_event(
        authorized_event(email="alice@example.com"),
        {"deviceToken": "abcdef0123456789"},
    )

    response = handler(event, mock_context)

    assert response["statusCode"] == 200
    body = json.loads(response["body"])
    assert body["ok"] is True
    assert body["email"] == "alice@example.com"

    mock_delete.assert_called_once_with(
        email="alice@example.com",
        device_token="abcdef0123456789",
    )


@patch("lambdas.notifications_unregister.handler.delete_token")
def test_unregister_ignores_email_in_body_prefers_context(
    mock_delete: Any, mock_context: Any, authorized_event: Any
) -> None:
    event = _post_event(
        authorized_event(email="trusted@example.com"),
        {"email": "spoofed@evil.com", "deviceToken": "abcdef0123456789"},
    )

    response = handler(event, mock_context)

    assert response["statusCode"] == 200
    body = json.loads(response["body"])
    assert body["email"] == "trusted@example.com"
    mock_delete.assert_called_once_with(
        email="trusted@example.com",
        device_token="abcdef0123456789",
    )


@patch("lambdas.notifications_unregister.handler.delete_token")
def test_unregister_falls_back_to_query_email_when_context_empty(
    mock_delete: Any, mock_context: Any, legacy_event: Any
) -> None:
    event = _post_event(
        legacy_event(email="legacy@example.com"),
        {"deviceToken": "abcdef0123456789"},
    )

    response = handler(event, mock_context)

    assert response["statusCode"] == 200
    body = json.loads(response["body"])
    assert body["email"] == "legacy@example.com"
    mock_delete.assert_called_once_with(
        email="legacy@example.com",
        device_token="abcdef0123456789",
    )


@patch("lambdas.notifications_unregister.handler.delete_token")
def test_unregister_returns_401_when_caller_identity_missing(
    mock_delete: Any, mock_context: Any, legacy_event: Any
) -> None:
    event = _post_event(legacy_event(), {"deviceToken": "abcdef0123456789"})

    response = handler(event, mock_context)

    assert response["statusCode"] == 401
    mock_delete.assert_not_called()


@patch("lambdas.notifications_unregister.handler.delete_token")
def test_unregister_returns_400_when_device_token_missing(
    mock_delete: Any, mock_context: Any, authorized_event: Any
) -> None:
    event = _post_event(authorized_event(email="alice@example.com"), {})

    response = handler(event, mock_context)

    assert response["statusCode"] == 400
    mock_delete.assert_not_called()


@patch("lambdas.notifications_unregister.handler.delete_token")
def test_unregister_returns_400_when_device_token_not_string(
    mock_delete: Any, mock_context: Any, authorized_event: Any
) -> None:
    event = _post_event(
        authorized_event(email="alice@example.com"),
        {"deviceToken": 12345},
    )

    response = handler(event, mock_context)

    assert response["statusCode"] == 400
    mock_delete.assert_not_called()
