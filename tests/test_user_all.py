"""
Tests for user_all lambda
"""

import json
from unittest.mock import patch

from lambdas.user_all.handler import handler


@patch('lambdas.user_all.handler.full_table_scan')
def test_user_all_no_caller_returns_everyone(mock_scan, mock_context, api_gateway_event):
    """Without an `email` query param, return all users (legacy behavior)."""
    mock_scan.return_value = [
        {"email": "a@test.com", "displayName": "A", "refreshToken": "REDACT-ME"},
        {"email": "b@test.com", "displayName": "B"},
    ]
    event = {
        **api_gateway_event,
        "path": "/user/all",
        "queryStringParameters": None,
    }

    response = handler(event, mock_context)
    body = json.loads(response['body'])

    assert response['statusCode'] == 200
    assert len(body) == 2
    # refreshToken always stripped
    assert all('refreshToken' not in u for u in body)


@patch('lambdas.user_all.handler.full_table_scan')
def test_user_all_filters_caller(mock_scan, mock_context, api_gateway_event):
    """With `?email=caller`, the caller's own row is omitted."""
    mock_scan.return_value = [
        {"email": "me@test.com", "displayName": "Me"},
        {"email": "friend@test.com", "displayName": "Friend"},
    ]
    event = {
        **api_gateway_event,
        "path": "/user/all",
        "queryStringParameters": {"email": "me@test.com"},
    }

    response = handler(event, mock_context)
    body = json.loads(response['body'])

    assert response['statusCode'] == 200
    assert len(body) == 1
    assert body[0]['email'] == "friend@test.com"


@patch('lambdas.user_all.handler.full_table_scan')
def test_user_all_filter_is_case_insensitive(mock_scan, mock_context, api_gateway_event):
    """Email casing shouldn't let the caller slip through."""
    mock_scan.return_value = [
        {"email": "Me@Test.com", "displayName": "Me"},
        {"email": "friend@test.com", "displayName": "Friend"},
    ]
    event = {
        **api_gateway_event,
        "path": "/user/all",
        "queryStringParameters": {"email": "ME@test.com"},
    }

    response = handler(event, mock_context)
    body = json.loads(response['body'])

    assert response['statusCode'] == 200
    assert len(body) == 1
    assert body[0]['email'] == "friend@test.com"
