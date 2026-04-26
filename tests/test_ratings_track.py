"""
Tests for ratings_track lambda

Covers the Track 1e migration: caller email is sourced from
`requestContext.authorizer.email` (per-user JWT) with fallback to query
string. `trackId` stays a required query parameter.
"""

import json
from unittest.mock import patch

from lambdas.ratings_track.handler import handler


SAMPLE_RATING = {
    "email": "alice@example.com",
    "trackId": "track1",
    "rating": 4.0,
    "trackName": "Song One",
    "artistName": "Artist A",
    "albumArt": "https://example.com/a.jpg",
}


@patch('lambdas.ratings_track.handler.get_single_track_rating_for_user')
def test_ratings_track_uses_caller_context(
    mock_get, mock_context, authorized_event
):
    """Caller email comes from authorizer; trackId stays in query params."""
    mock_get.return_value = SAMPLE_RATING
    event = authorized_event(
        email="alice@example.com",
        httpMethod="GET",
        path="/ratings/track",
        queryStringParameters={"trackId": "track1"},
    )

    response = handler(event, mock_context)

    assert response['statusCode'] == 200
    mock_get.assert_called_once_with("alice@example.com", "track1")
    body = json.loads(response['body'])
    assert body['rating'] == SAMPLE_RATING


@patch('lambdas.ratings_track.handler.get_single_track_rating_for_user')
def test_ratings_track_falls_back_to_query_email(
    mock_get, mock_context, legacy_event
):
    """Legacy clients pass caller email on the query string."""
    mock_get.return_value = SAMPLE_RATING
    event = legacy_event(email="legacy@example.com")
    event["httpMethod"] = "GET"
    event["path"] = "/ratings/track"
    event["queryStringParameters"]["trackId"] = "track1"

    response = handler(event, mock_context)

    assert response['statusCode'] == 200
    mock_get.assert_called_once_with("legacy@example.com", "track1")


@patch('lambdas.ratings_track.handler.get_single_track_rating_for_user')
def test_ratings_track_missing_identity_returns_401(
    mock_get, mock_context, legacy_event
):
    """No caller anywhere -> 401, lookup never invoked."""
    event = legacy_event()
    event["httpMethod"] = "GET"
    event["path"] = "/ratings/track"
    event["queryStringParameters"] = {"trackId": "track1"}

    response = handler(event, mock_context)

    assert response['statusCode'] == 401
    mock_get.assert_not_called()


@patch('lambdas.ratings_track.handler.get_single_track_rating_for_user')
def test_ratings_track_missing_track_id_returns_400(
    mock_get, mock_context, authorized_event
):
    """trackId is still a required query parameter."""
    event = authorized_event(
        httpMethod="GET",
        path="/ratings/track",
        queryStringParameters={},
    )

    response = handler(event, mock_context)

    assert response['statusCode'] == 400
    mock_get.assert_not_called()
