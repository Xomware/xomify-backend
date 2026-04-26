"""
Tests for friends_accept lambda
"""

import json
import pytest
from unittest.mock import patch
from lambdas.friends_accept.handler import handler


@patch('lambdas.friends_accept.handler.accept_friend_request')
def test_friends_accept_success(mock_accept, mock_context, authorized_event):
    """Caller from context, target (requestEmail) from body"""
    mock_accept.return_value = True
    event = authorized_event(
        email="user1@example.com",
        httpMethod="POST",
        path="/friends/accept",
        body=json.dumps({"requestEmail": "user2@example.com"}),
    )

    response = handler(event, mock_context)

    assert response['statusCode'] == 200
    body = json.loads(response['body'])
    assert body['success'] is True
    mock_accept.assert_called_once_with('user1@example.com', 'user2@example.com')


@patch('lambdas.friends_accept.handler.accept_friend_request')
def test_friends_accept_missing_target(mock_accept, mock_context, authorized_event):
    """Caller in context but no requestEmail -> 400"""
    event = authorized_event(
        email="user1@example.com",
        httpMethod="POST",
        path="/friends/accept",
        body=json.dumps({}),
    )

    response = handler(event, mock_context)

    assert response['statusCode'] == 400
    mock_accept.assert_not_called()


@patch('lambdas.friends_accept.handler.accept_friend_request')
def test_friends_accept_missing_caller_identity(mock_accept, mock_context, api_gateway_event):
    """No context, no body email -> 401"""
    event = {
        **api_gateway_event,
        "httpMethod": "POST",
        "path": "/friends/accept",
        "body": json.dumps({"requestEmail": "user2@example.com"}),
    }

    response = handler(event, mock_context)

    assert response['statusCode'] == 401
    mock_accept.assert_not_called()
