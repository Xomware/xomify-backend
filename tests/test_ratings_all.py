"""
Tests for ratings_all lambda

Covers the Track 1e migration: caller email is sourced from
`requestContext.authorizer.email` (per-user JWT) with fallback to query
string while legacy static-token clients are still in flight.
"""

import json
from unittest.mock import patch

from lambdas.ratings_all.handler import handler


SAMPLE_RATINGS = [
    {
        "email": "alice@example.com",
        "trackId": "track1",
        "rating": 5.0,
        "trackName": "Song One",
        "artistName": "Artist A",
        "albumArt": "https://example.com/a.jpg",
    },
    {
        "email": "alice@example.com",
        "trackId": "track2",
        "rating": 3.5,
        "trackName": "Song Two",
        "artistName": "Artist B",
        "albumArt": "https://example.com/b.jpg",
    },
]


@patch('lambdas.ratings_all.handler.list_all_track_ratings_for_user')
def test_ratings_all_uses_caller_context(
    mock_list, mock_context, authorized_event
):
    """Trusted authorizer context drives the lookup; no query param needed."""
    mock_list.return_value = SAMPLE_RATINGS
    event = authorized_event(
        email="alice@example.com",
        httpMethod="GET",
        path="/ratings/all",
    )

    response = handler(event, mock_context)

    assert response['statusCode'] == 200
    mock_list.assert_called_once_with("alice@example.com")
    body = json.loads(response['body'])
    assert body['totalCount'] == 2
    assert body['ratings'] == SAMPLE_RATINGS


@patch('lambdas.ratings_all.handler.list_all_track_ratings_for_user')
def test_ratings_all_falls_back_to_query_param(
    mock_list, mock_context, legacy_event
):
    """Legacy static-token callers still send caller email on the query string."""
    mock_list.return_value = []
    event = legacy_event(email="legacy@example.com")
    event["httpMethod"] = "GET"
    event["path"] = "/ratings/all"

    response = handler(event, mock_context)

    assert response['statusCode'] == 200
    mock_list.assert_called_once_with("legacy@example.com")
    body = json.loads(response['body'])
    assert body['totalCount'] == 0


@patch('lambdas.ratings_all.handler.list_all_track_ratings_for_user')
def test_ratings_all_missing_identity_returns_401(
    mock_list, mock_context, legacy_event
):
    """No context, no query, no body -> structured 401, no DB call."""
    event = legacy_event()
    event["httpMethod"] = "GET"
    event["path"] = "/ratings/all"

    response = handler(event, mock_context)

    assert response['statusCode'] == 401
    mock_list.assert_not_called()
