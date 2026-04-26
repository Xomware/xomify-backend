"""
Tests for friends_profile lambda
"""

import pytest
import json
from unittest.mock import patch, AsyncMock
from lambdas.friends_profile.handler import handler


@patch('lambdas.friends_profile.handler.count_shares_for_user')
@patch('lambdas.friends_profile.handler.get_user_public_playlists')
@patch('lambdas.friends_profile.handler.get_user_top_items')
@patch('lambdas.friends_profile.handler.get_user_table_data')
def test_friends_profile_success(mock_get_user, mock_get_top_items, mock_get_playlists, mock_count, mock_context, api_gateway_event, sample_user, sample_top_items):
    """Test successful friend profile retrieval"""
    # Setup
    mock_get_user.return_value = sample_user
    # Mock the async coroutines
    mock_get_top_items.return_value = sample_top_items
    mock_get_playlists.return_value = []
    mock_count.return_value = 0

    event = {
        **api_gateway_event,
        "httpMethod": "GET",
        "path": "/friends/profile",
        "queryStringParameters": {"friendEmail": "friend@example.com"}
    }

    # Execute
    response = handler(event, mock_context)

    # Assert
    assert response['statusCode'] == 200
    body = json.loads(response['body'])
    assert body['email'] == 'friend@example.com'
    assert 'topSongs' in body
    assert 'topArtists' in body
    assert 'topGenres' in body
    assert 'playlists' in body
    assert body['playlists'] == []
    assert body['displayName'] == sample_user['displayName']


@patch('lambdas.friends_profile.handler.get_user_public_playlists')
@patch('lambdas.friends_profile.handler.get_user_top_items')
@patch('lambdas.friends_profile.handler.get_user_table_data')
def test_friends_profile_missing_email(mock_get_user, mock_get_top_items, mock_get_playlists, mock_context, api_gateway_event):
    """Test missing friendEmail parameter"""
    # Setup
    event = {
        **api_gateway_event,
        "httpMethod": "GET",
        "path": "/friends/profile",
        "queryStringParameters": {}
    }

    # Execute
    response = handler(event, mock_context)

    # Assert
    assert response['statusCode'] == 400


# --------------------------------------------------------------------
# shareCount + playlistCount regression
# --------------------------------------------------------------------
# Bug repro: iOS Profile header expects `shareCount` (and falls back to
# 3 stats when absent — see the ios-profile-redesign-contract). We add
# `shareCount` and `playlistCount` so the friend profile header renders
# the full 4-stat row. shareCount comes from a Select=COUNT GSI query;
# playlistCount mirrors the length of the public-playlists payload.
@patch('lambdas.friends_profile.handler.count_shares_for_user')
@patch('lambdas.friends_profile.handler.get_user_public_playlists')
@patch('lambdas.friends_profile.handler.get_user_top_items')
@patch('lambdas.friends_profile.handler.get_user_table_data')
def test_friends_profile_includes_share_and_playlist_counts(
    mock_get_user, mock_get_top_items, mock_get_playlists, mock_count,
    mock_context, api_gateway_event, sample_user, sample_top_items,
):
    mock_get_user.return_value = sample_user
    mock_get_top_items.return_value = sample_top_items
    mock_get_playlists.return_value = [
        {"id": "p1", "name": "Vibes"},
        {"id": "p2", "name": "Hype"},
    ]
    mock_count.return_value = 7

    event = {
        **api_gateway_event,
        "httpMethod": "GET",
        "path": "/friends/profile",
        "queryStringParameters": {"friendEmail": "friend@example.com"},
    }
    response = handler(event, mock_context)

    assert response['statusCode'] == 200
    body = json.loads(response['body'])
    assert body['shareCount'] == 7
    assert body['playlistCount'] == 2
    mock_count.assert_called_once_with("friend@example.com")


@patch('lambdas.friends_profile.handler.count_shares_for_user')
@patch('lambdas.friends_profile.handler.get_user_public_playlists')
@patch('lambdas.friends_profile.handler.get_user_top_items')
@patch('lambdas.friends_profile.handler.get_user_table_data')
def test_friends_profile_share_count_failure_does_not_500(
    mock_get_user, mock_get_top_items, mock_get_playlists, mock_count,
    mock_context, api_gateway_event, sample_user, sample_top_items,
):
    """If the GSI count scan fails, profile still loads sans shareCount."""
    mock_get_user.return_value = sample_user
    mock_get_top_items.return_value = sample_top_items
    mock_get_playlists.return_value = []
    mock_count.side_effect = RuntimeError("DDB throttled")

    event = {
        **api_gateway_event,
        "httpMethod": "GET",
        "path": "/friends/profile",
        "queryStringParameters": {"friendEmail": "friend@example.com"},
    }
    response = handler(event, mock_context)

    assert response['statusCode'] == 200
    body = json.loads(response['body'])
    # Field omitted on lookup failure — iOS treats absence as "unknown".
    assert 'shareCount' not in body
    # playlistCount still present (derived from playlists list length).
    assert body['playlistCount'] == 0


