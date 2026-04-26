"""
Tests for shares_delete lambda
"""

import json
from unittest.mock import patch

from lambdas.shares_delete.handler import handler


def _query_event(authorized_event, params, email="owner@example.com"):
    return authorized_event(
        email=email,
        httpMethod="DELETE",
        path="/shares/delete",
        queryStringParameters=params,
    )


def _body_event(authorized_event, body, email="owner@example.com"):
    """Mirror iOS: POST/DELETE with JSON body, no query string."""
    return authorized_event(
        email=email,
        httpMethod="POST",
        path="/shares/delete",
        queryStringParameters=None,
        body=json.dumps(body),
    )


@patch('lambdas.shares_delete.handler.delete_share')
@patch('lambdas.shares_delete.handler.get_share')
def test_shares_delete_owner_success(
    mock_get, mock_delete, mock_context, authorized_event
):
    mock_get.return_value = {"shareId": "s1", "email": "owner@example.com"}
    mock_delete.return_value = True

    response = handler(
        _query_event(authorized_event, {"shareId": "s1"}, email="owner@example.com"),
        mock_context,
    )

    assert response['statusCode'] == 204
    mock_delete.assert_called_once_with("s1")


@patch('lambdas.shares_delete.handler.delete_share')
@patch('lambdas.shares_delete.handler.get_share')
def test_shares_delete_non_owner_forbidden(
    mock_get, mock_delete, mock_context, authorized_event
):
    mock_get.return_value = {"shareId": "s1", "email": "owner@example.com"}

    response = handler(
        _query_event(authorized_event, {"shareId": "s1"}, email="stranger@example.com"),
        mock_context,
    )

    # AuthorizationError defaults to 401; this handler accepts that the wire
    # response mirrors the declared status on the exception class.
    assert response['statusCode'] == 401
    mock_delete.assert_not_called()


@patch('lambdas.shares_delete.handler.delete_share')
@patch('lambdas.shares_delete.handler.get_share')
def test_shares_delete_not_found(
    mock_get, mock_delete, mock_context, authorized_event
):
    mock_get.return_value = None

    response = handler(
        _query_event(authorized_event, {"shareId": "missing"}, email="owner@example.com"),
        mock_context,
    )

    assert response['statusCode'] == 404
    mock_delete.assert_not_called()


@patch('lambdas.shares_delete.handler.get_share')
def test_shares_delete_missing_share_id(mock_get, mock_context, authorized_event):
    response = handler(
        _query_event(authorized_event, {}),
        mock_context,
    )
    assert response['statusCode'] == 400
    mock_get.assert_not_called()


# Bug regression: iOS POSTs `{shareId, sharedAt}` in the JSON body, not the
# query string. The previous handler only read query params, so the request
# silently failed validation (or — depending on API Gateway routing — ran
# with empty identifiers and never actually deleted the row). The handler
# now reads body OR query params for shareId.
@patch('lambdas.shares_delete.handler.delete_share')
@patch('lambdas.shares_delete.handler.get_share')
def test_shares_delete_accepts_body_payload(
    mock_get, mock_delete, mock_context, authorized_event
):
    mock_get.return_value = {"shareId": "s1", "email": "owner@example.com"}
    mock_delete.return_value = True

    response = handler(
        _body_event(authorized_event, {
            "shareId": "s1",
            "sharedAt": "2026-04-23T12:00:00+00:00",
        }, email="owner@example.com"),
        mock_context,
    )

    assert response['statusCode'] == 204
    mock_delete.assert_called_once_with("s1")


@patch('lambdas.shares_delete.handler.delete_share')
@patch('lambdas.shares_delete.handler.get_share')
def test_shares_delete_body_missing_share_id(
    mock_get, mock_delete, mock_context, authorized_event
):
    response = handler(
        _body_event(authorized_event, {}),
        mock_context,
    )
    assert response['statusCode'] == 400
    mock_get.assert_not_called()
    mock_delete.assert_not_called()


# ------------------------------------------------------------------ Auth
@patch('lambdas.shares_delete.handler.delete_share')
@patch('lambdas.shares_delete.handler.get_share')
def test_shares_delete_missing_caller_identity_returns_401(
    mock_get, mock_delete, mock_context, api_gateway_event
):
    event = {
        **api_gateway_event,
        "httpMethod": "DELETE",
        "path": "/shares/delete",
        "queryStringParameters": {"shareId": "s1"},
    }
    response = handler(event, mock_context)
    assert response['statusCode'] == 401
    mock_get.assert_not_called()
    mock_delete.assert_not_called()
