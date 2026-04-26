"""
Tests for friends_list lambda
"""

import json
import pytest
from unittest.mock import patch
from lambdas.friends_list.handler import handler


@patch('lambdas.friends_list.handler.list_all_friends_for_user')
def test_friends_list_success(mock_list_friends, mock_context, authorized_event):
    """Test successful friends list retrieval (caller from authorizer context)"""
    # Setup
    mock_list_friends.return_value = [
        {"email": "friend1@test.com", "status": "accepted", "direction": "outgoing"},
        {"email": "friend2@test.com", "status": "pending", "direction": "incoming"},
        {"email": "friend3@test.com", "status": "pending", "direction": "outgoing"},
    ]
    event = authorized_event(
        email="test@example.com",
        httpMethod="GET",
        path="/friends/list",
    )

    # Execute
    response = handler(event, mock_context)

    # Assert
    assert response['statusCode'] == 200
    body = json.loads(response['body'])
    assert body['email'] == 'test@example.com'
    assert body['acceptedCount'] == 1
    assert body['pendingCount'] == 1
    assert body['requestedCount'] == 1
    assert body['totalCount'] == 3
    mock_list_friends.assert_called_once_with('test@example.com')


@patch('lambdas.friends_list.handler.list_all_friends_for_user')
def test_friends_list_empty(mock_list_friends, mock_context, authorized_event):
    """Test empty friends list"""
    # Setup
    mock_list_friends.return_value = []
    event = authorized_event(
        email="test@example.com",
        httpMethod="GET",
        path="/friends/list",
    )

    # Execute
    response = handler(event, mock_context)

    # Assert
    assert response['statusCode'] == 200
    body = json.loads(response['body'])
    assert body['totalCount'] == 0
    assert body['acceptedCount'] == 0


@patch('lambdas.friends_list.handler.list_all_friends_for_user')
def test_friends_list_missing_caller_identity(mock_list_friends, mock_context, api_gateway_event):
    """No authorizer context AND no fallback email -> 401"""
    event = {
        **api_gateway_event,
        "httpMethod": "GET",
        "path": "/friends/list",
        "queryStringParameters": {},
    }

    response = handler(event, mock_context)

    assert response['statusCode'] == 401
    body = json.loads(response['body'])
    assert body['error']['field'] == 'email'
    mock_list_friends.assert_not_called()


@patch('lambdas.friends_list.handler.list_all_friends_for_user')
def test_friends_list_fallback_to_query(mock_list_friends, mock_context, legacy_event):
    """Legacy callers (no authorizer context) still resolve via query fallback"""
    mock_list_friends.return_value = []
    event = legacy_event(
        email="legacy@example.com",
        httpMethod="GET",
        path="/friends/list",
    )

    response = handler(event, mock_context)

    assert response['statusCode'] == 200
    body = json.loads(response['body'])
    assert body['email'] == 'legacy@example.com'
    mock_list_friends.assert_called_once_with('legacy@example.com')
