"""
Tests for invites_create lambda
"""

import json
from unittest.mock import patch

from botocore.exceptions import ClientError

from lambdas.invites_create.handler import handler


def _event(api_gateway_event, body):
    return {
        **api_gateway_event,
        "httpMethod": "POST",
        "path": "/invites/create",
        "body": json.dumps(body),
    }


@patch('lambdas.invites_create.handler.create_invite')
@patch('lambdas.invites_create.handler.generate_invite_code')
@patch('lambdas.invites_create.handler.count_outstanding_invites_for_sender')
def test_invites_create_happy_path(
    mock_count, mock_gen, mock_create, mock_context, api_gateway_event
):
    mock_count.return_value = 0
    mock_gen.return_value = "ABCDEFGH"
    mock_create.return_value = {
        "inviteCode": "ABCDEFGH",
        "senderEmail": "user@example.com",
        "createdAt": "2026-04-22T12:00:00+00:00",
        "expiresAt": "2026-05-22T12:00:00+00:00",
    }

    response = handler(_event(api_gateway_event, {"email": "user@example.com"}), mock_context)

    assert response['statusCode'] == 200
    body = json.loads(response['body'])
    assert body['inviteCode'] == "ABCDEFGH"
    assert body['inviteUrl'].endswith("/invite/ABCDEFGH")
    assert body['expiresAt'] == "2026-05-22T12:00:00+00:00"


@patch('lambdas.invites_create.handler.create_invite')
@patch('lambdas.invites_create.handler.generate_invite_code')
@patch('lambdas.invites_create.handler.count_outstanding_invites_for_sender')
def test_invites_create_code_collision_retry(
    mock_count, mock_gen, mock_create, mock_context, api_gateway_event
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

    response = handler(_event(api_gateway_event, {"email": "user@example.com"}), mock_context)

    assert response['statusCode'] == 200
    body = json.loads(response['body'])
    assert body['inviteCode'] == "SUCCEED2"
    assert mock_create.call_count == 2


@patch('lambdas.invites_create.handler.create_invite')
@patch('lambdas.invites_create.handler.count_outstanding_invites_for_sender')
def test_invites_create_rate_limit_exceeded(
    mock_count, mock_create, mock_context, api_gateway_event
):
    mock_count.return_value = 10

    response = handler(_event(api_gateway_event, {"email": "user@example.com"}), mock_context)

    assert response['statusCode'] == 429
    mock_create.assert_not_called()


@patch('lambdas.invites_create.handler.count_outstanding_invites_for_sender')
def test_invites_create_missing_email(mock_count, mock_context, api_gateway_event):
    response = handler(_event(api_gateway_event, {}), mock_context)
    assert response['statusCode'] == 400
    mock_count.assert_not_called()
