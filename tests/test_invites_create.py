"""
Tests for invites_create lambda.

Caller identity is sourced via `get_caller_email`, which prefers the per-user
JWT context populated by the authorizer and falls back to the body-supplied
`email` during the Track 0 -> Track 1 migration window. Both code paths are
exercised below.
"""

import json
from unittest.mock import patch

from botocore.exceptions import ClientError

from lambdas.invites_create.handler import handler


def _post_event(base_event, body):
    return {
        **base_event,
        "httpMethod": "POST",
        "path": "/invites/create",
        "body": json.dumps(body),
    }


# ============================================
# Trusted authorizer-context path (per-user JWT)
# ============================================

@patch('lambdas.invites_create.handler.create_invite')
@patch('lambdas.invites_create.handler.generate_invite_code')
@patch('lambdas.invites_create.handler.count_outstanding_invites_for_sender')
def test_invites_create_happy_path_context(
    mock_count, mock_gen, mock_create, mock_context, authorized_event
):
    mock_count.return_value = 0
    mock_gen.return_value = "ABCDEFGH"
    mock_create.return_value = {
        "inviteCode": "ABCDEFGH",
        "senderEmail": "user@example.com",
        "createdAt": "2026-04-22T12:00:00+00:00",
        "expiresAt": "2026-05-22T12:00:00+00:00",
    }

    event = _post_event(authorized_event(email="user@example.com"), {})
    response = handler(event, mock_context)

    assert response['statusCode'] == 200
    body = json.loads(response['body'])
    assert body['inviteCode'] == "ABCDEFGH"
    assert body['inviteUrl'].endswith("/invite/ABCDEFGH")
    assert body['expiresAt'] == "2026-05-22T12:00:00+00:00"
    mock_count.assert_called_once_with("user@example.com")


# ============================================
# Legacy body-fallback path (pre-migration clients)
# ============================================

@patch('lambdas.invites_create.handler.create_invite')
@patch('lambdas.invites_create.handler.generate_invite_code')
@patch('lambdas.invites_create.handler.count_outstanding_invites_for_sender')
def test_invites_create_happy_path_fallback(
    mock_count, mock_gen, mock_create, mock_context, legacy_event
):
    mock_count.return_value = 0
    mock_gen.return_value = "ABCDEFGH"
    mock_create.return_value = {
        "inviteCode": "ABCDEFGH",
        "senderEmail": "user@example.com",
        "createdAt": "2026-04-22T12:00:00+00:00",
        "expiresAt": "2026-05-22T12:00:00+00:00",
    }

    event = _post_event(legacy_event(), {"email": "user@example.com"})
    response = handler(event, mock_context)

    assert response['statusCode'] == 200
    body = json.loads(response['body'])
    assert body['inviteCode'] == "ABCDEFGH"
    mock_count.assert_called_once_with("user@example.com")


# ============================================
# Code-collision retry (caller via context)
# ============================================

@patch('lambdas.invites_create.handler.create_invite')
@patch('lambdas.invites_create.handler.generate_invite_code')
@patch('lambdas.invites_create.handler.count_outstanding_invites_for_sender')
def test_invites_create_code_collision_retry(
    mock_count, mock_gen, mock_create, mock_context, authorized_event
):
    mock_count.return_value = 0
    mock_gen.side_effect = ["COLLIDE1", "SUCCEED2", "NEVER"]

    collision = ClientError(
        {"Error": {"Code": "ConditionalCheckFailedException", "Message": "exists"}},
        "PutItem",
    )

    mock_create.side_effect = [
        collision,
        {
            "inviteCode": "SUCCEED2",
            "senderEmail": "user@example.com",
            "createdAt": "2026-04-22T12:00:00+00:00",
            "expiresAt": "2026-05-22T12:00:00+00:00",
        },
    ]

    event = _post_event(authorized_event(email="user@example.com"), {})
    response = handler(event, mock_context)

    assert response['statusCode'] == 200
    body = json.loads(response['body'])
    assert body['inviteCode'] == "SUCCEED2"
    assert mock_create.call_count == 2


# ============================================
# Rate-limit cap (caller via context)
# ============================================

@patch('lambdas.invites_create.handler.create_invite')
@patch('lambdas.invites_create.handler.count_outstanding_invites_for_sender')
def test_invites_create_rate_limit_exceeded(
    mock_count, mock_create, mock_context, authorized_event
):
    mock_count.return_value = 10

    event = _post_event(authorized_event(email="user@example.com"), {})
    response = handler(event, mock_context)

    assert response['statusCode'] == 429
    mock_create.assert_not_called()


# ============================================
# Caller missing entirely -> 401 from helper
# ============================================

@patch('lambdas.invites_create.handler.count_outstanding_invites_for_sender')
def test_invites_create_missing_caller(mock_count, mock_context, legacy_event):
    event = _post_event(legacy_event(), {})
    response = handler(event, mock_context)
    assert response['statusCode'] == 401
    mock_count.assert_not_called()
