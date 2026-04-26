"""
Tests for invites_decline lambda.

Caller identity is sourced via `get_caller_email`, which prefers the per-user
JWT context populated by the authorizer and falls back to the body-supplied
`email` during the Track 0 -> Track 1 migration window. Both code paths are
exercised below.
"""

import json
from datetime import datetime, timezone, timedelta
from unittest.mock import patch

from botocore.exceptions import ClientError

from lambdas.invites_decline.handler import handler


def _post_event(base_event, body):
    return {
        **base_event,
        "httpMethod": "POST",
        "path": "/invites/decline",
        "body": json.dumps(body),
    }


def _future_iso(days: int = 30) -> str:
    return (datetime.now(timezone.utc) + timedelta(days=days)).isoformat()


def _past_iso(days: int = 1) -> str:
    return (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()


# ============================================
# Trusted authorizer-context path (per-user JWT)
# ============================================

@patch('lambdas.invites_decline.handler.decline_invite')
@patch('lambdas.invites_decline.handler.get_invite')
def test_invites_decline_happy_path_context(
    mock_get, mock_decline, mock_context, authorized_event
):
    mock_get.return_value = {
        "inviteCode": "ABCDEFGH",
        "senderEmail": "alice@example.com",
        "expiresAt": _future_iso(),
    }
    mock_decline.return_value = {"consumedAt": "2026-04-22T12:00:00+00:00"}

    event = _post_event(
        authorized_event(email="bob@example.com"),
        {"inviteCode": "ABCDEFGH"},
    )
    response = handler(event, mock_context)

    assert response['statusCode'] == 200
    body = json.loads(response['body'])
    assert body['ok'] is True
    assert body['senderEmail'] == "alice@example.com"
    mock_decline.assert_called_once_with("ABCDEFGH", "bob@example.com")


# ============================================
# Legacy body-fallback path (pre-migration clients)
# ============================================

@patch('lambdas.invites_decline.handler.decline_invite')
@patch('lambdas.invites_decline.handler.get_invite')
def test_invites_decline_happy_path_fallback(
    mock_get, mock_decline, mock_context, legacy_event
):
    mock_get.return_value = {
        "inviteCode": "ABCDEFGH",
        "senderEmail": "alice@example.com",
        "expiresAt": _future_iso(),
    }
    mock_decline.return_value = {"consumedAt": "2026-04-22T12:00:00+00:00"}

    event = _post_event(
        legacy_event(),
        {"email": "bob@example.com", "inviteCode": "ABCDEFGH"},
    )
    response = handler(event, mock_context)

    assert response['statusCode'] == 200
    body = json.loads(response['body'])
    assert body['ok'] is True
    mock_decline.assert_called_once_with("ABCDEFGH", "bob@example.com")


# ============================================
# Caller missing entirely -> 401 from helper
# ============================================

def test_invites_decline_missing_caller(mock_context, legacy_event):
    event = _post_event(legacy_event(), {"inviteCode": "ABCDEFGH"})
    response = handler(event, mock_context)
    assert response['statusCode'] == 401


# ============================================
# Domain-rule failure cases
# ============================================

@patch('lambdas.invites_decline.handler.get_invite')
def test_invites_decline_not_found(mock_get, mock_context, authorized_event):
    mock_get.return_value = None
    event = _post_event(
        authorized_event(email="bob@example.com"),
        {"inviteCode": "NOPE"},
    )
    response = handler(event, mock_context)
    assert response['statusCode'] == 404


@patch('lambdas.invites_decline.handler.get_invite')
def test_invites_decline_already_consumed(mock_get, mock_context, authorized_event):
    mock_get.return_value = {
        "inviteCode": "ABCDEFGH",
        "senderEmail": "alice@example.com",
        "expiresAt": _future_iso(),
        "consumedAt": "2026-04-21T10:00:00+00:00",
    }
    event = _post_event(
        authorized_event(email="bob@example.com"),
        {"inviteCode": "ABCDEFGH"},
    )
    response = handler(event, mock_context)
    assert response['statusCode'] == 410
    body = json.loads(response['body'])
    assert body['error']['error_code'] == "INVITE_CONSUMED"


@patch('lambdas.invites_decline.handler.get_invite')
def test_invites_decline_expired(mock_get, mock_context, authorized_event):
    mock_get.return_value = {
        "inviteCode": "ABCDEFGH",
        "senderEmail": "alice@example.com",
        "expiresAt": _past_iso(),
    }
    event = _post_event(
        authorized_event(email="bob@example.com"),
        {"inviteCode": "ABCDEFGH"},
    )
    response = handler(event, mock_context)
    assert response['statusCode'] == 410
    body = json.loads(response['body'])
    assert body['error']['error_code'] == "INVITE_EXPIRED"


@patch('lambdas.invites_decline.handler.get_invite')
def test_invites_decline_self_invite(mock_get, mock_context, authorized_event):
    mock_get.return_value = {
        "inviteCode": "ABCDEFGH",
        "senderEmail": "alice@example.com",
        "expiresAt": _future_iso(),
    }
    event = _post_event(
        authorized_event(email="alice@example.com"),
        {"inviteCode": "ABCDEFGH"},
    )
    response = handler(event, mock_context)
    assert response['statusCode'] == 400


@patch('lambdas.invites_decline.handler.decline_invite')
@patch('lambdas.invites_decline.handler.get_invite')
def test_invites_decline_race_conditional_fail(
    mock_get, mock_decline, mock_context, authorized_event
):
    mock_get.return_value = {
        "inviteCode": "ABCDEFGH",
        "senderEmail": "alice@example.com",
        "expiresAt": _future_iso(),
    }
    mock_decline.side_effect = ClientError(
        {"Error": {"Code": "ConditionalCheckFailedException", "Message": "consumed"}},
        "UpdateItem",
    )

    event = _post_event(
        authorized_event(email="bob@example.com"),
        {"inviteCode": "ABCDEFGH"},
    )
    response = handler(event, mock_context)
    assert response['statusCode'] == 410
    body = json.loads(response['body'])
    assert body['error']['error_code'] == "INVITE_UNAVAILABLE"


def test_invites_decline_missing_invite_code(mock_context, authorized_event):
    event = _post_event(authorized_event(email="bob@example.com"), {})
    response = handler(event, mock_context)
    assert response['statusCode'] == 400
