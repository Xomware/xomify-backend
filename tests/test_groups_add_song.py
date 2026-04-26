"""
Tests for groups_add_song lambda.

The handler must accept BOTH request shapes:
  1. nested `track: {name, artists[{name}], album.images[{url}]}` (legacy)
  2. flat `{trackName, artistName, albumName, imageUrl}` (iOS client)

groupId / trackId are always required in the body. Caller email is sourced
from the authorizer context via `authorized_event` (post Track 1 migration).
"""

import json
from unittest.mock import patch

from lambdas.groups_add_song.handler import handler


def _event(authorized_event, email: str, body: dict) -> dict:
    return authorized_event(
        email=email,
        httpMethod="POST",
        path="/groups/add-song",
        body=json.dumps(body),
    )


@patch('lambdas.groups_add_song.handler.add_track_to_group')
def test_groups_add_song_flat_shape_ios(mock_add, mock_context, authorized_event):
    """iOS sends flat top-level fields — no `track` object."""
    body = {
        "groupId": "g1",
        "trackId": "spotify:track:1",
        "trackName": "Bohemian Rhapsody",
        "artistName": "Queen",
        "albumName": "A Night at the Opera",
        "imageUrl": "https://i.scdn.co/image/abc.jpg",
    }

    response = handler(_event(authorized_event, "user@example.com", body), mock_context)

    assert response['statusCode'] == 200
    payload = json.loads(response['body'])
    assert payload['trackId'] == "spotify:track:1"
    assert payload['trackName'] == "Bohemian Rhapsody"
    assert payload['artistName'] == "Queen"
    assert payload['albumName'] == "A Night at the Opera"
    assert payload['albumImageUrl'] == "https://i.scdn.co/image/abc.jpg"

    kwargs = mock_add.call_args.kwargs
    assert kwargs['group_id'] == 'g1'
    assert kwargs['track_id'] == 'spotify:track:1'
    assert kwargs['added_by'] == 'user@example.com'
    assert kwargs['track_name'] == 'Bohemian Rhapsody'
    assert kwargs['artist_name'] == 'Queen'
    assert kwargs['album_image_url'] == 'https://i.scdn.co/image/abc.jpg'


@patch('lambdas.groups_add_song.handler.add_track_to_group')
def test_groups_add_song_nested_shape_legacy(mock_add, mock_context, authorized_event):
    """Legacy nested `track` object still works."""
    body = {
        "groupId": "g1",
        "trackId": "spotify:track:1",
        "track": {
            "name": "Bohemian Rhapsody",
            "artists": [{"name": "Queen"}],
            "album": {
                "name": "A Night at the Opera",
                "images": [{"url": "https://i.scdn.co/image/abc.jpg"}],
            },
        },
    }

    response = handler(_event(authorized_event, "user@example.com", body), mock_context)

    assert response['statusCode'] == 200
    payload = json.loads(response['body'])
    assert payload['trackName'] == "Bohemian Rhapsody"
    assert payload['artistName'] == "Queen"
    assert payload['albumName'] == "A Night at the Opera"
    assert payload['albumImageUrl'] == "https://i.scdn.co/image/abc.jpg"

    kwargs = mock_add.call_args.kwargs
    assert kwargs['track_name'] == 'Bohemian Rhapsody'
    assert kwargs['artist_name'] == 'Queen'
    assert kwargs['album_image_url'] == 'https://i.scdn.co/image/abc.jpg'


@patch('lambdas.groups_add_song.handler.add_track_to_group')
def test_groups_add_song_missing_required_field(mock_add, mock_context, authorized_event):
    """Missing trackId -> 400, and we don't touch Dynamo."""
    body = {
        "groupId": "g1",
        "trackName": "Bohemian Rhapsody",
    }

    response = handler(_event(authorized_event, "user@example.com", body), mock_context)

    assert response['statusCode'] == 400
    mock_add.assert_not_called()


@patch('lambdas.groups_add_song.handler.add_track_to_group')
def test_groups_add_song_flat_shape_tolerates_missing_metadata(
    mock_add, mock_context, authorized_event
):
    """Only the three required keys are needed — track metadata is optional."""
    body = {
        "groupId": "g1",
        "trackId": "spotify:track:1",
    }

    response = handler(_event(authorized_event, "user@example.com", body), mock_context)

    assert response['statusCode'] == 200
    kwargs = mock_add.call_args.kwargs
    assert kwargs['track_name'] is None
    assert kwargs['artist_name'] is None
    assert kwargs['album_image_url'] is None


@patch('lambdas.groups_add_song.handler.add_track_to_group')
def test_groups_add_song_nested_shape_with_empty_arrays(
    mock_add, mock_context, authorized_event
):
    """Nested shape with empty artists/images lists — should not crash."""
    body = {
        "groupId": "g1",
        "trackId": "spotify:track:1",
        "track": {
            "name": "Some Song",
            "artists": [],
            "album": {"name": "X", "images": []},
        },
    }

    response = handler(_event(authorized_event, "user@example.com", body), mock_context)

    assert response['statusCode'] == 200
    kwargs = mock_add.call_args.kwargs
    assert kwargs['track_name'] == 'Some Song'
    assert kwargs['artist_name'] is None
    assert kwargs['album_image_url'] is None


@patch('lambdas.groups_add_song.handler.add_track_to_group')
def test_groups_add_song_missing_caller_identity_returns_401(
    mock_add, mock_context, legacy_event,
):
    """No authorizer context AND no caller email in body -> 401, no DDB writes."""
    body = {
        "groupId": "g1",
        "trackId": "spotify:track:1",
    }
    event = legacy_event()
    event["httpMethod"] = "POST"
    event["path"] = "/groups/add-song"
    event["body"] = json.dumps(body)

    response = handler(event, mock_context)

    assert response['statusCode'] == 401
    mock_add.assert_not_called()
