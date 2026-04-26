"""
Tests for user_all lambda
"""

import json
from unittest.mock import patch

from lambdas.user_all.handler import handler


@patch('lambdas.user_all.handler.full_table_scan')
def test_user_all_anonymous_returns_everyone(mock_scan, mock_context, api_gateway_event):
    """Without any caller identity (no context, no fallback), return all users."""
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
def test_user_all_filters_caller_via_context(mock_scan, mock_context, authorized_event):
    """Trusted authorizer context: caller's own row is filtered out."""
    mock_scan.return_value = [
        {"email": "me@test.com", "displayName": "Me"},
        {"email": "friend@test.com", "displayName": "Friend"},
    ]
    event = authorized_event(email="me@test.com", path="/user/all")

    response = handler(event, mock_context)
    body = json.loads(response['body'])

    assert response['statusCode'] == 200
    assert len(body) == 1
    assert body[0]['email'] == "friend@test.com"


@patch('lambdas.user_all.handler.full_table_scan')
def test_user_all_filters_caller_via_query_fallback(mock_scan, mock_context, legacy_event):
    """Legacy `?email=` fallback still filters caller (migration window)."""
    mock_scan.return_value = [
        {"email": "me@test.com", "displayName": "Me"},
        {"email": "friend@test.com", "displayName": "Friend"},
    ]
    event = legacy_event(email="me@test.com", path="/user/all")

    response = handler(event, mock_context)
    body = json.loads(response['body'])

    assert response['statusCode'] == 200
    assert len(body) == 1
    assert body[0]['email'] == "friend@test.com"


@patch('lambdas.user_all.handler.full_table_scan')
def test_user_all_filter_is_case_insensitive(mock_scan, mock_context, authorized_event):
    """Email casing in context shouldn't let the caller slip through."""
    mock_scan.return_value = [
        {"email": "Me@Test.com", "displayName": "Me"},
        {"email": "friend@test.com", "displayName": "Friend"},
    ]
    event = authorized_event(email="ME@test.com", path="/user/all")

    response = handler(event, mock_context)
    body = json.loads(response['body'])

    assert response['statusCode'] == 200
    assert len(body) == 1
    assert body[0]['email'] == "friend@test.com"
