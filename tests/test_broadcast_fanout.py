"""
Tests for the admin-broadcast fan-out (B4 leftover).

The point of this lambda is that the work happens OFF the admin's request
path, so the two things worth guarding are: the request handler dispatches
asynchronously and never blocks, and the fan-out itself respects the same
`active` gate every other user-wide send uses.
"""

import json
from unittest.mock import MagicMock, patch


def _admin_event(body):
    return {
        "body": json.dumps(body),
        "requestContext": {"authorizer": {"email": "admin@example.com"}},
    }


# ── Fan-out lambda ──────────────────────────────────────────────────────

@patch("lambdas.notifications_broadcast_fanout.handler.notify")
@patch("lambdas.notifications_broadcast_fanout.handler.full_table_scan")
def test_fanout_notifies_only_active_users(mock_scan, mock_notify, mock_context):
    from lambdas.notifications_broadcast_fanout.handler import handler

    mock_scan.return_value = [
        {"email": "a@e.com", "active": True},
        {"email": "b@e.com", "active": False},   # inactive -> skipped
        {"active": True},                         # no email -> skipped
        {"email": "c@e.com", "active": True},
    ]

    response = handler({"broadcastId": "b1", "title": "T", "body": "B"}, mock_context)
    # is_api=False, so `body` is the raw dict rather than a JSON string.
    data = response["body"]

    assert data["notified"] == 2
    assert data["skipped"] == 2
    assert {c.args[1] for c in mock_notify.call_args_list} == {"a@e.com", "c@e.com"}
    assert mock_notify.call_args.args[0] == "broadcast"


@patch("lambdas.notifications_broadcast_fanout.handler.notify")
@patch("lambdas.notifications_broadcast_fanout.handler.full_table_scan")
def test_fanout_is_capped(mock_scan, mock_notify, mock_context):
    """A runaway scan should truncate loudly, not time out delivering nothing."""
    from lambdas.notifications_broadcast_fanout.handler import handler, MAX_RECIPIENTS

    mock_scan.return_value = [
        {"email": f"u{i}@e.com", "active": True} for i in range(MAX_RECIPIENTS + 20)
    ]
    handler({"broadcastId": "b1", "title": "T", "body": "B"}, mock_context)
    assert mock_notify.call_count == MAX_RECIPIENTS


@patch("lambdas.notifications_broadcast_fanout.handler.full_table_scan")
def test_fanout_requires_title_and_body(mock_scan, mock_context):
    from lambdas.notifications_broadcast_fanout.handler import handler

    response = handler({"broadcastId": "b1"}, mock_context)
    assert response["statusCode"] == 400


# ── Request handler dispatches, never blocks ────────────────────────────

@patch("lambdas.admin_broadcasts_create.handler._lambda_client")
@patch("lambdas.admin_broadcasts_create.handler.put_broadcast")
@patch("lambdas.admin_broadcasts_create.handler.require_admin")
def test_create_dispatches_fanout_asynchronously(mock_admin, mock_put, mock_client, mock_context):
    from lambdas.admin_broadcasts_create.handler import handler

    mock_admin.return_value = "admin@example.com"
    handler(_admin_event({"title": "Heads up", "body": "New release", "activeUntil": None}), mock_context)

    assert mock_client.invoke.call_count == 1
    kwargs = mock_client.invoke.call_args.kwargs
    # Event, not RequestResponse — the admin must not wait on a users-table scan.
    assert kwargs["InvocationType"] == "Event"
    payload = json.loads(kwargs["Payload"].decode("utf-8"))
    assert payload["title"] == "Heads up"


@patch("lambdas.admin_broadcasts_create.handler._lambda_client")
@patch("lambdas.admin_broadcasts_create.handler.put_broadcast")
@patch("lambdas.admin_broadcasts_create.handler.require_admin")
def test_create_survives_a_failed_dispatch(mock_admin, mock_put, mock_client, mock_context):
    """The broadcast row is already persisted — a failed push must not 500 it."""
    from lambdas.admin_broadcasts_create.handler import handler

    mock_admin.return_value = "admin@example.com"
    mock_client.invoke.side_effect = RuntimeError("lambda unavailable")

    response = handler(_admin_event({"title": "T", "body": "B", "activeUntil": None}), mock_context)
    assert response["statusCode"] == 200


# ── Envelope-collision regression ───────────────────────────────────────

def test_coerce_event_does_not_eat_a_prose_body(mock_context):
    """
    REGRESSION. The direct-invoke payload has its own `body` key — the
    notification's text — which collides with API Gateway's `body` envelope.
    The original `_coerce_event` saw a string, tried `json.loads` on ordinary
    prose, failed, and returned `{}`. Every direct invoke was then rejected as
    missing required fields, so NOTHING EVER SENT.
    """
    from lambdas.notifications_send.handler import _coerce_event

    event = {
        "kind": "queue_threshold",
        "email": "r@e.com",
        "title": "Your share is heating up",
        "body": "3 friends have queued Midnight City",
    }
    assert _coerce_event(event) == event


def test_coerce_event_still_unwraps_a_real_api_gateway_envelope(mock_context):
    from lambdas.notifications_send.handler import _coerce_event

    inner = {"kind": "digest", "email": "r@e.com", "title": "T", "body": "B"}
    assert _coerce_event({"body": json.dumps(inner)}) == inner


def test_coerce_event_ignores_a_json_scalar_body(mock_context):
    """`body: "42"` parses as JSON but is text, not an envelope."""
    from lambdas.notifications_send.handler import _coerce_event

    event = {"kind": "digest", "email": "r@e.com", "title": "T", "body": "42"}
    assert _coerce_event(event) == event
