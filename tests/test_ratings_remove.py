"""
Tests for ratings_remove lambda

Covers the Track 1e migration: caller email is sourced from
`requestContext.authorizer.email` (per-user JWT) with fallback to query
string. `trackId` stays a required query parameter (it identifies which
of the caller's ratings to delete, not who the caller is).
"""

import json
from unittest.mock import patch

from lambdas.ratings_remove.handler import handler


@patch('lambdas.ratings_remove.handler.delete_track_rating')
def test_ratings_remove_uses_caller_context(
    mock_delete, mock_context, authorized_event
):
    """Caller email comes from authorizer; trackId stays in query params."""
    mock_delete.return_value = True
    event = authorized_event(
        email="alice@example.com",
        httpMethod="DELETE",
        path="/ratings/remove",
        queryStringParameters={"trackId": "track1"},
    )

    response = handler(event, mock_context)

    assert response['statusCode'] == 200
    mock_delete.assert_called_once_with("alice@example.com", "track1")
    body = json.loads(response['body'])
    assert body['success'] is True


@patch('lambdas.ratings_remove.handler.delete_track_rating')
def test_ratings_remove_falls_back_to_query_email(
    mock_delete, mock_context, legacy_event
):
    """Legacy clients still pass caller email on the query string."""
    mock_delete.return_value = True
    event = legacy_event(email="legacy@example.com")
    event["httpMethod"] = "DELETE"
    event["path"] = "/ratings/remove"
    event["queryStringParameters"]["trackId"] = "track1"

    response = handler(event, mock_context)

    assert response['statusCode'] == 200
    mock_delete.assert_called_once_with("legacy@example.com", "track1")


@patch('lambdas.ratings_remove.handler.delete_track_rating')
def test_ratings_remove_missing_identity_returns_401(
    mock_delete, mock_context, legacy_event
):
    """No caller anywhere -> 401, delete never invoked."""
    event = legacy_event()
    event["httpMethod"] = "DELETE"
    event["path"] = "/ratings/remove"
    event["queryStringParameters"] = {"trackId": "track1"}

    response = handler(event, mock_context)

    assert response['statusCode'] == 401
    mock_delete.assert_not_called()


@patch('lambdas.ratings_remove.handler.delete_track_rating')
def test_ratings_remove_missing_track_id_returns_400(
    mock_delete, mock_context, authorized_event
):
    """trackId is still a required query parameter."""
    event = authorized_event(
        httpMethod="DELETE",
        path="/ratings/remove",
        queryStringParameters={},
    )

    response = handler(event, mock_context)

    assert response['statusCode'] == 400
    mock_delete.assert_not_called()
