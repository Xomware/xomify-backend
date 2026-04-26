"""
Tests for friends_pending lambda
"""

import json
import pytest
from unittest.mock import patch
from lambdas.friends_pending.handler import handler


@patch('lambdas.friends_pending.handler.list_all_friends_for_user')
def test_friends_pending_success(mock_list_friends, mock_context, authorized_event):
    """Caller from context, returns only pending rows"""
    mock_list_friends.return_value = [
        {"email": "f1@x.com", "status": "pending"},
        {"email": "f2@x.com", "status": "accepted"},
        {"email": "f3@x.com", "status": "pending"},
    ]
    event = authorized_event(
        email="test@example.com",
        httpMethod="GET",
        path="/friends/pending",
    )

    response = handler(event, mock_context)

    assert response['statusCode'] == 200
    body = json.loads(response['body'])
    assert body['email'] == 'test@example.com'
    assert body['pendingCount'] == 2
    assert len(body['pending']) == 2
    mock_list_friends.assert_called_once_with('test@example.com')


@patch('lambdas.friends_pending.handler.list_all_friends_for_user')
def test_friends_pending_empty(mock_list_friends, mock_context, authorized_event):
    """No friends -> empty pending list"""
    mock_list_friends.return_value = []
    event = authorized_event(
        email="test@example.com",
        httpMethod="GET",
        path="/friends/pending",
    )

    response = handler(event, mock_context)

    assert response['statusCode'] == 200
    body = json.loads(response['body'])
    assert body['pendingCount'] == 0
    assert body['pending'] == []


@patch('lambdas.friends_pending.handler.list_all_friends_for_user')
def test_friends_pending_missing_caller_identity(mock_list_friends, mock_context, api_gateway_event):
    """No authorizer context AND no fallback email -> 401"""
    event = {
        **api_gateway_event,
        "httpMethod": "GET",
        "path": "/friends/pending",
        "queryStringParameters": {},
    }

    response = handler(event, mock_context)

    assert response['statusCode'] == 401
    mock_list_friends.assert_not_called()
