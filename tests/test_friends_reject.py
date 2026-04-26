"""
Tests for friends_reject lambda
"""

import json
import pytest
from unittest.mock import patch
from lambdas.friends_reject.handler import handler


@patch('lambdas.friends_reject.handler.delete_friends')
def test_friends_reject_success(mock_delete, mock_context, authorized_event):
    """Caller from context, target (requestEmail) from body"""
    mock_delete.return_value = True
    event = authorized_event(
        email="user1@example.com",
        httpMethod="POST",
        path="/friends/reject",
        body=json.dumps({"requestEmail": "user2@example.com"}),
    )

    response = handler(event, mock_context)

    assert response['statusCode'] == 200
    body = json.loads(response['body'])
    assert body['success'] is True
    mock_delete.assert_called_once_with('user1@example.com', 'user2@example.com')


@patch('lambdas.friends_reject.handler.delete_friends')
def test_friends_reject_missing_target(mock_delete, mock_context, authorized_event):
    """Caller in context but no requestEmail -> 400"""
    event = authorized_event(
        email="user1@example.com",
        httpMethod="POST",
        path="/friends/reject",
        body=json.dumps({}),
    )

    response = handler(event, mock_context)

    assert response['statusCode'] == 400
    mock_delete.assert_not_called()


@patch('lambdas.friends_reject.handler.delete_friends')
def test_friends_reject_missing_caller_identity(mock_delete, mock_context, api_gateway_event):
    """No context, no body email -> 401"""
    event = {
        **api_gateway_event,
        "httpMethod": "POST",
        "path": "/friends/reject",
        "body": json.dumps({"requestEmail": "user2@example.com"}),
    }

    response = handler(event, mock_context)

    assert response['statusCode'] == 401
    mock_delete.assert_not_called()
