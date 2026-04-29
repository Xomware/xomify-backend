"""
Regression tests for the author-auto-listener wiring on /shares/create.

Bug 3 (the one this guards): the author of a share should appear as a
listener on their own share immediately. Today /shares/create doesn't
write a listener row, so authors look like they "never listened" to their
own song until they hit Queue or Play.

Coverage:
- happy path: shares_create writes mark_listened(shareId, author, "author_create")
- mark_listened failure does NOT roll back / 500 the share creation
"""

import json
from unittest.mock import patch

from lambdas.shares_create.handler import handler


VALID_BODY = {
    "trackId": "spotify:track:1",
    "trackUri": "spotify:track:1",
    "trackName": "Song",
    "artistName": "Artist",
    "albumName": "Album",
    "albumArtUrl": "https://example.com/art.jpg",
}


def _event(authorized_event, body, email="author@example.com"):
    return authorized_event(
        email=email,
        httpMethod="POST",
        path="/shares/create",
        body=json.dumps(body),
    )


@patch('lambdas.shares_create.handler.mark_listened')
@patch('lambdas.shares_create.handler.create_share')
def test_shares_create_marks_author_as_listener_on_success(
    mock_create, mock_mark, mock_context, authorized_event
):
    mock_create.return_value = {
        "shareId": "share-123",
        "createdAt": "2026-04-22T12:00:00+00:00",
        "groupIds": [],
        "public": True,
    }

    response = handler(_event(authorized_event, VALID_BODY), mock_context)

    assert response['statusCode'] == 200
    mock_mark.assert_called_once_with(
        "share-123", "author@example.com", source="author_create"
    )


@patch('lambdas.shares_create.handler.mark_listened')
@patch('lambdas.shares_create.handler.create_share')
def test_shares_create_succeeds_even_when_listener_write_fails(
    mock_create, mock_mark, mock_context, authorized_event
):
    """
    Auto-listener is best-effort. A blow-up there must NOT 500 / roll back
    the share creation — the user still expects their share to land.
    """
    mock_create.return_value = {
        "shareId": "share-123",
        "createdAt": "2026-04-22T12:00:00+00:00",
        "groupIds": [],
        "public": True,
    }
    mock_mark.side_effect = RuntimeError("listeners table down")

    response = handler(_event(authorized_event, VALID_BODY), mock_context)

    assert response['statusCode'] == 200
    body = json.loads(response['body'])
    assert body['shareId'] == "share-123"
    mock_mark.assert_called_once()
