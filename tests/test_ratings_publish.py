"""
Tests for ratings_publish lambda

Covers the Track 1e migration: caller email is sourced from
`requestContext.authorizer.email` (per-user JWT) with fallback to body
during the migration window. Track-level fields (trackId, rating, etc.)
remain explicit body inputs.
"""

import json
from unittest.mock import patch

from lambdas.ratings_publish.handler import handler


def _publish_body(**overrides):
    body = {
        "trackId": "track1",
        "rating": 4.5,
        "trackName": "Song One",
        "artistName": "Artist A",
        "albumArt": "https://example.com/a.jpg",
    }
    body.update(overrides)
    return body


@patch('lambdas.ratings_publish.handler.upsert_track_rating')
def test_ratings_publish_uses_caller_context(
    mock_upsert, mock_context, authorized_event
):
    """Caller email comes from authorizer context; track fields from body."""
    mock_upsert.return_value = {
        "email": "alice@example.com",
        "trackId": "track1",
        "rating": 4.5,
    }
    event = authorized_event(
        email="alice@example.com",
        httpMethod="POST",
        path="/ratings/publish",
        body=json.dumps(_publish_body()),
    )

    response = handler(event, mock_context)

    assert response['statusCode'] == 200
    mock_upsert.assert_called_once_with(
        "alice@example.com",
        "track1",
        4.5,
        "Song One",
        "Artist A",
        "https://example.com/a.jpg",
        None,
        None,
    )
    body = json.loads(response['body'])
    assert body['rating']['trackId'] == "track1"


@patch('lambdas.ratings_publish.handler.upsert_track_rating')
def test_ratings_publish_falls_back_to_body_email(
    mock_upsert, mock_context, legacy_event
):
    """Legacy clients send caller email in the JSON body alongside track data."""
    mock_upsert.return_value = {"email": "legacy@example.com", "trackId": "track1"}
    event = legacy_event()
    event["httpMethod"] = "POST"
    event["path"] = "/ratings/publish"
    event["body"] = json.dumps(_publish_body(email="legacy@example.com"))

    response = handler(event, mock_context)

    assert response['statusCode'] == 200
    args, _ = mock_upsert.call_args
    assert args[0] == "legacy@example.com"
    assert args[1] == "track1"


@patch('lambdas.ratings_publish.handler.upsert_track_rating')
def test_ratings_publish_missing_identity_returns_401(
    mock_upsert, mock_context, legacy_event
):
    """No caller email anywhere -> 401, upsert never invoked."""
    event = legacy_event()
    event["httpMethod"] = "POST"
    event["path"] = "/ratings/publish"
    event["body"] = json.dumps(_publish_body())  # no email field

    response = handler(event, mock_context)

    assert response['statusCode'] == 401
    mock_upsert.assert_not_called()


@patch('lambdas.ratings_publish.handler.upsert_track_rating')
def test_ratings_publish_missing_track_id_returns_400(
    mock_upsert, mock_context, authorized_event
):
    """Track id is still validated as a required body field."""
    body = _publish_body()
    body.pop("trackId")
    event = authorized_event(
        httpMethod="POST",
        path="/ratings/publish",
        body=json.dumps(body),
    )

    response = handler(event, mock_context)

    assert response['statusCode'] == 400
    mock_upsert.assert_not_called()
