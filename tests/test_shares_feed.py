"""
Tests for shares_feed lambda
"""

import json
from unittest.mock import patch

from lambdas.shares_feed.handler import handler


def _event(authorized_event, params, email="me@example.com"):
    return authorized_event(
        email=email,
        httpMethod="GET",
        path="/shares/feed",
        queryStringParameters=params,
    )


@patch('lambdas.shares_feed.handler.query_feed_for_emails')
@patch('lambdas.shares_feed.handler.list_all_friends_for_user')
def test_shares_feed_happy_path(mock_friends, mock_query, mock_context, authorized_event):
    mock_friends.return_value = [
        {"friendEmail": "alice@example.com", "status": "accepted"},
        {"friendEmail": "bob@example.com", "status": "accepted"},
        {"friendEmail": "blocked@example.com", "status": "blocked"},
    ]
    mock_query.return_value = [
        {"shareId": "1", "email": "alice@example.com", "createdAt": "2026-04-22T12:00:00+00:00"},
        {"shareId": "2", "email": "me@example.com", "createdAt": "2026-04-22T11:00:00+00:00"},
    ]

    response = handler(
        _event(authorized_event, {}, email="me@example.com"),
        mock_context,
    )

    assert response['statusCode'] == 200
    body = json.loads(response['body'])
    assert len(body['shares']) == 2
    # Enrichment stubs populated
    assert body['shares'][0]['queuedCount'] == 0
    assert body['shares'][0]['viewerHasQueued'] is False
    # Fan-out emails: me + accepted friends (blocked excluded)
    emails_arg = mock_query.call_args.args[0]
    assert set(emails_arg) == {"me@example.com", "alice@example.com", "bob@example.com"}


@patch('lambdas.shares_feed.handler.query_feed_for_emails')
@patch('lambdas.shares_feed.handler.list_all_friends_for_user')
def test_shares_feed_empty_friends(mock_friends, mock_query, mock_context, authorized_event):
    mock_friends.return_value = []
    mock_query.return_value = []

    response = handler(
        _event(authorized_event, {}, email="solo@example.com"),
        mock_context,
    )

    assert response['statusCode'] == 200
    body = json.loads(response['body'])
    assert body['shares'] == []
    assert body['nextBefore'] is None
    # Still fans out over the requester themselves
    assert mock_query.call_args.args[0] == ["solo@example.com"]


@patch('lambdas.shares_feed.handler.list_members_of_group')
@patch('lambdas.shares_feed.handler.query_feed_for_emails')
@patch('lambdas.shares_feed.handler.list_all_friends_for_user')
def test_shares_feed_group_filter_intersects(
    mock_friends, mock_query, mock_members, mock_context, authorized_event
):
    mock_friends.return_value = [
        {"friendEmail": "alice@example.com", "status": "accepted"},
        {"friendEmail": "bob@example.com", "status": "accepted"},
    ]
    mock_members.return_value = [
        {"email": "alice@example.com"},
        {"email": "me@example.com"},
        {"email": "unrelated@example.com"},
    ]
    mock_query.return_value = []

    handler(
        _event(authorized_event, {"groupId": "g1"}, email="me@example.com"),
        mock_context,
    )

    emails_arg = mock_query.call_args.args[0]
    # Intersection of {me, alice, bob} with {alice, me, unrelated} = {me, alice}
    assert set(emails_arg) == {"me@example.com", "alice@example.com"}


# ------------------------------------------------------------
# Public / group-only visibility filter (v2)
# ------------------------------------------------------------

@patch('lambdas.shares_feed.handler.query_feed_for_emails')
@patch('lambdas.shares_feed.handler.list_all_friends_for_user')
def test_shares_feed_public_feed_excludes_group_only_rows(
    mock_friends, mock_query, mock_context, authorized_event
):
    """Friends feed (no groupId) must hide rows with public=False."""
    mock_friends.return_value = [
        {"friendEmail": "alice@example.com", "status": "accepted"},
    ]
    mock_query.return_value = [
        # Legacy row - no `public` field -> default visible
        {"shareId": "legacy", "email": "alice@example.com",
         "createdAt": "2026-04-22T12:00:00+00:00"},
        # Dual share - public=True + groups -> visible
        {"shareId": "dual", "email": "alice@example.com",
         "createdAt": "2026-04-22T11:00:00+00:00",
         "public": True, "groupIds": ["g1"]},
        # Group-only share - public=False -> hidden from friends feed
        {"shareId": "group-only", "email": "alice@example.com",
         "createdAt": "2026-04-22T10:00:00+00:00",
         "public": False, "groupIds": ["g1"]},
    ]

    response = handler(
        _event(authorized_event, {}),
        mock_context,
    )

    assert response['statusCode'] == 200
    body = json.loads(response['body'])
    ids = [s['shareId'] for s in body['shares']]
    assert "group-only" not in ids
    assert set(ids) == {"legacy", "dual"}


