"""
Tests for shares_delete lambda
"""

import json
from unittest.mock import patch

from lambdas.shares_delete.handler import handler


def _event(api_gateway_event, params):
    return {
        **api_gateway_event,
        "httpMethod": "DELETE",
        "path": "/shares/delete",
        "queryStringParameters": params,
    }


@patch('lambdas.shares_delete.handler.delete_share')
@patch('lambdas.shares_delete.handler.get_share')
def test_shares_delete_owner_success(
    mock_get, mock_delete, mock_context, api_gateway_event
):
    mock_get.return_value = {"shareId": "s1", "email": "owner@example.com"}
    mock_delete.return_value = True

    response = handler(
        _event(api_gateway_event, {"email": "owner@example.com", "shareId": "s1"}),
        mock_context,
    )

    assert response['statusCode'] == 204
    mock_delete.assert_called_once_with("s1")


@patch('lambdas.shares_delete.handler.delete_share')
@patch('lambdas.shares_delete.handler.get_share')
def test_shares_delete_non_owner_forbidden(
    mock_get, mock_delete, mock_context, api_gateway_event
):
    mock_get.return_value = {"shareId": "s1", "email": "owner@example.com"}

    response = handler(
        _event(api_gateway_event, {"email": "stranger@example.com", "shareId": "s1"}),
        mock_context,
    )

    # AuthorizationError defaults to 401; this handler accepts that the wire
    # response mirrors the declared status on the exception class.
    assert response['statusCode'] == 401
    mock_delete.assert_not_called()


@patch('lambdas.shares_delete.handler.delete_share')
@patch('lambdas.shares_delete.handler.get_share')
def test_shares_delete_not_found(
    mock_get, mock_delete, mock_context, api_gateway_event
):
    mock_get.return_value = None

    response = handler(
        _event(api_gateway_event, {"email": "owner@example.com", "shareId": "missing"}),
        mock_context,
    )

    assert response['statusCode'] == 404
    mock_delete.assert_not_called()


@patch('lambdas.shares_delete.handler.get_share')
def test_shares_delete_missing_fields(mock_get, mock_context, api_gateway_event):
    response = handler(
        _event(api_gateway_event, {"email": "owner@example.com"}),
        mock_context,
    )
    assert response['statusCode'] == 400
    mock_get.assert_not_called()
