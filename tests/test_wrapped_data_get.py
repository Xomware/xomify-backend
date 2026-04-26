"""
Tests for wrapped_all (GET /wrapped/all) lambda.
"""

import json
from unittest.mock import patch

from lambdas.wrapped_all.handler import handler


@patch('lambdas.wrapped_all.handler.get_wrapped_data')
def test_wrapped_all_success_via_authorizer_context(
    mock_get_wrapped, mock_context, authorized_event
):
    """Caller email is read from `requestContext.authorizer` (no query param)."""
    mock_get_wrapped.return_value = {
        'active': True,
        'activeWrapped': True,
        'activeReleaseRadar': False,
        'wraps': [
            {'monthKey': '2024-01', 'trackCount': 25},
            {'monthKey': '2024-02', 'trackCount': 30},
        ],
    }
    event = authorized_event(
        email="caller@example.com",
        httpMethod="GET",
        path="/wrapped/all",
    )

    response = handler(event, mock_context)

    assert response['statusCode'] == 200
    body = json.loads(response['body'])
    assert body['active'] is True
    assert body['activeWrapped'] is True
    assert len(body['wraps']) == 2
    mock_get_wrapped.assert_called_once_with("caller@example.com")


@patch('lambdas.wrapped_all.handler.get_wrapped_data')
def test_wrapped_all_no_history(mock_get_wrapped, mock_context, authorized_event):
    """Empty wraps list still returns 200."""
    mock_get_wrapped.return_value = {
        'active': True,
        'activeWrapped': True,
        'activeReleaseRadar': False,
        'wraps': [],
    }
    event = authorized_event(httpMethod="GET", path="/wrapped/all")

    response = handler(event, mock_context)

    assert response['statusCode'] == 200
    body = json.loads(response['body'])
    assert body['wraps'] == []


@patch('lambdas.wrapped_all.handler.get_wrapped_data')
def test_wrapped_all_legacy_query_fallback(
    mock_get_wrapped, mock_context, legacy_event
):
    """During the migration window, a query-string `email` is still accepted."""
    mock_get_wrapped.return_value = {'wraps': []}
    event = legacy_event(email="legacy@example.com")
    event['httpMethod'] = "GET"
    event['path'] = "/wrapped/all"

    response = handler(event, mock_context)

    assert response['statusCode'] == 200
    mock_get_wrapped.assert_called_once_with("legacy@example.com")


@patch('lambdas.wrapped_all.handler.get_wrapped_data')
def test_wrapped_all_missing_caller_identity(
    mock_get_wrapped, mock_context, legacy_event
):
    """No authorizer context AND no query/body email -> 401."""
    event = legacy_event()  # no email anywhere

    response = handler(event, mock_context)

    assert response['statusCode'] == 401
    body = json.loads(response['body'])
    assert 'email' in body['error']['message']
    mock_get_wrapped.assert_not_called()
