"""
Tests for user_get lambda
"""

import pytest
from unittest.mock import patch, MagicMock
from lambdas.user_get.handler import handler


@patch('lambdas.user_get.handler.get_user_table_data')
def test_user_get_success(mock_get_user, mock_context, api_gateway_event, sample_user):
    """Test successful user retrieval"""
    # Setup
    mock_get_user.return_value = sample_user
    event = {
        **api_gateway_event,
        "httpMethod": "GET",
        "path": "/user/user-table",
        "queryStringParameters": {"email": "test@example.com"}
    }

    # Execute
    response = handler(event, mock_context)

    # Assert
    assert response['statusCode'] == 200
    mock_get_user.assert_called_once_with('test@example.com')


@patch('lambdas.user_get.handler.get_user_table_data')
def test_user_get_missing_email(mock_get_user, mock_context, api_gateway_event):
    """Test missing email parameter"""
    # Setup
    event = {
        **api_gateway_event,
        "httpMethod": "GET",
        "path": "/user/user-table",
        "queryStringParameters": {}
    }

    # Execute
    response = handler(event, mock_context)

    # Assert
    assert response['statusCode'] == 400
    assert 'error' in response['body'].lower()


@patch('lambdas.user_get.handler.get_user_table_data')
def test_user_get_not_found(mock_get_user, mock_context, api_gateway_event):
    """Test user not found"""
    # Setup
    mock_get_user.side_effect = Exception("User not found")
    event = {
        **api_gateway_event,
        "httpMethod": "GET",
        "path": "/user/user-table",
        "queryStringParameters": {"email": "notfound@example.com"}
    }

    # Execute
    response = handler(event, mock_context)

    # Assert
    assert response['statusCode'] == 500
