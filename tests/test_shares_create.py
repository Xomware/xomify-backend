"""
Tests for shares_create lambda.

Covers legacy public-only behavior plus the v2 multi-target contract:
- groupIds + public defaults preserve legacy callers
- non-member groupIds rejected (403 AuthorizationError)
- public=False with empty groupIds rejected (400 ValidationError)
- dual / group-only persistence paths
- caller identity migration: helper-sourced email + 401 on missing context
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


def _event(authorized_event, body, email="user@example.com"):
    return authorized_event(
        email=email,
        httpMethod="POST",
        path="/shares/create",
        body=json.dumps(body),
    )


@patch('lambdas.shares_create.handler.create_share')
def test_shares_create_happy_path(mock_create, mock_context, authorized_event):
    mock_create.return_value = {
        "shareId": "abc-123",
        "createdAt": "2026-04-22T12:00:00+00:00",
        "groupIds": [],
        "public": True,
    }

    response = handler(_event(authorized_event, VALID_BODY), mock_context)

    assert response['statusCode'] == 200
    body = json.loads(response['body'])
    assert body['shareId'] == "abc-123"
    assert body['createdAt'] == "2026-04-22T12:00:00+00:00"
    # Defaults: public share, no groups.
    assert body['public'] is True
    assert body['groupIds'] == []
    kwargs = mock_create.call_args.kwargs
    assert kwargs['group_ids'] == []
    assert kwargs['public'] is True
    # Caller email comes from authorizer context, not the body.
    assert kwargs['email'] == "user@example.com"


@patch('lambdas.shares_create.handler.create_share')
def test_shares_create_missing_required_field(mock_create, mock_context, authorized_event):
    incomplete = {k: v for k, v in VALID_BODY.items() if k != 'trackId'}
    response = handler(_event(authorized_event, incomplete), mock_context)

    assert response['statusCode'] == 400
    mock_create.assert_not_called()


@patch('lambdas.shares_create.handler.create_share')
def test_shares_create_caption_too_long(mock_create, mock_context, authorized_event):
    body = {**VALID_BODY, "caption": "a" * 141}
    response = handler(_event(authorized_event, body), mock_context)

    assert response['statusCode'] == 400
    assert 'caption' in json.loads(response['body'])['error']['message']
    mock_create.assert_not_called()


@patch('lambdas.shares_create.handler.create_share')
def test_shares_create_invalid_mood_tag(mock_create, mock_context, authorized_event):
    body = {**VALID_BODY, "moodTag": "bogus"}
    response = handler(_event(authorized_event, body), mock_context)

    assert response['statusCode'] == 400
    assert 'moodTag' in json.loads(response['body'])['error']['message']
    mock_create.assert_not_called()


@patch('lambdas.shares_create.handler.create_share')
def test_shares_create_too_many_genre_tags(mock_create, mock_context, authorized_event):
    body = {**VALID_BODY, "genreTags": ["a", "b", "c", "d"]}
    response = handler(_event(authorized_event, body), mock_context)

    assert response['statusCode'] == 400
    mock_create.assert_not_called()


@patch('lambdas.shares_create.handler.create_share')
def test_shares_create_valid_optional_fields(mock_create, mock_context, authorized_event):
    mock_create.return_value = {
        "shareId": "x",
        "createdAt": "2026-04-22T12:00:00+00:00",
        "groupIds": [],
        "public": True,
    }
    body = {**VALID_BODY, "caption": "nice", "moodTag": "hype", "genreTags": ["pop", "rock"]}

    response = handler(_event(authorized_event, body), mock_context)

    assert response['statusCode'] == 200
    kwargs = mock_create.call_args.kwargs
    assert kwargs['caption'] == 'nice'
    assert kwargs['mood_tag'] == 'hype'
    assert kwargs['genre_tags'] == ['pop', 'rock']


# ------------------------------------------------------------
# Multi-target (groupIds + public)
# ------------------------------------------------------------

@patch('lambdas.shares_create.handler.is_member_of_group')
@patch('lambdas.shares_create.handler.create_share')
def test_shares_create_dual_target_public_and_groups(
    mock_create, mock_member, mock_context, authorized_event
):
    """public=True with groupIds -> dual share, persisted with both fields."""
    mock_member.return_value = True
    mock_create.return_value = {
        "shareId": "s1",
        "createdAt": "2026-04-22T12:00:00+00:00",
        "groupIds": ["g1", "g2"],
        "public": True,
    }
    body = {**VALID_BODY, "groupIds": ["g1", "g2"], "public": True}

    response = handler(_event(authorized_event, body), mock_context)

    assert response['statusCode'] == 200
    kwargs = mock_create.call_args.kwargs
    assert kwargs['group_ids'] == ["g1", "g2"]
    assert kwargs['public'] is True
    # Both groups were checked.
    checked = {c.args[1] for c in mock_member.call_args_list}
    assert checked == {"g1", "g2"}


@patch('lambdas.shares_create.handler.is_member_of_group')
@patch('lambdas.shares_create.handler.create_share')
def test_shares_create_group_only_share(
    mock_create, mock_member, mock_context, authorized_event
):
    """public=False with groupIds -> group-only share."""
    mock_member.return_value = True
    mock_create.return_value = {
        "shareId": "s2",
        "createdAt": "2026-04-22T12:00:00+00:00",
        "groupIds": ["g1"],
        "public": False,
    }
    body = {**VALID_BODY, "groupIds": ["g1"], "public": False}

    response = handler(_event(authorized_event, body), mock_context)

    assert response['statusCode'] == 200
    kwargs = mock_create.call_args.kwargs
    assert kwargs['group_ids'] == ["g1"]
    assert kwargs['public'] is False


@patch('lambdas.shares_create.handler.is_member_of_group')
@patch('lambdas.shares_create.handler.create_share')
def test_shares_create_rejects_non_member_group(
    mock_create, mock_member, mock_context, authorized_event
):
    """Caller not a member of the requested group -> 401 AuthorizationError."""
    mock_member.side_effect = lambda email, gid: gid != "g-forbidden"
    body = {**VALID_BODY, "groupIds": ["g1", "g-forbidden"]}

    response = handler(_event(authorized_event, body), mock_context)

    # AuthorizationError.status == 401 (see lambdas/common/errors.py)
    assert response['statusCode'] == 401
    assert "g-forbidden" in json.loads(response['body'])['error']['message']
    mock_create.assert_not_called()


@patch('lambdas.shares_create.handler.is_member_of_group')
@patch('lambdas.shares_create.handler.create_share')
def test_shares_create_rejects_private_with_no_targets(
    mock_create, mock_member, mock_context, authorized_event
):
    """public=False + empty groupIds -> 400."""
    body = {**VALID_BODY, "groupIds": [], "public": False}

    response = handler(_event(authorized_event, body), mock_context)

    assert response['statusCode'] == 400
    assert 'target' in json.loads(response['body'])['error']['message'].lower()
    mock_create.assert_not_called()
    # Membership check should short-circuit (no groups to check).
    mock_member.assert_not_called()


@patch('lambdas.shares_create.handler.is_member_of_group')
@patch('lambdas.shares_create.handler.create_share')
def test_shares_create_group_ids_must_be_list(
    mock_create, mock_member, mock_context, authorized_event
):
    body = {**VALID_BODY, "groupIds": "g1"}

    response = handler(_event(authorized_event, body), mock_context)

    assert response['statusCode'] == 400
    mock_create.assert_not_called()
    mock_member.assert_not_called()


# ------------------------------------------------------------
# Caller-identity migration
# ------------------------------------------------------------

@patch('lambdas.shares_create.handler.create_share')
def test_shares_create_missing_caller_identity_returns_401(
    mock_create, mock_context, api_gateway_event
):
    """No authorizer context AND no email in body -> 401 from helper."""
    event = {
        **api_gateway_event,
        "httpMethod": "POST",
        "path": "/shares/create",
        "body": json.dumps(VALID_BODY),
    }
    response = handler(event, mock_context)
    assert response['statusCode'] == 401
    mock_create.assert_not_called()


@patch('lambdas.shares_create.handler.create_share')
def test_shares_create_legacy_email_in_body_still_works(
    mock_create, mock_context, legacy_event
):
    """During the migration window, the helper falls back to body `email`."""
    mock_create.return_value = {
        "shareId": "legacy-1",
        "createdAt": "2026-04-22T12:00:00+00:00",
        "groupIds": [],
        "public": True,
    }
    body_with_email = {**VALID_BODY, "email": "legacy@example.com"}
    event = legacy_event(
        httpMethod="POST",
        path="/shares/create",
        body=json.dumps(body_with_email),
    )
    response = handler(event, mock_context)
    assert response['statusCode'] == 200
    assert mock_create.call_args.kwargs['email'] == "legacy@example.com"


# ------------------------------------------------------------
# Rate-on-share
# ------------------------------------------------------------

SHARE_RESULT = {
    "shareId": "share-ros-1",
    "createdAt": "2026-04-26T12:00:00+00:00",
    "groupIds": [],
    "public": True,
}


@patch('lambdas.shares_create.handler.upsert_track_rating')
@patch('lambdas.shares_create.handler.create_share')
def test_shares_create_without_rating_does_not_call_upsert(
    mock_create, mock_upsert, mock_context, authorized_event
):
    """Share without `rating` field still works; upsert is never called."""
    mock_create.return_value = SHARE_RESULT
    response = handler(_event(authorized_event, VALID_BODY), mock_context)
    assert response['statusCode'] == 200
    mock_upsert.assert_not_called()


@patch('lambdas.shares_create.handler.upsert_track_rating')
@patch('lambdas.shares_create.handler.create_share')
def test_shares_create_with_valid_rating_writes_both_rows(
    mock_create, mock_upsert, mock_context, authorized_event
):
    """Share with rating=4 writes the share row and then calls upsert_track_rating."""
    mock_create.return_value = SHARE_RESULT
    body = {**VALID_BODY, "rating": 4}
    response = handler(_event(authorized_event, body), mock_context)
    assert response['statusCode'] == 200
    mock_upsert.assert_called_once()
    call_kwargs = mock_upsert.call_args.kwargs
    assert call_kwargs['rating'] == 4
    assert call_kwargs['track_id'] == VALID_BODY['trackId']


@patch('lambdas.shares_create.handler.upsert_track_rating')
@patch('lambdas.shares_create.handler.create_share')
def test_shares_create_with_out_of_range_rating_ignores_rating(
    mock_create, mock_upsert, mock_context, authorized_event
):
    """Share with rating=99 writes share only; upsert is not called (silently ignored)."""
    mock_create.return_value = SHARE_RESULT
    body = {**VALID_BODY, "rating": 99}
    response = handler(_event(authorized_event, body), mock_context)
    assert response['statusCode'] == 200
    mock_upsert.assert_not_called()
