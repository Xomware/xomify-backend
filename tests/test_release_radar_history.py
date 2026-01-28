"""
Tests for release_radar_history lambda
"""

import pytest
import json
from unittest.mock import patch
from lambdas.release_radar_history.handler import handler


@patch('lambdas.release_radar_history.handler.get_user_release_radar_history')
@patch('lambdas.release_radar_history.handler.get_week_key')
@patch('lambdas.release_radar_history.handler.format_week_display')
def test_release_radar_history_success(mock_format, mock_get_week, mock_get_history, mock_context, api_gateway_event):
    """Test successful release radar history retrieval"""
    # Setup
    mock_get_history.return_value = [
        {'weekKey': '2024-W01', 'trackCount': 10},
        {'weekKey': '2024-W02', 'trackCount': 15}
    ]
    mock_get_week.return_value = '2024-W10'
    mock_format.return_value = 'Week 10, 2024'

    event = {
        **api_gateway_event,
        "httpMethod": "GET",
        "path": "/release-radar/history",
        "queryStringParameters": {"email": "test@example.com"}
    }

    # Execute
    response = handler(event, mock_context)

    # Assert
    assert response['statusCode'] == 200
    body = json.loads(response['body'])
    assert body['count'] == 2
    assert body['email'] == 'test@example.com'


@patch('lambdas.release_radar_history.handler.get_user_release_radar_history')
@patch('lambdas.release_radar_history.handler.get_week_key')
@patch('lambdas.release_radar_history.handler.format_week_display')
def test_release_radar_history_with_limit(mock_format, mock_get_week, mock_get_history, mock_context, api_gateway_event):
    """Test history retrieval with custom limit"""
    # Setup
    mock_get_history.return_value = []
    mock_get_week.return_value = '2024-W10'
    mock_format.return_value = 'Week 10, 2024'

    event = {
        **api_gateway_event,
        "httpMethod": "GET",
        "path": "/release-radar/history",
        "queryStringParameters": {
            "email": "test@example.com",
            "limit": "10"
        }
    }

    # Execute
    response = handler(event, mock_context)

    # Assert
    assert response['statusCode'] == 200
    mock_get_history.assert_called_once_with('test@example.com', limit=10)
