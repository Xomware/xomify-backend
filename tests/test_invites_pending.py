"""
Tests for invites_pending lambda.

Caller identity is sourced via `get_caller_email`, which prefers the per-user
JWT context populated by the authorizer and falls back to the query-string
`email` during the Track 0 -> Track 1 migration window. Both code paths are
exercised below.
"""

import json
from unittest.mock import patch

from lambdas.invites_pending.handler import handler


def _get_event(base_event):
    return {
        **base_event,
        "httpMethod": "GET",
        "path": "/invites/pending",
    }


# ============================================
# Trusted authorizer-context path (per-user JWT)
# ============================================

@patch('lambdas.invites_pending.handler.list_invites_by_sender')
def test_invites_pending_happy_path_context(
    mock_list, mock_context, authorized_event
):
    mock_list.return_value = [
        {
            "inviteCode": "ABCDEFGH",
            "senderEmail": "user@example.com",
            "createdAt": "2026-04-01T00:00:00+00:00",
            "expiresAt": "2026-05-01T00:00:00+00:00",
        }
    ]

    event = _get_event(authorized_event(email="user@example.com"))
    response = handler(event, mock_context)

    assert response['statusCode'] == 200
    body = json.loads(response['body'])
    assert body['email'] == "user@example.com"
    assert body['count'] == 1
    assert body['invites'][0]['inviteCode'] == "ABCDEFGH"
    assert body['invites'][0]['inviteUrl'].endswith("/invite/ABCDEFGH")
    mock_list.assert_called_once_with("user@example.com", active_only=True)


# ============================================
# Legacy query-string fallback path (pre-migration clients)
# ============================================

@patch('lambdas.invites_pending.handler.list_invites_by_sender')
def test_invites_pending_happy_path_fallback(
    mock_list, mock_context, legacy_event
):
    mock_list.return_value = []

    event = _get_event(legacy_event(email="user@example.com"))
    response = handler(event, mock_context)

    assert response['statusCode'] == 200
    body = json.loads(response['body'])
    assert body['email'] == "user@example.com"
    assert body['count'] == 0
    assert body['invites'] == []
    mock_list.assert_called_once_with("user@example.com", active_only=True)


# ============================================
# Caller missing entirely -> 401 from helper
# ============================================

@patch('lambdas.invites_pending.handler.list_invites_by_sender')
def test_invites_pending_missing_caller(mock_list, mock_context, legacy_event):
    event = _get_event(legacy_event())
    response = handler(event, mock_context)
    assert response['statusCode'] == 401
    mock_list.assert_not_called()


# ============================================
# Empty invites list (caller via context)
# ============================================

@patch('lambdas.invites_pending.handler.list_invites_by_sender')
def test_invites_pending_empty_list(mock_list, mock_context, authorized_event):
    mock_list.return_value = []

    event = _get_event(authorized_event(email="user@example.com"))
    response = handler(event, mock_context)

    assert response['statusCode'] == 200
    body = json.loads(response['body'])
    assert body['count'] == 0
    assert body['invites'] == []
