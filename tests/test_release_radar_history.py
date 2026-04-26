"""
Tests for release_radar_history lambda.

Covers caller-identity migration (Track 1g): handler now reads the caller's
email from the trusted authorizer context via `get_caller_email`, with a
query-string fallback retained during the migration window.
"""

import json
from unittest.mock import patch

import pytest

from lambdas.release_radar_history.handler import handler


@patch('lambdas.release_radar_history.handler.get_user_release_radar_history')
@patch('lambdas.release_radar_history.handler.get_week_key')
@patch('lambdas.release_radar_history.handler.format_week_display')
def test_release_radar_history_success_authorized(
    mock_format, mock_get_week, mock_get_history, mock_context, authorized_event
):
    """Caller email comes from authorizer context — no query param needed."""
    mock_get_history.return_value = [
        {'weekKey': '2024-W01', 'trackCount': 10},
        {'weekKey': '2024-W02', 'trackCount': 15},
    ]
    mock_get_week.return_value = '2024-W10'
    mock_format.return_value = 'Week 10, 2024'

    event = authorized_event(
        email='ctx@example.com',
        httpMethod='GET',
        path='/release-radar/history',
    )

    response = handler(event, mock_context)

    assert response['statusCode'] == 200
    body = json.loads(response['body'])
    assert body['count'] == 2
    assert body['email'] == 'ctx@example.com'
    mock_get_history.assert_called_once_with('ctx@example.com', limit=26)


@patch('lambdas.release_radar_history.handler.get_user_release_radar_history')
@patch('lambdas.release_radar_history.handler.get_week_key')
@patch('lambdas.release_radar_history.handler.format_week_display')
def test_release_radar_history_with_limit(
    mock_format, mock_get_week, mock_get_history, mock_context, authorized_event
):
    """`limit` query param is still honored alongside context-sourced email."""
    mock_get_history.return_value = []
    mock_get_week.return_value = '2024-W10'
    mock_format.return_value = 'Week 10, 2024'

    event = authorized_event(
        email='ctx@example.com',
        httpMethod='GET',
        path='/release-radar/history',
        queryStringParameters={'limit': '10'},
    )

    response = handler(event, mock_context)

    assert response['statusCode'] == 200
    mock_get_history.assert_called_once_with('ctx@example.com', limit=10)


@patch('lambdas.release_radar_history.handler.get_user_release_radar_history')
@patch('lambdas.release_radar_history.handler.get_week_key')
@patch('lambdas.release_radar_history.handler.format_week_display')
def test_release_radar_history_legacy_query_fallback(
    mock_format, mock_get_week, mock_get_history, mock_context, legacy_event
):
    """Legacy clients (no per-user JWT) still work via the query-string fallback."""
    mock_get_history.return_value = []
    mock_get_week.return_value = '2024-W10'
    mock_format.return_value = 'Week 10, 2024'

    event = legacy_event(email='legacy@example.com')
    event['httpMethod'] = 'GET'
    event['path'] = '/release-radar/history'

    response = handler(event, mock_context)

    assert response['statusCode'] == 200
    body = json.loads(response['body'])
    assert body['email'] == 'legacy@example.com'
    mock_get_history.assert_called_once_with('legacy@example.com', limit=26)


def test_release_radar_history_missing_identity_returns_401(
    mock_context, legacy_event
):
    """No authorizer context AND no query/body email -> structured 401."""
    event = legacy_event()  # neither context email nor query email
    event['httpMethod'] = 'GET'
    event['path'] = '/release-radar/history'

    response = handler(event, mock_context)

    assert response['statusCode'] == 401
    body = json.loads(response['body'])
    assert body['error']['status'] == 401
