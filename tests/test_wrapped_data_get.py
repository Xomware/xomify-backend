"""
Tests for wrapped_data_get lambda
"""

import pytest
import json
from unittest.mock import patch
from lambdas.wrapped_all.handler import handler


@patch('lambdas.wrapped_all.handler.get_wrapped_data')
def test_wrapped_data_get_success(mock_get_wrapped, mock_context, api_gateway_event):
    """Test successful wrapped data retrieval"""
    # Setup
    mock_get_wrapped.return_value = {
        'active': True,
        'activeWrapped': True,
        'activeReleaseRadar': False,
        'wraps': [
            {'monthKey': '2024-01', 'trackCount': 25},
            {'monthKey': '2024-02', 'trackCount': 30}
        ]
    }
    event = {
        **api_gateway_event,
        "httpMethod": "GET",
        "path": "/wrapped/data",
        "queryStringParameters": {"email": "test@example.com"}
    }

    # Execute
    response = handler(event, mock_context)

    # Assert
    assert response['statusCode'] == 200
    body = json.loads(response['body'])
    assert body['active'] is True
    assert body['activeWrapped'] is True
    assert len(body['wraps']) == 2


@patch('lambdas.wrapped_all.handler.get_wrapped_data')
def test_wrapped_data_get_no_history(mock_get_wrapped, mock_context, api_gateway_event):
    """Test user with no wrapped history"""
    # Setup
    mock_get_wrapped.return_value = {
        'active': True,
        'activeWrapped': True,
        'activeReleaseRadar': False,
        'wraps': []
    }
    event = {
        **api_gateway_event,
        "httpMethod": "GET",
        "path": "/wrapped/data",
        "queryStringParameters": {"email": "test@example.com"}
    }

    # Execute
    response = handler(event, mock_context)

    # Assert
    assert response['statusCode'] == 200
    body = json.loads(response['body'])
    assert len(body['wraps']) == 0


@patch('lambdas.wrapped_all.handler.get_wrapped_data')
def test_wrapped_data_get_missing_email(mock_get_wrapped, mock_context, api_gateway_event):
    """Test missing email parameter"""
    # Setup
    event = {
        **api_gateway_event,
        "httpMethod": "GET",
        "path": "/wrapped/data",
        "queryStringParameters": {}
    }

    # Execute
    response = handler(event, mock_context)

    # Assert
    assert response['statusCode'] == 400
