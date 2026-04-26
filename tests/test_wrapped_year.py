"""
Tests for wrapped_year (GET /wrapped/year) lambda.
"""

import json
from unittest.mock import patch

from lambdas.wrapped_year.handler import handler


@patch('lambdas.wrapped_year.handler.get_wrapped_year')
def test_wrapped_year_success_via_authorizer_context(
    mock_get, mock_context, authorized_event
):
    """Caller email comes from authorizer; `year` stays in query."""
    mock_get.return_value = [
        {'monthKey': '2024-01'},
        {'monthKey': '2024-02'},
        {'monthKey': '2024-03'},
    ]
    event = authorized_event(
        email="caller@example.com",
        httpMethod="GET",
        path="/wrapped/year",
        queryStringParameters={'year': '2024'},
    )

    response = handler(event, mock_context)

    assert response['statusCode'] == 200
    body = json.loads(response['body'])
    assert body['email'] == 'caller@example.com'
    assert body['year'] == '2024'
    assert body['count'] == 3
    assert len(body['wraps']) == 3
    mock_get.assert_called_once_with("caller@example.com", "2024")


@patch('lambdas.wrapped_year.handler.get_wrapped_year')
def test_wrapped_year_empty(mock_get, mock_context, authorized_event):
    """Empty list still returns 200 with count=0."""
    mock_get.return_value = []
    event = authorized_event(
        httpMethod="GET",
        path="/wrapped/year",
        queryStringParameters={'year': '2099'},
    )

    response = handler(event, mock_context)

    assert response['statusCode'] == 200
    body = json.loads(response['body'])
    assert body['count'] == 0


@patch('lambdas.wrapped_year.handler.get_wrapped_year')
def test_wrapped_year_missing_year(mock_get, mock_context, authorized_event):
    """Missing required `year` -> 400."""
    event = authorized_event(
        httpMethod="GET",
        path="/wrapped/year",
        queryStringParameters={},
    )

    response = handler(event, mock_context)

    assert response['statusCode'] == 400
    mock_get.assert_not_called()


@patch('lambdas.wrapped_year.handler.get_wrapped_year')
def test_wrapped_year_missing_caller_identity(
    mock_get, mock_context, legacy_event
):
    """No authorizer context, no query/body email -> 401."""
    event = legacy_event()
    event['queryStringParameters'] = {'year': '2024'}

    response = handler(event, mock_context)

    assert response['statusCode'] == 401
    mock_get.assert_not_called()
