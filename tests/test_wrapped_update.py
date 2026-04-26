"""
Tests for wrapped_update (POST /wrapped/update) lambda.
"""

import json
from unittest.mock import patch

from lambdas.wrapped_update.handler import handler


def _body(**overrides) -> str:
    payload = {
        'userId': 'spotify123',
        'refreshToken': 'mock-refresh-token',
        'active': True,
    }
    payload.update(overrides)
    return json.dumps(payload)


@patch('lambdas.wrapped_update.handler.update_wrapped_data')
def test_wrapped_update_success_via_authorizer_context(
    mock_update, mock_context, authorized_event
):
    """Caller email comes from authorizer; other body fields stay."""
    mock_update.return_value = 'User opted into Monthly Wrapped successfully.'
    event = authorized_event(
        email="caller@example.com",
        httpMethod="POST",
        path="/wrapped/update",
        body=_body(),
    )

    response = handler(event, mock_context)

    assert response['statusCode'] == 200
    body = json.loads(response['body'])
    assert 'message' in body
    # update_wrapped_data is called with a dict whose `email` is the caller,
    # plus the other payload fields untouched.
    mock_update.assert_called_once()
    persisted_data = mock_update.call_args[0][0]
    assert persisted_data['email'] == 'caller@example.com'
    assert persisted_data['userId'] == 'spotify123'
    assert persisted_data['refreshToken'] == 'mock-refresh-token'
    assert persisted_data['active'] is True


@patch('lambdas.wrapped_update.handler.update_wrapped_data')
def test_wrapped_update_authorizer_overrides_body_email(
    mock_update, mock_context, authorized_event
):
    """If the client sends an `email` in the body, the trusted caller value wins."""
    mock_update.return_value = 'ok'
    event = authorized_event(
        email="trusted@example.com",
        httpMethod="POST",
        path="/wrapped/update",
        body=_body(email="spoofed@example.com"),
    )

    response = handler(event, mock_context)

    assert response['statusCode'] == 200
    persisted_data = mock_update.call_args[0][0]
    assert persisted_data['email'] == 'trusted@example.com'


@patch('lambdas.wrapped_update.handler.update_wrapped_data')
def test_wrapped_update_legacy_body_fallback(
    mock_update, mock_context, legacy_event
):
    """Legacy clients can still send `email` in the POST body during migration."""
    mock_update.return_value = 'ok'
    event = legacy_event()
    event['httpMethod'] = "POST"
    event['path'] = "/wrapped/update"
    event['body'] = _body(email="legacy@example.com")

    response = handler(event, mock_context)

    assert response['statusCode'] == 200
    persisted_data = mock_update.call_args[0][0]
    assert persisted_data['email'] == 'legacy@example.com'


@patch('lambdas.wrapped_update.handler.update_wrapped_data')
def test_wrapped_update_missing_required_body_field(
    mock_update, mock_context, authorized_event
):
    """Missing `userId` -> 400."""
    event = authorized_event(
        httpMethod="POST",
        path="/wrapped/update",
        body=json.dumps({
            'refreshToken': 'mock-refresh-token',
            'active': True,
        }),
    )

    response = handler(event, mock_context)

    assert response['statusCode'] == 400
    mock_update.assert_not_called()


@patch('lambdas.wrapped_update.handler.update_wrapped_data')
def test_wrapped_update_missing_caller_identity(
    mock_update, mock_context, legacy_event
):
    """No authorizer context AND no fallback `email` -> 401."""
    event = legacy_event()
    event['httpMethod'] = "POST"
    event['path'] = "/wrapped/update"
    event['body'] = _body()  # no `email` field

    response = handler(event, mock_context)

    assert response['statusCode'] == 401
    mock_update.assert_not_called()
