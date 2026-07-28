"""
Tests for the year-end favorites reminder cron.

Covers: active-only targeting, per-year idempotency via the REMINDER marker,
and per-user send-failure isolation.
"""

import json
from unittest.mock import patch


def _cron_event():
    return {"source": "aws.events"}


@patch("lambdas.cron_favorites_reminder.handler.put_reminder_marker")
@patch("lambdas.cron_favorites_reminder.handler.send_favorites_reminder_email")
@patch("lambdas.cron_favorites_reminder.handler.get_reminder_marker")
@patch("lambdas.cron_favorites_reminder.handler.full_table_scan")
def test_cron_sends_skips_and_fails(
    mock_scan, mock_marker, mock_send, mock_put, mock_context
):
    from lambdas.cron_favorites_reminder.handler import handler

    mock_scan.return_value = [
        {"email": "a@e.com", "displayName": "A", "active": True},   # sent
        {"email": "b@e.com", "displayName": "B", "active": True},   # already sent -> skip
        {"email": "c@e.com", "displayName": "C", "active": True},   # send fails
        {"email": "d@e.com", "displayName": "D", "active": False},  # inactive -> ignored
        {"displayName": "no-email", "active": True},                 # no email -> ignored
    ]

    # b already has a marker; others don't.
    mock_marker.side_effect = lambda email, year: {"sentAt": "x"} if email == "b@e.com" else None

    def _send(email, name, year):
        if email == "c@e.com":
            raise Exception("SES down")
        return True

    mock_send.side_effect = _send

    response = handler(_cron_event(), mock_context)

    # Cron responses are is_api=False -> body is a raw dict, not JSON string.
    body = response["body"]
    assert body == {"successfulEmails": 1, "failedEmails": 1, "skipped": 1}

    # Marker only written for the successful send (a), never for the failed one (c).
    from datetime import datetime, timezone
    current_year = datetime.now(timezone.utc).year
    mock_put.assert_called_once_with("a@e.com", current_year)


@patch("lambdas.cron_favorites_reminder.handler.put_reminder_marker")
@patch("lambdas.cron_favorites_reminder.handler.send_favorites_reminder_email")
@patch("lambdas.cron_favorites_reminder.handler.get_reminder_marker")
@patch("lambdas.cron_favorites_reminder.handler.full_table_scan")
def test_cron_all_already_sent_are_skipped(
    mock_scan, mock_marker, mock_send, mock_put, mock_context
):
    from lambdas.cron_favorites_reminder.handler import handler

    mock_scan.return_value = [{"email": "a@e.com", "active": True}]
    mock_marker.return_value = {"sentAt": "x"}

    response = handler(_cron_event(), mock_context)

    assert response["body"] == {"successfulEmails": 0, "failedEmails": 0, "skipped": 1}
    mock_send.assert_not_called()
    mock_put.assert_not_called()
