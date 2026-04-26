"""
Tests for the /likes/push lambda.

Covers:
- Happy path: items written, counter + timestamp updated.
- Throttle path: count + first-addedAt match cache -> skip items write.
- Auth-mismatch: body email != caller email -> 403.
- Validation: missing fields, malformed tracks, oversize cap enforcement,
  bad ``total`` types.
"""

from __future__ import annotations

import json
from unittest.mock import patch

import pytest

from lambdas.likes_push.handler import handler


def _push_event(authorized_event, *, body: dict) -> dict:
    """Build an authorized POST /likes/push event with a JSON body."""
    return authorized_event(
        email="user@example.com",
        httpMethod="POST",
        path="/likes/push",
        body=json.dumps(body),
    )


# ---------------------------------------------------------------- Happy path
@patch("lambdas.likes_push.handler.set_user_likes_count")
@patch("lambdas.likes_push.handler.upsert_user_likes")
@patch("lambdas.likes_push.handler.get_likes_settings")
def test_likes_push_happy_path_writes_items_and_counter(
    mock_get_settings, mock_upsert, mock_set_count, mock_context, authorized_event
):
    mock_get_settings.return_value = {
        "likes_count": 0,
        "likes_updated_at": None,
        "likes_public": True,
    }
    mock_upsert.return_value = 2
    mock_set_count.return_value = "2025-04-26T00:00:00Z"

    event = _push_event(
        authorized_event,
        body={
            "email": "user@example.com",
            "total": 2,
            "tracks": [
                {"trackId": "t1", "addedAt": "2025-04-26T00:00:00Z", "name": "S1"},
                {"trackId": "t2", "addedAt": "2025-04-25T00:00:00Z", "name": "S2"},
            ],
        },
    )

    response = handler(event, mock_context)

    assert response["statusCode"] == 200
    body = json.loads(response["body"])
    assert body == {
        "throttled": False,
        "written": 2,
        "likesCount": 2,
        "likesUpdatedAt": "2025-04-26T00:00:00Z",
    }
    mock_upsert.assert_called_once_with("user@example.com", event_tracks(event))
    mock_set_count.assert_called_once_with(
        "user@example.com", 2, updated_at="2025-04-26T00:00:00Z"
    )


def event_tracks(event: dict) -> list[dict]:
    return json.loads(event["body"])["tracks"]


# ---------------------------------------------------------------- Throttle path
@patch("lambdas.likes_push.handler.set_user_likes_count")
@patch("lambdas.likes_push.handler.upsert_user_likes")
@patch("lambdas.likes_push.handler.get_likes_settings")
def test_likes_push_throttled_when_total_and_first_added_match(
    mock_get_settings, mock_upsert, mock_set_count, mock_context, authorized_event
):
    mock_get_settings.return_value = {
        "likes_count": 5,
        "likes_updated_at": "2025-04-26T00:00:00Z",
        "likes_public": True,
    }
    mock_set_count.return_value = "2025-04-26T00:00:00Z"

    event = _push_event(
        authorized_event,
        body={
            "email": "user@example.com",
            "total": 5,
            "tracks": [
                {"trackId": "t1", "addedAt": "2025-04-26T00:00:00Z"},
                {"trackId": "t2", "addedAt": "2025-04-25T00:00:00Z"},
            ],
        },
    )

    response = handler(event, mock_context)

    assert response["statusCode"] == 200
    body = json.loads(response["body"])
    assert body["throttled"] is True
    assert body["written"] == 0
    assert body["likesCount"] == 5
    # Items write must be skipped on throttle.
    mock_upsert.assert_not_called()
    # Timestamp refresh still fires so "user is alive" remains observable.
    mock_set_count.assert_called_once_with(
        "user@example.com", 5, updated_at="2025-04-26T00:00:00Z"
    )


@patch("lambdas.likes_push.handler.set_user_likes_count")
@patch("lambdas.likes_push.handler.upsert_user_likes")
@patch("lambdas.likes_push.handler.get_likes_settings")
def test_likes_push_not_throttled_when_count_matches_but_addedat_differs(
    mock_get_settings, mock_upsert, mock_set_count, mock_context, authorized_event
):
    """Same count but the latest addedAt moved -> user added+removed, so write."""
    mock_get_settings.return_value = {
        "likes_count": 5,
        "likes_updated_at": "2025-04-25T00:00:00Z",
        "likes_public": True,
    }
    mock_upsert.return_value = 2
    mock_set_count.return_value = "2025-04-26T00:00:00Z"

    event = _push_event(
        authorized_event,
        body={
            "email": "user@example.com",
            "total": 5,
            "tracks": [
                {"trackId": "t1", "addedAt": "2025-04-26T00:00:00Z"},
                {"trackId": "t2", "addedAt": "2025-04-25T00:00:00Z"},
            ],
        },
    )

    response = handler(event, mock_context)

    body = json.loads(response["body"])
    assert body["throttled"] is False
    mock_upsert.assert_called_once()


