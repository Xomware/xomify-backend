"""
Tests for friends_request lambda
"""

import pytest
import json
from unittest.mock import patch
from lambdas.friends_request.handler import handler


@patch('lambdas.friends_request.handler.send_friend_request')
def test_friends_request_success(mock_send_request, mock_context, api_gateway_event):
    """Test successful friend request"""
    # Setup
    mock_send_request.return_value = True
    event = {
        **api_gateway_event,
        "httpMethod": "POST",
        "path": "/friends/request",
        "body": json.dumps({
            "email": "user1@example.com",
            "requestEmail": "user2@example.com"
        })
    }

    # Execute
    response = handler(event, mock_context)

    # Assert
    assert response['statusCode'] == 200
    body = json.loads(response['body'])
    assert body['success'] is True
    mock_send_request.assert_called_once_with('user1@example.com', 'user2@example.com')


@patch('lambdas.friends_request.handler.send_friend_request')
def test_friends_request_failure(mock_send_request, mock_context, api_gateway_event):
    """Test failed friend request"""
    # Setup
    mock_send_request.return_value = False
    event = {
        **api_gateway_event,
        "httpMethod": "POST",
        "path": "/friends/request",
        "body": json.dumps({
            "email": "user1@example.com",
            "requestEmail": "user2@example.com"
        })
    }

    # Execute
    response = handler(event, mock_context)

    # Assert
    assert response['statusCode'] == 200
    body = json.loads(response['body'])
    assert body['success'] is False


@patch('lambdas.friends_request.handler.send_friend_request')
def test_friends_request_missing_fields(mock_send_request, mock_context, api_gateway_event):
    """Test missing required fields"""
    # Setup
    event = {
        **api_gateway_event,
        "httpMethod": "POST",
        "path": "/friends/request",
        "body": json.dumps({"email": "user1@example.com"})
    }

    # Execute
    response = handler(event, mock_context)

    # Assert
    assert response['statusCode'] == 400
