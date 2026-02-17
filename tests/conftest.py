"""
Shared pytest fixtures for lambda tests
"""

import pytest
import os
import sys
from unittest.mock import MagicMock

# Add lambdas to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

# Set required env vars before any lambda modules are imported
_TEST_ENV_VARS = {
    "AWS_DEFAULT_REGION": "us-east-1",
    "DYNAMODB_KMS_ALIAS": "alias/xomify-kms-test",
    "USERS_TABLE_NAME": "xomify-users-test",
    "WRAPPED_HISTORY_TABLE_NAME": "xomify-wrapped-history-test",
    "RELEASE_RADAR_HISTORY_TABLE_NAME": "xomify-release-radar-history-test",
    "FRIENDSHIPS_TABLE_NAME": "xomify-friendships-test",
    "GROUPS_TABLE_NAME": "xomify-groups-test",
    "GROUP_MEMBERS_TABLE_NAME": "xomify-group-members-test",
    "GROUP_TRACKS_TABLE_NAME": "xomify-group-tracks-test",
    "TRACK_RATINGS_TABLE_NAME": "xomify-track-ratings-test",
}
for key, value in _TEST_ENV_VARS.items():
    os.environ.setdefault(key, value)

# Mock ssm_helpers BEFORE any lambda modules import it.
# ssm_helpers.py makes real AWS SSM API calls at module level which will
# fail in CI without credentials. We inject a fake module into sys.modules
# so any `from lambdas.common.ssm_helpers import ...` gets test values.
import types
_mock_ssm = types.ModuleType("lambdas.common.ssm_helpers")
_mock_ssm.SPOTIFY_CLIENT_ID = "test-spotify-client-id"
_mock_ssm.SPOTIFY_CLIENT_SECRET = "test-spotify-client-secret"
_mock_ssm.AWS_ACCESS_KEY = "test-aws-access-key"
_mock_ssm.AWS_SECRET_KEY = "test-aws-secret-key"
_mock_ssm.API_SECRET_KEY = "test-api-secret-key"
sys.modules["lambdas.common.ssm_helpers"] = _mock_ssm


@pytest.fixture
def mock_context():
    """Mock AWS Lambda context"""
    context = MagicMock()
    context.function_name = "test-function"
    context.memory_limit_in_mb = 128
    context.invoked_function_arn = "arn:aws:lambda:us-east-1:123456789012:function:test-function"
    context.aws_request_id = "test-request-id"
    return context


@pytest.fixture
def api_gateway_event():
    """Base API Gateway event structure"""
    return {
        "httpMethod": "GET",
        "path": "/test",
        "queryStringParameters": {},
        "headers": {
            "Content-Type": "application/json"
        },
        "body": None,
        "isBase64Encoded": False
    }


@pytest.fixture
def sample_user():
    """Sample user data"""
    return {
        "email": "test@example.com",
        "userId": "spotify123",
        "displayName": "Test User",
        "refreshToken": "mock-refresh-token",
        "avatar": "https://example.com/avatar.jpg",
        "active": True,
        "activeWrapped": True,
        "activeReleaseRadar": True
    }


@pytest.fixture
def sample_friendship():
    """Sample friendship data"""
    return {
        "user1": "user1@example.com",
        "user2": "user2@example.com",
        "status": "accepted",
        "direction": "outgoing",
        "createdAt": "2024-01-01 00:00:00"
    }


@pytest.fixture
def sample_top_items():
    """Sample Spotify top items"""
    return {
        "tracks": {
            "short_term": [
                {
                    "id": "track1",
                    "name": "Test Song",
                    "artists": [{"name": "Test Artist"}],
                    "uri": "spotify:track:track1"
                }
            ],
            "medium_term": [],
            "long_term": []
        },
        "artists": {
            "short_term": [
                {
                    "id": "artist1",
                    "name": "Test Artist",
                    "genres": ["pop", "rock"],
                    "uri": "spotify:artist:artist1"
                }
            ],
            "medium_term": [],
            "long_term": []
        },
        "genres": {
            "short_term": {"pop": 10, "rock": 5},
            "medium_term": {},
            "long_term": {}
        }
    }