# ---------------------------------------------------------------- Auth gate
@patch("lambdas.likes_push.handler.set_user_likes_count")
@patch("lambdas.likes_push.handler.upsert_user_likes")
@patch("lambdas.likes_push.handler.get_likes_settings")
def test_likes_push_rejects_cross_user_push(
    mock_get_settings, mock_upsert, mock_set_count, mock_context, authorized_event
):
    event = _push_event(
        authorized_event,
        body={
            "email": "someone-else@example.com",
            "total": 1,
            "tracks": [{"trackId": "t1", "addedAt": "2025-04-26T00:00:00Z"}],
        },
    )

    response = handler(event, mock_context)

    assert response["statusCode"] == 401  # Authorization error -> 401 by base class
    mock_upsert.assert_not_called()
    mock_set_count.assert_not_called()


# ---------------------------------------------------------------- Validation
def test_likes_push_missing_email_field(mock_context, authorized_event):
    event = _push_event(
        authorized_event,
        body={"total": 0, "tracks": []},
    )
    response = handler(event, mock_context)
    assert response["statusCode"] == 400


def test_likes_push_missing_total(mock_context, authorized_event):
    event = _push_event(
        authorized_event,
        body={"email": "user@example.com", "tracks": []},
    )
    response = handler(event, mock_context)
    assert response["statusCode"] == 400


def test_likes_push_missing_tracks(mock_context, authorized_event):
    event = _push_event(
        authorized_event,
        body={"email": "user@example.com", "total": 0},
    )
    response = handler(event, mock_context)
    assert response["statusCode"] == 400


def test_likes_push_rejects_non_int_total(mock_context, authorized_event):
    event = _push_event(
        authorized_event,
        body={"email": "user@example.com", "total": "lots", "tracks": []},
    )
    response = handler(event, mock_context)
    assert response["statusCode"] == 400


def test_likes_push_rejects_negative_total(mock_context, authorized_event):
    event = _push_event(
        authorized_event,
        body={"email": "user@example.com", "total": -1, "tracks": []},
    )
    response = handler(event, mock_context)
    assert response["statusCode"] == 400


def test_likes_push_rejects_malformed_tracks(mock_context, authorized_event):
    event = _push_event(
        authorized_event,
        body={
            "email": "user@example.com",
            "total": 1,
            "tracks": [{"trackId": "t1"}],  # missing addedAt
        },
    )
    response = handler(event, mock_context)
    assert response["statusCode"] == 400


def test_likes_push_rejects_non_list_tracks(mock_context, authorized_event):
    event = _push_event(
        authorized_event,
        body={"email": "user@example.com", "total": 0, "tracks": "nope"},
    )
    response = handler(event, mock_context)
    assert response["statusCode"] == 400


@patch("lambdas.likes_push.handler.set_user_likes_count")
@patch("lambdas.likes_push.handler.upsert_user_likes")
@patch("lambdas.likes_push.handler.get_likes_settings")
def test_likes_push_caps_oversized_payload_at_max(
    mock_get_settings, mock_upsert, mock_set_count, mock_context, authorized_event
):
    """Oversize payloads are silently truncated to MAX_LIKES_PAGE."""
    from lambdas.likes_push import handler as likes_push_handler

    mock_get_settings.return_value = {
        "likes_count": 0,
        "likes_updated_at": None,
        "likes_public": True,
    }
    mock_upsert.return_value = likes_push_handler.MAX_LIKES_PAGE
    mock_set_count.return_value = "2025-04-26T00:00:00Z"

    big_payload = [
        {"trackId": f"t{i}", "addedAt": "2025-04-26T00:00:00Z"}
        for i in range(likes_push_handler.MAX_LIKES_PAGE + 50)
    ]
    event = _push_event(
        authorized_event,
        body={
            "email": "user@example.com",
            "total": len(big_payload),
            "tracks": big_payload,
        },
    )

    response = handler(event, mock_context)

    assert response["statusCode"] == 200
    args, _kwargs = mock_upsert.call_args
    sent_tracks = args[1]
    assert len(sent_tracks) == likes_push_handler.MAX_LIKES_PAGE
