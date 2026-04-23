"""
Tests for shares_create lambda
"""

import json
from unittest.mock import patch

from lambdas.shares_create.handler import handler


VALID_BODY = {
    "email": "user@example.com",
    "trackId": "spotify:track:1",
    "trackUri": "spotify:track:1",
    "trackName": "Song",
    "artistName": "Artist",
    "albumName": "Album",
    "albumArtUrl": "https://example.com/art.jpg",
}


def _event(api_gateway_event, body):
    return {
        **api_gateway_event,
        "httpMethod": "POST",
        "path": "/shares/create",
        "body": json.dumps(body),
    }


@patch('lambdas.shares_create.handler.create_share')
def test_shares_create_happy_path(mock_create, mock_context, api_gateway_event):
    mock_create.return_value = {
        "shareId": "abc-123",
        "createdAt": "2026-04-22T12:00:00+00:00",
    }

    response = handler(_event(api_gateway_event, VALID_BODY), mock_context)

    assert response['statusCode'] == 200
    body = json.loads(response['body'])
    assert body['shareId'] == "abc-123"
    assert body['createdAt'] == "2026-04-22T12:00:00+00:00"
    mock_create.assert_called_once()


@patch('lambdas.shares_create.handler.create_share')
def test_shares_create_missing_required_field(mock_create, mock_context, api_gateway_event):
    incomplete = {k: v for k, v in VALID_BODY.items() if k != 'trackId'}
    response = handler(_event(api_gateway_event, incomplete), mock_context)

    assert response['statusCode'] == 400
    mock_create.assert_not_called()


@patch('lambdas.shares_create.handler.create_share')
def test_shares_create_caption_too_long(mock_create, mock_context, api_gateway_event):
    body = {**VALID_BODY, "caption": "a" * 141}
    response = handler(_event(api_gateway_event, body), mock_context)

    assert response['statusCode'] == 400
    assert 'caption' in json.loads(response['body'])['error']['message']
    mock_create.assert_not_called()


@patch('lambdas.shares_create.handler.create_share')
def test_shares_create_invalid_mood_tag(mock_create, mock_context, api_gateway_event):
    body = {**VALID_BODY, "moodTag": "bogus"}
    response = handler(_event(api_gateway_event, body), mock_context)

    assert response['statusCode'] == 400
    assert 'moodTag' in json.loads(response['body'])['error']['message']
    mock_create.assert_not_called()


@patch('lambdas.shares_create.handler.create_share')
def test_shares_create_too_many_genre_tags(mock_create, mock_context, api_gateway_event):
    body = {**VALID_BODY, "genreTags": ["a", "b", "c", "d"]}
    response = handler(_event(api_gateway_event, body), mock_context)

    assert response['statusCode'] == 400
    mock_create.assert_not_called()


@patch('lambdas.shares_create.handler.create_share')
def test_shares_create_valid_optional_fields(mock_create, mock_context, api_gateway_event):
    mock_create.return_value = {"shareId": "x", "createdAt": "2026-04-22T12:00:00+00:00"}
    body = {**VALID_BODY, "caption": "nice", "moodTag": "hype", "genreTags": ["pop", "rock"]}

    response = handler(_event(api_gateway_event, body), mock_context)

    assert response['statusCode'] == 200
    kwargs = mock_create.call_args.kwargs
    assert kwargs['caption'] == 'nice'
    assert kwargs['mood_tag'] == 'hype'
    assert kwargs['genre_tags'] == ['pop', 'rock']
