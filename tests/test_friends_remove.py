"""
Tests for friends_remove lambda
"""

import json
import pytest
from unittest.mock import patch
from lambdas.friends_remove.handler import handler


@patch('lambdas.friends_remove.handler.delete_friends')
def test_friends_remove_success(mock_delete, mock_context, authorized_event):
    """Caller from context, target (friendEmail) from query"""
    mock_delete.return_value = True
    event = authorized_event(
        email="user1@example.com",
        httpMethod="DELETE",
        path="/friends/remove",
        queryStringParameters={"friendEmail": "user2@example.com"},
    )

    response = handler(event, mock_context)

    assert response['statusCode'] == 200
    body = json.loads(response['body'])
    assert body['success'] is True
    mock_delete.assert_called_once_with('user1@example.com', 'user2@example.com')


@patch('lambdas.friends_remove.handler.delete_friends')
def test_friends_remove_missing_target(mock_delete, mock_context, authorized_event):
    """Caller in context but no friendEmail -> 400"""
    event = authorized_event(
        email="user1@example.com",
        httpMethod="DELETE",
        path="/friends/remove",
        queryStringParameters={},
    )

    response = handler(event, mock_context)

    assert response['statusCode'] == 400
    mock_delete.assert_not_called()


@patch('lambdas.friends_remove.handler.delete_friends')
def test_friends_remove_missing_caller_identity(mock_delete, mock_context, api_gateway_event):
    """No context, no query email -> 401 (target email present but caller is unresolved)"""
    event = {
        **api_gateway_event,
        "httpMethod": "DELETE",
        "path": "/friends/remove",
        "queryStringParameters": {"friendEmail": "user2@example.com"},
    }

    response = handler(event, mock_context)

    assert response['statusCode'] == 401
    mock_delete.assert_not_called()
