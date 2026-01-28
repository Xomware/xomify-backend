"""
Tests for friends_list lambda
"""

import pytest
from unittest.mock import patch, MagicMock
from lambdas.friends_list.handler import handler


@patch('lambdas.friends_list.handler.list_all_friends_for_user')
def test_friends_list_success(mock_list_friends, mock_context, api_gateway_event):
    """Test successful friends list retrieval"""
    # Setup
    mock_list_friends.return_value = [
        {"email": "friend1@test.com", "status": "accepted", "direction": "outgoing"},
        {"email": "friend2@test.com", "status": "pending", "direction": "incoming"},
        {"email": "friend3@test.com", "status": "pending", "direction": "outgoing"},
    ]
    event = {
        **api_gateway_event,
        "httpMethod": "GET",
        "path": "/friends/list",
        "queryStringParameters": {"email": "test@example.com"}
    }

    # Execute
    response = handler(event, mock_context)

    # Assert
    assert response['statusCode'] == 200
    import json
    body = json.loads(response['body'])
    assert body['acceptedCount'] == 1
    assert body['pendingCount'] == 1
    assert body['requestedCount'] == 1
    assert body['totalCount'] == 3


@patch('lambdas.friends_list.handler.list_all_friends_for_user')
def test_friends_list_empty(mock_list_friends, mock_context, api_gateway_event):
    """Test empty friends list"""
    # Setup
    mock_list_friends.return_value = []
    event = {
        **api_gateway_event,
        "httpMethod": "GET",
        "path": "/friends/list",
        "queryStringParameters": {"email": "test@example.com"}
    }

    # Execute
    response = handler(event, mock_context)

    # Assert
    assert response['statusCode'] == 200
    import json
    body = json.loads(response['body'])
    assert body['totalCount'] == 0
    assert body['acceptedCount'] == 0


@patch('lambdas.friends_list.handler.list_all_friends_for_user')
def test_friends_list_missing_email(mock_list_friends, mock_context, api_gateway_event):
    """Test missing email parameter"""
    # Setup
    event = {
        **api_gateway_event,
        "httpMethod": "GET",
        "path": "/friends/list",
        "queryStringParameters": {}
    }

    # Execute
    response = handler(event, mock_context)

    # Assert
    assert response['statusCode'] == 400