@patch('lambdas.shares_feed.handler.list_members_of_group')
@patch('lambdas.shares_feed.handler.query_feed_for_emails')
@patch('lambdas.shares_feed.handler.list_all_friends_for_user')
def test_shares_feed_group_feed_includes_group_targeted_rows(
    mock_friends, mock_query, mock_members, mock_context, authorized_event
):
    """Group feed must include both group-only and dual shares targeted to that
    group, and must drop rows that don't list the group in groupIds."""
    mock_friends.return_value = [
        {"friendEmail": "alice@example.com", "status": "accepted"},
    ]
    mock_members.return_value = [
        {"email": "alice@example.com"},
        {"email": "me@example.com"},
    ]
    mock_query.return_value = [
        # Targets g1 via dual share
        {"shareId": "dual", "email": "alice@example.com",
         "createdAt": "2026-04-22T12:00:00+00:00",
         "public": True, "groupIds": ["g1", "g2"]},
        # Targets g1 via group-only share
        {"shareId": "group-only", "email": "alice@example.com",
         "createdAt": "2026-04-22T11:00:00+00:00",
         "public": False, "groupIds": ["g1"]},
        # Does NOT target g1
        {"shareId": "other-group", "email": "alice@example.com",
         "createdAt": "2026-04-22T10:00:00+00:00",
         "public": False, "groupIds": ["g2"]},
        # Legacy public-only (no groupIds) -> not in g1's feed
        {"shareId": "legacy-public", "email": "alice@example.com",
         "createdAt": "2026-04-22T09:00:00+00:00"},
    ]

    response = handler(
        _event(authorized_event, {"groupId": "g1"}),
        mock_context,
    )

    assert response['statusCode'] == 200
    body = json.loads(response['body'])
    ids = {s['shareId'] for s in body['shares']}
    assert ids == {"dual", "group-only"}


@patch('lambdas.shares_feed.handler.query_feed_for_emails')
@patch('lambdas.shares_feed.handler.list_all_friends_for_user')
def test_shares_feed_legacy_rows_visible_on_public_feed(
    mock_friends, mock_query, mock_context, authorized_event
):
    """Rows written before the multi-target rollout have no `public` field
    and must stay visible on the public feed."""
    mock_friends.return_value = []
    mock_query.return_value = [
        {"shareId": "legacy-1", "email": "me@example.com",
         "createdAt": "2026-04-22T12:00:00+00:00"},
    ]

    response = handler(
        _event(authorized_event, {}),
        mock_context,
    )

    assert response['statusCode'] == 200
    body = json.loads(response['body'])
    assert [s['shareId'] for s in body['shares']] == ["legacy-1"]


@patch('lambdas.shares_feed.handler.query_feed_for_emails')
@patch('lambdas.shares_feed.handler.list_all_friends_for_user')
def test_shares_feed_limit_exceeds_max(
    mock_friends, mock_query, mock_context, authorized_event
):
    mock_friends.return_value = []
    response = handler(
        _event(authorized_event, {"limit": "500"}),
        mock_context,
    )
    assert response['statusCode'] == 400
    mock_query.assert_not_called()


# ------------------------------------------------------------------ Auth
@patch('lambdas.shares_feed.handler.list_all_friends_for_user')
def test_shares_feed_missing_caller_identity_returns_401(
    mock_friends, mock_context, api_gateway_event
):
    event = {
        **api_gateway_event,
        "httpMethod": "GET",
        "path": "/shares/feed",
        "queryStringParameters": {},
    }
    response = handler(event, mock_context)
    assert response['statusCode'] == 401
    mock_friends.assert_not_called()