# --------------------------------------------------------------------
# likesCount enrichment (Phase 4)
# --------------------------------------------------------------------
# Friends should see a target's likesCount when the target has
# likes_public=True (default). Self always sees their own count.
# Private targets cause the field to be omitted (iOS hides the chip).
@patch('lambdas.friends_profile.handler.get_likes_settings')
@patch('lambdas.friends_profile.handler.count_shares_for_user')
@patch('lambdas.friends_profile.handler.get_user_public_playlists')
@patch('lambdas.friends_profile.handler.get_user_top_items')
@patch('lambdas.friends_profile.handler.get_user_table_data')
def test_friends_profile_includes_likes_count_when_public(
    mock_get_user, mock_get_top_items, mock_get_playlists, mock_count, mock_likes,
    mock_context, authorized_event, sample_user, sample_top_items,
):
    mock_get_user.return_value = sample_user
    mock_get_top_items.return_value = sample_top_items
    mock_get_playlists.return_value = []
    mock_count.return_value = 0
    mock_likes.return_value = {
        "likes_count": 42,
        "likes_updated_at": "2025-04-26T00:00:00+00:00",
        "likes_public": True,
    }

    event = authorized_event(
        email="caller@example.com",
        httpMethod="GET",
        path="/friends/profile",
        queryStringParameters={"friendEmail": "friend@example.com"},
    )
    response = handler(event, mock_context)

    assert response['statusCode'] == 200
    body = json.loads(response['body'])
    assert body['likesCount'] == 42


@patch('lambdas.friends_profile.handler.get_likes_settings')
@patch('lambdas.friends_profile.handler.count_shares_for_user')
@patch('lambdas.friends_profile.handler.get_user_public_playlists')
@patch('lambdas.friends_profile.handler.get_user_top_items')
@patch('lambdas.friends_profile.handler.get_user_table_data')
def test_friends_profile_omits_likes_count_when_private_and_not_self(
    mock_get_user, mock_get_top_items, mock_get_playlists, mock_count, mock_likes,
    mock_context, authorized_event, sample_user, sample_top_items,
):
    mock_get_user.return_value = sample_user
    mock_get_top_items.return_value = sample_top_items
    mock_get_playlists.return_value = []
    mock_count.return_value = 0
    mock_likes.return_value = {
        "likes_count": 42,
        "likes_updated_at": "2025-04-26T00:00:00+00:00",
        "likes_public": False,
    }

    event = authorized_event(
        email="caller@example.com",
        httpMethod="GET",
        path="/friends/profile",
        queryStringParameters={"friendEmail": "friend@example.com"},
    )
    response = handler(event, mock_context)

    assert response['statusCode'] == 200
    body = json.loads(response['body'])
    assert 'likesCount' not in body


@patch('lambdas.friends_profile.handler.get_likes_settings')
@patch('lambdas.friends_profile.handler.count_shares_for_user')
@patch('lambdas.friends_profile.handler.get_user_public_playlists')
@patch('lambdas.friends_profile.handler.get_user_top_items')
@patch('lambdas.friends_profile.handler.get_user_table_data')
def test_friends_profile_includes_likes_count_for_self_even_if_private(
    mock_get_user, mock_get_top_items, mock_get_playlists, mock_count, mock_likes,
    mock_context, authorized_event, sample_user, sample_top_items,
):
    mock_get_user.return_value = sample_user
    mock_get_top_items.return_value = sample_top_items
    mock_get_playlists.return_value = []
    mock_count.return_value = 0
    mock_likes.return_value = {
        "likes_count": 7,
        "likes_updated_at": "ts",
        "likes_public": False,
    }

    event = authorized_event(
        email="me@example.com",
        httpMethod="GET",
        path="/friends/profile",
        queryStringParameters={"friendEmail": "me@example.com"},
    )
    response = handler(event, mock_context)

    assert response['statusCode'] == 200
    body = json.loads(response['body'])
    assert body['likesCount'] == 7


@patch('lambdas.friends_profile.handler.get_likes_settings')
@patch('lambdas.friends_profile.handler.count_shares_for_user')
@patch('lambdas.friends_profile.handler.get_user_public_playlists')
@patch('lambdas.friends_profile.handler.get_user_top_items')
@patch('lambdas.friends_profile.handler.get_user_table_data')
def test_friends_profile_likes_lookup_failure_does_not_500(
    mock_get_user, mock_get_top_items, mock_get_playlists, mock_count, mock_likes,
    mock_context, authorized_event, sample_user, sample_top_items,
):
    """A DDB hiccup on the likes lookup must not break the whole profile."""
    mock_get_user.return_value = sample_user
    mock_get_top_items.return_value = sample_top_items
    mock_get_playlists.return_value = []
    mock_count.return_value = 0
    mock_likes.side_effect = RuntimeError("DDB throttled")

    event = authorized_event(
        email="caller@example.com",
        httpMethod="GET",
        path="/friends/profile",
        queryStringParameters={"friendEmail": "friend@example.com"},
    )
    response = handler(event, mock_context)

    assert response['statusCode'] == 200
    body = json.loads(response['body'])
    assert 'likesCount' not in body
