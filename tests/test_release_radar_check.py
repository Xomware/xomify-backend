"""
Tests for release_radar_check lambda.

Covers caller-identity migration (Track 1g): handler reads caller email
from authorizer context, with query-string fallback during the migration
window.
"""

import json
from datetime import date
from unittest.mock import patch

from lambdas.release_radar_check.handler import handler


@patch('lambdas.release_radar_check.handler.get_user_table_data')
@patch('lambdas.release_radar_check.handler.format_week_display')
@patch('lambdas.release_radar_check.handler.get_week_date_range')
@patch('lambdas.release_radar_check.handler.get_week_key')
@patch('lambdas.release_radar_check.handler.check_user_has_history')
def test_release_radar_check_success_authorized(
    mock_has_history,
    mock_week_key,
    mock_week_range,
    mock_week_display,
    mock_user_data,
    mock_context,
    authorized_event,
):
    """Caller email comes from trusted authorizer context."""
    mock_has_history.return_value = True
    mock_week_key.return_value = '2024-W10'
    mock_week_range.return_value = (date(2024, 3, 4), date(2024, 3, 10))
    mock_week_display.return_value = 'Week 10, 2024'
    mock_user_data.return_value = {'activeReleaseRadar': True}

    event = authorized_event(
        email='ctx@example.com',
        httpMethod='GET',
        path='/release-radar/check',
    )

    response = handler(event, mock_context)

    assert response['statusCode'] == 200
    body = json.loads(response['body'])
    assert body['email'] == 'ctx@example.com'
    assert body['enrolled'] is True
    assert body['hasHistory'] is True
    assert body['currentWeek'] == '2024-W10'
    assert body['weekStartDate'] == '2024-03-04'
    assert body['weekEndDate'] == '2024-03-10'
    mock_has_history.assert_called_once_with('ctx@example.com')
    mock_user_data.assert_called_once_with('ctx@example.com')


@patch('lambdas.release_radar_check.handler.get_user_table_data')
@patch('lambdas.release_radar_check.handler.format_week_display')
@patch('lambdas.release_radar_check.handler.get_week_date_range')
@patch('lambdas.release_radar_check.handler.get_week_key')
@patch('lambdas.release_radar_check.handler.check_user_has_history')
def test_release_radar_check_not_enrolled_when_user_missing(
    mock_has_history,
    mock_week_key,
    mock_week_range,
    mock_week_display,
    mock_user_data,
    mock_context,
    authorized_event,
):
    """Missing user record -> enrolled=False (no crash)."""
    mock_has_history.return_value = False
    mock_week_key.return_value = '2024-W10'
    mock_week_range.return_value = (date(2024, 3, 4), date(2024, 3, 10))
    mock_week_display.return_value = 'Week 10, 2024'
    mock_user_data.return_value = None

    event = authorized_event(email='nouser@example.com')

    response = handler(event, mock_context)

    assert response['statusCode'] == 200
    body = json.loads(response['body'])
    assert body['enrolled'] is False
    assert body['hasHistory'] is False


@patch('lambdas.release_radar_check.handler.get_user_table_data')
@patch('lambdas.release_radar_check.handler.format_week_display')
@patch('lambdas.release_radar_check.handler.get_week_date_range')
@patch('lambdas.release_radar_check.handler.get_week_key')
@patch('lambdas.release_radar_check.handler.check_user_has_history')
def test_release_radar_check_legacy_query_fallback(
    mock_has_history,
    mock_week_key,
    mock_week_range,
    mock_week_display,
    mock_user_data,
    mock_context,
    legacy_event,
):
    """Legacy callers (no JWT context) still resolve email via query string."""
    mock_has_history.return_value = False
    mock_week_key.return_value = '2024-W10'
    mock_week_range.return_value = (date(2024, 3, 4), date(2024, 3, 10))
    mock_week_display.return_value = 'Week 10, 2024'
    mock_user_data.return_value = {'activeReleaseRadar': False}

    event = legacy_event(email='legacy@example.com')

    response = handler(event, mock_context)

    assert response['statusCode'] == 200
    body = json.loads(response['body'])
    assert body['email'] == 'legacy@example.com'
    mock_has_history.assert_called_once_with('legacy@example.com')


def test_release_radar_check_missing_identity_returns_401(
    mock_context, legacy_event
):
    """No context email and no query email -> structured 401 from helper."""
    event = legacy_event()

    response = handler(event, mock_context)

    assert response['statusCode'] == 401
    body = json.loads(response['body'])
    assert body['error']['status'] == 401
