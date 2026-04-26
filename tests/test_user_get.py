"""
Tests for user_data lambda
"""

import json
from unittest.mock import patch

from lambdas.user_data.handler import handler


@patch('lambdas.user_data.handler.get_user_table_data')
def test_user_get_via_context(mock_get_user, mock_context, authorized_event, sample_user):
    """Trusted authorizer context populates the caller email."""
    mock_get_user.return_value = sample_user
    event = authorized_event(
        email="test@example.com",
        httpMethod="GET",
        path="/user/user-table",
    )

    response = handler(event, mock_context)

    assert response['statusCode'] == 200
    mock_get_user.assert_called_once_with('test@example.com')


@patch('lambdas.user_data.handler.get_user_table_data')
def test_user_get_via_query_fallback(mock_get_user, mock_context, legacy_event, sample_user):
    """Legacy `?email=` callers still resolve during the migration window."""
    mock_get_user.return_value = sample_user
    event = legacy_event(
        email="legacy@example.com",
        httpMethod="GET",
        path="/user/user-table",
    )

    response = handler(event, mock_context)

    assert response['statusCode'] == 200
    mock_get_user.assert_called_once_with('legacy@example.com')


@patch('lambdas.user_data.handler.get_user_table_data')
def test_user_get_missing_caller_identity_returns_401(
    mock_get_user, mock_context, api_gateway_event,
):
    """No context, no fallback: helper raises a structured 401."""
    event = {
        **api_gateway_event,
        "httpMethod": "GET",
        "path": "/user/user-table",
        "queryStringParameters": {},
    }

    response = handler(event, mock_context)

    assert response['statusCode'] == 401
    body = json.loads(response['body'])
    assert body['error']['field'] == 'email'
    mock_get_user.assert_not_called()


@patch('lambdas.user_data.handler.get_user_table_data')
def test_user_get_dynamo_failure_propagates_as_500(
    mock_get_user, mock_context, authorized_event,
):
    """Underlying retrieval errors surface as a 500 via the error decorator."""
    mock_get_user.side_effect = Exception("User not found")
    event = authorized_event(
        email="notfound@example.com",
        httpMethod="GET",
        path="/user/user-table",
    )

    response = handler(event, mock_context)

    assert response['statusCode'] == 500
