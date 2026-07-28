"""
Tests for the shared instrumentation hooks:
- request-log hook baked into @handle_errors
- notification-log recording in the SES send helpers
"""

from unittest.mock import patch, MagicMock

import pytest

from lambdas.common.errors import handle_errors


def _http_event(email="test@example.com", method="GET", path="/thing"):
    return {
        "httpMethod": method,
        "resource": path,
        "path": path,
        "queryStringParameters": {},
        "headers": {},
        "body": None,
        "requestContext": {"authorizer": {"email": email, "userId": "u1"}},
    }


# ============================================
# request-log hook
# ============================================

@patch("lambdas.common.request_log_dynamo.upsert_last_seen")
@patch("lambdas.common.request_log_dynamo.record_request")
@patch("lambdas.common.constants.REQUEST_LOG_TABLE_NAME", "xomify-request-log-test")
def test_hook_logs_success(mock_record, mock_seen, mock_context):
    @handle_errors("dummy")
    def handler(event, context):
        from lambdas.common.utility_helpers import success_response
        return success_response({"ok": True})

    handler(_http_event(path="/user/data"), mock_context)

    kwargs = mock_record.call_args.kwargs
    assert kwargs["path"] == "/user/data"
    assert kwargs["method"] == "GET"
    assert kwargs["status"] == 200
    assert kwargs["email"] == "test@example.com"
    assert kwargs["error"] is None
    assert isinstance(kwargs["duration_ms"], int)
    mock_seen.assert_called_once_with("test@example.com")


@patch("lambdas.common.request_log_dynamo.upsert_last_seen")
@patch("lambdas.common.request_log_dynamo.record_request")
@patch("lambdas.common.constants.REQUEST_LOG_TABLE_NAME", "xomify-request-log-test")
def test_hook_logs_error_status(mock_record, mock_seen, mock_context):
    from lambdas.common.errors import ValidationError

    @handle_errors("dummy")
    def handler(event, context):
        raise ValidationError("bad", handler="dummy", field="x")

    resp = handler(_http_event(), mock_context)
    assert resp["statusCode"] == 400

    kwargs = mock_record.call_args.kwargs
    assert kwargs["status"] == 400
    assert kwargs["error"] == "bad"


@patch("lambdas.common.request_log_dynamo.record_request")
@patch("lambdas.common.constants.REQUEST_LOG_TABLE_NAME", "xomify-request-log-test")
def test_hook_noop_for_cron_event(mock_record, mock_context):
    @handle_errors("dummy")
    def handler(event, context):
        from lambdas.common.utility_helpers import success_response
        return success_response({"ok": True}, is_api=False)

    handler({"source": "aws.events"}, mock_context)
    mock_record.assert_not_called()


@patch("lambdas.common.request_log_dynamo.record_request")
@patch("lambdas.common.constants.REQUEST_LOG_TABLE_NAME", "")
def test_hook_noop_when_table_unset(mock_record, mock_context):
    @handle_errors("dummy")
    def handler(event, context):
        from lambdas.common.utility_helpers import success_response
        return success_response({"ok": True})

    handler(_http_event(), mock_context)
    mock_record.assert_not_called()


# ============================================
# SES notification recording
# ============================================

@patch("lambdas.common.ses_helper.record_notification")
@patch("lambdas.common.ses_helper.ses_client")
def test_favorites_reminder_records_sent(mock_ses, mock_record):
    from lambdas.common.ses_helper import send_favorites_reminder_email

    mock_ses.send_email.return_value = {"MessageId": "mid"}
    assert send_favorites_reminder_email("u@x.com", "U", 2026) is True

    kwargs = mock_record.call_args.kwargs
    assert kwargs["channel"] == "email"
    assert kwargs["to_email"] == "u@x.com"
    assert kwargs["status"] == "sent"


@patch("lambdas.common.ses_helper.record_notification")
@patch("lambdas.common.ses_helper.ses_client")
def test_favorites_reminder_records_failed_and_raises(mock_ses, mock_record):
    from lambdas.common.ses_helper import send_favorites_reminder_email

    mock_ses.send_email.side_effect = RuntimeError("smtp down")
    with pytest.raises(Exception):
        send_favorites_reminder_email("u@x.com", "U", 2026)

    kwargs = mock_record.call_args.kwargs
    assert kwargs["status"] == "failed"
    assert "smtp down" in kwargs["error"]
