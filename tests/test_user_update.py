"""
Tests for user_update lambda
"""

import json
from unittest.mock import patch

from lambdas.user_update.handler import handler


@patch('lambdas.user_update.handler.update_user_table_refresh_token')
def test_user_update_refresh_token_via_context(
    mock_update_token, mock_context, authorized_event,
):
    """Token-persistence path with caller identity from authorizer context."""
    mock_update_token.return_value = {
        'email': 'test@example.com',
        'userId': 'spotify123',
        'updated': True,
    }
    event = authorized_event(
        email="test@example.com",
        user_id="spotify123",
        httpMethod="POST",
        path="/user/user-table",
        body=json.dumps({
            "displayName": "Test User",
            "refreshToken": "new-token",
            "avatar": "https://example.com/avatar.jpg",
        }),
    )

    response = handler(event, mock_context)

    assert response['statusCode'] == 200
    mock_update_token.assert_called_once_with(
        'test@example.com',
        'spotify123',
        'Test User',
        'new-token',
        'https://example.com/avatar.jpg',
    )


@patch('lambdas.user_update.handler.update_user_table_refresh_token')
def test_user_update_refresh_token_via_body_fallback(
    mock_update_token, mock_context, legacy_event,
):
    """Legacy callers (no context) still send email/userId in the body."""
    mock_update_token.return_value = {'email': 'legacy@example.com', 'updated': True}
    event = legacy_event(
        httpMethod="POST",
        path="/user/user-table",
        body=json.dumps({
            "email": "legacy@example.com",
            "userId": "spotifyLegacy",
            "displayName": "Legacy User",
            "refreshToken": "legacy-token",
            "avatar": "https://example.com/legacy.jpg",
        }),
    )

    response = handler(event, mock_context)

    assert response['statusCode'] == 200
    mock_update_token.assert_called_once_with(
        'legacy@example.com',
        'spotifyLegacy',
        'Legacy User',
        'legacy-token',
        'https://example.com/legacy.jpg',
    )


@patch('lambdas.user_update.handler.update_user_table_refresh_token')
def test_user_update_refresh_token_missing_profile_field_is_400(
    mock_update_token, mock_context, authorized_event,
):
    """Profile fields (displayName/refreshToken/avatar) are still required."""
    event = authorized_event(
        httpMethod="POST",
        path="/user/user-table",
        body=json.dumps({
            "refreshToken": "new-token",
            # displayName + avatar omitted
        }),
    )

    response = handler(event, mock_context)

    assert response['statusCode'] == 400
    mock_update_token.assert_not_called()


@patch('lambdas.user_update.handler.update_user_table_enrollments')
def test_user_update_enrollments_via_context(
    mock_update_enrollments, mock_context, authorized_event,
):
    """Enrollment path uses caller email from authorizer context."""
    mock_update_enrollments.return_value = {
        'email': 'test@example.com',
        'wrappedEnrolled': True,
        'releaseRadarEnrolled': False,
    }
    event = authorized_event(
        email="test@example.com",
        httpMethod="POST",
        path="/user/user-table",
        body=json.dumps({
            "wrappedEnrolled": True,
            "releaseRadarEnrolled": False,
        }),
    )

    response = handler(event, mock_context)

    assert response['statusCode'] == 200
    mock_update_enrollments.assert_called_once_with('test@example.com', True, False)


@patch('lambdas.user_update.handler.update_user_table_refresh_token')
def test_user_update_invalid_request_returns_400(
    mock_update_token, mock_context, authorized_event,
):
    """Body with neither token nor enrollment fields is a 400."""
    event = authorized_event(
        httpMethod="POST",
        path="/user/user-table",
        body=json.dumps({}),
    )

    response = handler(event, mock_context)

    assert response['statusCode'] == 400


@patch('lambdas.user_update.handler.update_user_table_refresh_token')
def test_user_update_missing_caller_identity_returns_401(
    mock_update_token, mock_context, api_gateway_event,
):
    """No context, no body fallback for caller email: structured 401."""
    event = {
        **api_gateway_event,
        "httpMethod": "POST",
        "path": "/user/user-table",
        "body": json.dumps({
            "displayName": "X",
            "refreshToken": "Y",
            "avatar": "Z",
        }),
    }

    response = handler(event, mock_context)

    assert response['statusCode'] == 401
    body = json.loads(response['body'])
    assert body['error']['field'] == 'email'
    mock_update_token.assert_not_called()


@patch('lambdas.user_update.handler.update_user_table_refresh_token')
def test_user_update_token_path_missing_user_id_returns_401(
    mock_update_token, mock_context, legacy_event,
):
    """Body has email but no userId: helper raises 401 on userId resolution."""
    event = legacy_event(
        email="legacy@example.com",
        httpMethod="POST",
        path="/user/user-table",
        body=json.dumps({
            "email": "legacy@example.com",
            # userId omitted
            "displayName": "X",
            "refreshToken": "Y",
            "avatar": "Z",
        }),
    )

    response = handler(event, mock_context)

    assert response['statusCode'] == 401
    body = json.loads(response['body'])
    assert body['error']['field'] == 'userId'
    mock_update_token.assert_not_called()
