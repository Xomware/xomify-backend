"""
Tests for friends_request lambda
"""

import json
import pytest
from unittest.mock import patch
from lambdas.friends_request.handler import handler


@patch('lambdas.friends_request.handler.send_friend_request')
def test_friends_request_success(mock_send_request, mock_context, authorized_event):
    """Caller from context, target (requestEmail) from body"""
    mock_send_request.return_value = True
    event = authorized_event(
        email="user1@example.com",
        httpMethod="POST",
        path="/friends/request",
        body=json.dumps({"requestEmail": "user2@example.com"}),
    )

    response = handler(event, mock_context)

    assert response['statusCode'] == 200
    body = json.loads(response['body'])
    assert body['success'] is True
    mock_send_request.assert_called_once_with('user1@example.com', 'user2@example.com')


@patch('lambdas.friends_request.handler.send_friend_request')
def test_friends_request_failure(mock_send_request, mock_context, authorized_event):
    """Downstream returns False -> success=false but still 200"""
    mock_send_request.return_value = False
    event = authorized_event(
        email="user1@example.com",
        httpMethod="POST",
        path="/friends/request",
        body=json.dumps({"requestEmail": "user2@example.com"}),
    )

    response = handler(event, mock_context)

    assert response['statusCode'] == 200
    body = json.loads(response['body'])
    assert body['success'] is False


@patch('lambdas.friends_request.handler.send_friend_request')
def test_friends_request_missing_target(mock_send_request, mock_context, authorized_event):
    """Caller in context, but no requestEmail in body -> 400 ValidationError"""
    event = authorized_event(
        email="user1@example.com",
        httpMethod="POST",
        path="/friends/request",
        body=json.dumps({}),
    )

    response = handler(event, mock_context)

    assert response['statusCode'] == 400
    mock_send_request.assert_not_called()


@patch('lambdas.friends_request.handler.send_friend_request')
def test_friends_request_missing_caller_identity(mock_send_request, mock_context, api_gateway_event):
    """No authorizer context AND no fallback email -> 401"""
    event = {
        **api_gateway_event,
        "httpMethod": "POST",
        "path": "/friends/request",
        "body": json.dumps({"requestEmail": "user2@example.com"}),
    }

    response = handler(event, mock_context)

    assert response['statusCode'] == 401
    mock_send_request.assert_not_called()


@patch('lambdas.friends_request.handler.send_friend_request')
def test_friends_request_fallback_caller_in_body(mock_send_request, mock_context, legacy_event):
    """Legacy: caller email in body alongside requestEmail still works via fallback"""
    mock_send_request.return_value = True
    event = legacy_event(
        httpMethod="POST",
        path="/friends/request",
        body=json.dumps({
            "email": "user1@example.com",
            "requestEmail": "user2@example.com",
        }),
    )

    response = handler(event, mock_context)

    assert response['statusCode'] == 200
    mock_send_request.assert_called_once_with('user1@example.com', 'user2@example.com')
