"""
Tests for shares_user lambda
"""

import json
from unittest.mock import patch

from lambdas.shares_user.handler import handler


def _event(api_gateway_event, params):
    return {
        **api_gateway_event,
        "httpMethod": "GET",
        "path": "/shares/user",
        "queryStringParameters": params,
    }


@patch('lambdas.shares_user.handler.list_shares_for_user')
def test_shares_user_happy_path(mock_list, mock_context, api_gateway_event):
    mock_list.return_value = (
        [
            {"shareId": "1", "email": "target@example.com", "createdAt": "2026-04-22T12:00:00+00:00"},
            {"shareId": "2", "email": "target@example.com", "createdAt": "2026-04-21T12:00:00+00:00"},
        ],
        None,
    )

    response = handler(
        _event(api_gateway_event, {"email": "me@example.com", "targetEmail": "target@example.com"}),
        mock_context,
    )

    assert response['statusCode'] == 200
    body = json.loads(response['body'])
    assert len(body['shares']) == 2
    assert body['nextBefore'] is None
    mock_list.assert_called_once_with("target@example.com", limit=50, before=None)


@patch('lambdas.shares_user.handler.list_shares_for_user')
def test_shares_user_pagination_cursor(mock_list, mock_context, api_gateway_event):
    mock_list.return_value = ([], "2026-04-20T00:00:00+00:00")

    response = handler(
        _event(api_gateway_event, {
            "email": "me@example.com",
            "targetEmail": "target@example.com",
            "limit": "10",
            "before": "2026-04-22T00:00:00+00:00",
        }),
        mock_context,
    )

    assert response['statusCode'] == 200
    body = json.loads(response['body'])
    assert body['nextBefore'] == "2026-04-20T00:00:00+00:00"
    mock_list.assert_called_once_with(
        "target@example.com", limit=10, before="2026-04-22T00:00:00+00:00"
    )


@patch('lambdas.shares_user.handler.list_shares_for_user')
def test_shares_user_missing_target(mock_list, mock_context, api_gateway_event):
    response = handler(
        _event(api_gateway_event, {"email": "me@example.com"}),
        mock_context,
    )
    assert response['statusCode'] == 400
    mock_list.assert_not_called()


@patch('lambdas.shares_user.handler.list_shares_for_user')
def test_shares_user_limit_exceeds_max(mock_list, mock_context, api_gateway_event):
    response = handler(
        _event(api_gateway_event, {
            "email": "me@example.com",
            "targetEmail": "target@example.com",
            "limit": "500",
        }),
        mock_context,
    )
    assert response['statusCode'] == 400
    mock_list.assert_not_called()


@patch('lambdas.shares_user.handler.build_enrichment')
@patch('lambdas.shares_user.handler.list_shares_for_user')
def test_shares_user_hides_group_only_shares(
    mock_list, mock_enrich, mock_context, api_gateway_event
):
    """Profile view only surfaces public shares — group-only rows stay scoped
    to their group feeds. Legacy rows (no `public` field) remain visible."""
    mock_enrich.return_value = {
        "queuedCount": 0, "ratedCount": 0,
        "viewerHasQueued": False, "viewerRating": None, "sharerRating": None,
    }
    mock_list.return_value = (
        [
            # Legacy row — default visible
            {"shareId": "legacy", "email": "target@example.com",
             "createdAt": "2026-04-22T12:00:00+00:00"},
            # Dual share — public=True + groups -> visible
            {"shareId": "dual", "email": "target@example.com",
             "createdAt": "2026-04-22T11:00:00+00:00",
             "public": True, "groupIds": ["g1"]},
            # Group-only — must be hidden
            {"shareId": "group-only", "email": "target@example.com",
             "createdAt": "2026-04-22T10:00:00+00:00",
             "public": False, "groupIds": ["g1"]},
        ],
        None,
    )

    response = handler(
        _event(api_gateway_event, {
            "email": "me@example.com", "targetEmail": "target@example.com",
        }),
        mock_context,
    )

    assert response['statusCode'] == 200
    body = json.loads(response['body'])
    ids = {s['shareId'] for s in body['shares']}
    assert ids == {"legacy", "dual"}
