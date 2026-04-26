"""
Tests for wrapped_month (GET /wrapped/month) lambda.
"""

import json
from unittest.mock import patch

from lambdas.wrapped_month.handler import handler


@patch('lambdas.wrapped_month.handler.get_wrapped_month')
def test_wrapped_month_success_via_authorizer_context(
    mock_get, mock_context, authorized_event
):
    """Caller email comes from authorizer; `monthKey` stays in query."""
    mock_get.return_value = {'monthKey': '2024-03', 'trackCount': 42}
    event = authorized_event(
        email="caller@example.com",
        httpMethod="GET",
        path="/wrapped/month",
        queryStringParameters={'monthKey': '2024-03'},
    )

    response = handler(event, mock_context)

    assert response['statusCode'] == 200
    body = json.loads(response['body'])
    assert body['monthKey'] == '2024-03'
    mock_get.assert_called_once_with("caller@example.com", "2024-03")


@patch('lambdas.wrapped_month.handler.get_wrapped_month')
def test_wrapped_month_not_found(mock_get, mock_context, authorized_event):
    """Missing wrap data -> 404."""
    mock_get.return_value = None
    event = authorized_event(
        httpMethod="GET",
        path="/wrapped/month",
        queryStringParameters={'monthKey': '1999-12'},
    )

    response = handler(event, mock_context)

    assert response['statusCode'] == 404


@patch('lambdas.wrapped_month.handler.get_wrapped_month')
def test_wrapped_month_missing_month_key(mock_get, mock_context, authorized_event):
    """Missing required `monthKey` -> 400."""
    event = authorized_event(
        httpMethod="GET",
        path="/wrapped/month",
        queryStringParameters={},
    )

    response = handler(event, mock_context)

    assert response['statusCode'] == 400
    mock_get.assert_not_called()


@patch('lambdas.wrapped_month.handler.get_wrapped_month')
def test_wrapped_month_missing_caller_identity(
    mock_get, mock_context, legacy_event
):
    """No authorizer context, no query/body email -> 401."""
    event = legacy_event()
    event['queryStringParameters'] = {'monthKey': '2024-03'}

    response = handler(event, mock_context)

    assert response['statusCode'] == 401
    mock_get.assert_not_called()
