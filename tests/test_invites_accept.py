"""
Tests for invites_accept lambda
"""

import json
from datetime import datetime, timezone, timedelta
from unittest.mock import patch

from botocore.exceptions import ClientError

from lambdas.invites_accept.handler import handler


def _event(api_gateway_event, body):
    return {
        **api_gateway_event,
        "httpMethod": "POST",
        "path": "/invites/accept",
        "body": json.dumps(body),
    }


def _future_iso(days: int = 30) -> str:
    return (datetime.now(timezone.utc) + timedelta(days=days)).isoformat()


def _past_iso(days: int = 1) -> str:
    return (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()


@patch('lambdas.invites_accept.handler.create_accepted_friendship')
@patch('lambdas.invites_accept.handler.list_all_friends_for_user')
@patch('lambdas.invites_accept.handler.consume_invite')
@patch('lambdas.invites_accept.handler.get_invite')
def test_invites_accept_happy_path(
    mock_get, mock_consume, mock_friends, mock_create_fs, mock_context, api_gateway_event
):
    mock_get.return_value = {
        "inviteCode": "ABCDEFGH",
        "senderEmail": "alice@example.com",
        "expiresAt": _future_iso(),
    }
    mock_friends.return_value = []
    mock_consume.return_value = {"consumedAt": "2026-04-22T12:00:00+00:00"}
    mock_create_fs.return_value = True

    response = handler(
        _event(api_gateway_event, {"email": "bob@example.com", "inviteCode": "ABCDEFGH"}),
        mock_context,
    )

    assert response['statusCode'] == 200
    body = json.loads(response['body'])
    assert body['ok'] is True
    assert body['senderEmail'] == "alice@example.com"
    mock_create_fs.assert_called_once_with("alice@example.com", "bob@example.com")


@patch('lambdas.invites_accept.handler.get_invite')
def test_invites_accept_not_found(mock_get, mock_context, api_gateway_event):
    mock_get.return_value = None
    response = handler(
        _event(api_gateway_event, {"email": "bob@example.com", "inviteCode": "NOPE"}),
        mock_context,
    )
    assert response['statusCode'] == 404


@patch('lambdas.invites_accept.handler.get_invite')
def test_invites_accept_already_consumed(mock_get, mock_context, api_gateway_event):
    mock_get.return_value = {
        "inviteCode": "ABCDEFGH",
        "senderEmail": "alice@example.com",
        "expiresAt": _future_iso(),
        "consumedAt": "2026-04-21T10:00:00+00:00",
        "consumedBy": "someone@example.com",
    }
    response = handler(
        _event(api_gateway_event, {"email": "bob@example.com", "inviteCode": "ABCDEFGH"}),
        mock_context,
    )
    assert response['statusCode'] == 410
    body = json.loads(response['body'])
    assert body['error']['error_code'] == "INVITE_CONSUMED"


@patch('lambdas.invites_accept.handler.get_invite')
def test_invites_accept_expired(mock_get, mock_context, api_gateway_event):
    mock_get.return_value = {
        "inviteCode": "ABCDEFGH",
        "senderEmail": "alice@example.com",
        "expiresAt": _past_iso(),
    }
    response = handler(
        _event(api_gateway_event, {"email": "bob@example.com", "inviteCode": "ABCDEFGH"}),
        mock_context,
    )
    assert response['statusCode'] == 410
    body = json.loads(response['body'])
    assert body['error']['error_code'] == "INVITE_EXPIRED"


@patch('lambdas.invites_accept.handler.get_invite')
def test_invites_accept_self_invite(mock_get, mock_context, api_gateway_event):
    mock_get.return_value = {
        "inviteCode": "ABCDEFGH",
        "senderEmail": "alice@example.com",
        "expiresAt": _future_iso(),
    }
    response = handler(
        _event(api_gateway_event, {"email": "alice@example.com", "inviteCode": "ABCDEFGH"}),
        mock_context,
    )
    assert response['statusCode'] == 400


@patch('lambdas.invites_accept.handler.list_all_friends_for_user')
@patch('lambdas.invites_accept.handler.get_invite')
def test_invites_accept_already_friends(
    mock_get, mock_friends, mock_context, api_gateway_event
):
    mock_get.return_value = {
        "inviteCode": "ABCDEFGH",
        "senderEmail": "alice@example.com",
        "expiresAt": _future_iso(),
    }
    mock_friends.return_value = [
        {"friendEmail": "alice@example.com", "status": "accepted"},
    ]
    response = handler(
        _event(api_gateway_event, {"email": "bob@example.com", "inviteCode": "ABCDEFGH"}),
        mock_context,
    )
    assert response['statusCode'] == 409
    body = json.loads(response['body'])
    assert body['error']['error_code'] == "ALREADY_FRIENDS"


@patch('lambdas.invites_accept.handler.list_all_friends_for_user')
@patch('lambdas.invites_accept.handler.consume_invite')
@patch('lambdas.invites_accept.handler.get_invite')
def test_invites_accept_race_conditional_fail(
    mock_get, mock_consume, mock_friends, mock_context, api_gateway_event
):
    mock_get.return_value = {
        "inviteCode": "ABCDEFGH",
        "senderEmail": "alice@example.com",
        "expiresAt": _future_iso(),
    }
    mock_friends.return_value = []
    mock_consume.side_effect = ClientError(
        {"Error": {"Code": "ConditionalCheckFailedException", "Message": "consumed"}},
        "UpdateItem",
    )

    response = handler(
        _event(api_gateway_event, {"email": "bob@example.com", "inviteCode": "ABCDEFGH"}),
        mock_context,
    )
    assert response['statusCode'] == 410
    body = json.loads(response['body'])
    assert body['error']['error_code'] == "INVITE_UNAVAILABLE"
