"""
Tests for shares_feed lambda
"""

import json
from unittest.mock import patch

from lambdas.shares_feed.handler import handler


def _event(api_gateway_event, params):
    return {
        **api_gateway_event,
        "httpMethod": "GET",
        "path": "/shares/feed",
        "queryStringParameters": params,
    }


@patch('lambdas.shares_feed.handler.query_feed_for_emails')
@patch('lambdas.shares_feed.handler.list_all_friends_for_user')
def test_shares_feed_happy_path(mock_friends, mock_query, mock_context, api_gateway_event):
    mock_friends.return_value = [
        {"friendEmail": "alice@example.com", "status": "accepted"},
        {"friendEmail": "bob@example.com", "status": "accepted"},
        {"friendEmail": "blocked@example.com", "status": "blocked"},
    ]
    mock_query.return_value = [
        {"shareId": "1", "email": "alice@example.com", "createdAt": "2026-04-22T12:00:00+00:00"},
        {"shareId": "2", "email": "me@example.com", "createdAt": "2026-04-22T11:00:00+00:00"},
    ]

    response = handler(_event(api_gateway_event, {"email": "me@example.com"}), mock_context)

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
def test_shares_feed_empty_friends(mock_friends, mock_query, mock_context, api_gateway_event):
    mock_friends.return_value = []
    mock_query.return_value = []

    response = handler(_event(api_gateway_event, {"email": "solo@example.com"}), mock_context)

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
    mock_friends, mock_query, mock_members, mock_context, api_gateway_event
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
        _event(api_gateway_event, {"email": "me@example.com", "groupId": "g1"}),
        mock_context,
    )

    emails_arg = mock_query.call_args.args[0]
    # Intersection of {me, alice, bob} with {alice, me, unrelated} = {me, alice}
    assert set(emails_arg) == {"me@example.com", "alice@example.com"}


@patch('lambdas.shares_feed.handler.query_feed_for_emails')
@patch('lambdas.shares_feed.handler.list_all_friends_for_user')
def test_shares_feed_limit_exceeds_max(
    mock_friends, mock_query, mock_context, api_gateway_event
):
    mock_friends.return_value = []
    response = handler(
        _event(api_gateway_event, {"email": "me@example.com", "limit": "500"}),
        mock_context,
    )
    assert response['statusCode'] == 400
    mock_query.assert_not_called()


@patch('lambdas.shares_feed.handler.list_all_friends_for_user')
def test_shares_feed_missing_email(mock_friends, mock_context, api_gateway_event):
    response = handler(_event(api_gateway_event, {}), mock_context)
    assert response['statusCode'] == 400
    mock_friends.assert_not_called()
