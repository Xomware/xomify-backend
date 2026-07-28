"""
Tests for broadcasts_dynamo active filtering and the broadcasts_active handler.
"""

import json
from datetime import datetime, timedelta, timezone
from unittest.mock import patch

from lambdas.common import broadcasts_dynamo


def _now():
    return datetime.now(timezone.utc)


def test_is_active_null_active_until():
    assert broadcasts_dynamo.is_active({"activeUntil": None}) is True
    assert broadcasts_dynamo.is_active({}) is True


def test_is_active_future_is_active():
    future = (_now() + timedelta(days=1)).isoformat()
    assert broadcasts_dynamo.is_active({"activeUntil": future}) is True


def test_is_active_past_is_inactive():
    past = (_now() - timedelta(days=1)).isoformat()
    assert broadcasts_dynamo.is_active({"activeUntil": past}) is False


def test_is_active_unparseable_defaults_active():
    assert broadcasts_dynamo.is_active({"activeUntil": "not-a-date"}) is True


@patch("lambdas.common.broadcasts_dynamo.full_table_scan")
def test_get_active_broadcasts_filters(mock_scan):
    future = (_now() + timedelta(days=1)).isoformat()
    past = (_now() - timedelta(days=1)).isoformat()
    mock_scan.return_value = [
        {"broadcastId": "b1", "activeUntil": None},
        {"broadcastId": "b2", "activeUntil": future},
        {"broadcastId": "b3", "activeUntil": past},
    ]

    active = broadcasts_dynamo.get_active_broadcasts()
    ids = {b["broadcastId"] for b in active}
    assert ids == {"b1", "b2"}


@patch("lambdas.broadcasts_active.handler.get_active_broadcasts")
def test_broadcasts_active_handler_shape(mock_active, authorized_event, mock_context):
    from lambdas.broadcasts_active.handler import handler

    mock_active.return_value = [
        {
            "broadcastId": "b1",
            "title": "Heads up",
            "body": "New feature",
            "activeUntil": None,
            "createdAt": "2026-01-01T00:00:00+00:00",
            "createdBy": "admin@example.com",
        }
    ]

    response = handler(authorized_event(httpMethod="GET"), mock_context)

    assert response["statusCode"] == 200
    body = json.loads(response["body"])
    assert len(body["broadcasts"]) == 1
    b = body["broadcasts"][0]
    # createdBy is NOT exposed on the public active endpoint.
    assert set(b.keys()) == {"id", "title", "body", "activeUntil", "createdAt"}
    assert b["id"] == "b1"


def test_broadcasts_active_missing_identity_is_401(mock_context, legacy_event):
    from lambdas.broadcasts_active.handler import handler

    response = handler(legacy_event(), mock_context)
    assert response["statusCode"] == 401
