"""
Tests for friends_profile lambda
"""

import pytest
import json
from unittest.mock import patch, AsyncMock
from lambdas.friends_profile.handler import handler


@patch('lambdas.friends_profile.handler.get_user_public_playlists')
@patch('lambdas.friends_profile.handler.get_user_top_items')
@patch('lambdas.friends_profile.handler.get_user_table_data')
def test_friends_profile_success(mock_get_user, mock_get_top_items, mock_get_playlists, mock_context, api_gateway_event, sample_user, sample_top_items):
    """Test successful friend profile retrieval"""
    # Setup
    mock_get_user.return_value = sample_user
    # Mock the async coroutines
    mock_get_top_items.return_value = sample_top_items
    mock_get_playlists.return_value = []

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
