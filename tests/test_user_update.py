"""
Tests for user_update lambda
"""

import pytest
import json
from unittest.mock import patch
from lambdas.user_update.handler import handler


@patch('lambdas.user_update.handler.update_user_table_refresh_token')
def test_user_update_refresh_token(mock_update_token, mock_context, api_gateway_event):
    """Test updating refresh token"""
    # Setup
    mock_update_token.return_value = {
        'email': 'test@example.com',
        'userId': 'spotify123',
        'updated': True
    }
    event = {
        **api_gateway_event,
        "httpMethod": "POST",
        "path": "/user/user-table",
        "body": json.dumps({
            "email": "test@example.com",
            "userId": "spotify123",
            "displayName": "Test User",
            "refreshToken": "new-token",
            "avatar": "https://example.com/avatar.jpg"
        })
    }

    # Execute
    response = handler(event, mock_context)

    # Assert
    assert response['statusCode'] == 200
    mock_update_token.assert_called_once()


@patch('lambdas.user_update.handler.update_user_table_enrollments')
def test_user_update_enrollments(mock_update_enrollments, mock_context, api_gateway_event):
    """Test updating enrollment status"""
    # Setup
    mock_update_enrollments.return_value = {
        'email': 'test@example.com',
        'wrappedEnrolled': True,
        'releaseRadarEnrolled': False
    }
    event = {
        **api_gateway_event,
        "httpMethod": "POST",
        "path": "/user/user-table",
        "body": json.dumps({
            "email": "test@example.com",
            "wrappedEnrolled": True,
            "releaseRadarEnrolled": False
        })
    }

    # Execute
    response = handler(event, mock_context)

    # Assert
    assert response['statusCode'] == 200
    mock_update_enrollments.assert_called_once_with('test@example.com', True, False)


@patch('lambdas.user_update.handler.update_user_table_refresh_token')
def test_user_update_invalid_request(mock_update_token, mock_context, api_gateway_event):
    """Test invalid update request"""
    # Setup
    event = {
        **api_gateway_event,
        "httpMethod": "POST",
        "path": "/user/user-table",
        "body": json.dumps({
            "email": "test@example.com"
            # Missing both token and enrollment fields
        })
    }

    # Execute
    response = handler(event, mock_context)

    # Assert
    assert response['statusCode'] == 400
