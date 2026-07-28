"""
Tests for ses_helper.send_favorites_reminder_email.
"""

from unittest.mock import MagicMock, patch

from botocore.exceptions import ClientError

import pytest

from lambdas.common import ses_helper


@patch("lambdas.common.ses_helper.ses_client")
def test_send_favorites_reminder_success(mock_ses):
    mock_ses.send_email.return_value = {"MessageId": "mid-123"}

    ok = ses_helper.send_favorites_reminder_email("u@e.com", "Dom", 2026)

    assert ok is True
    mock_ses.send_email.assert_called_once()
    kwargs = mock_ses.send_email.call_args.kwargs
    assert kwargs["Destination"]["ToAddresses"] == ["u@e.com"]
    assert kwargs["Message"]["Subject"]["Data"] == "Set your 2026 favorites"
    # Both HTML and text parts reference the year.
    assert "2026" in kwargs["Message"]["Body"]["Html"]["Data"]
    assert "2026" in kwargs["Message"]["Body"]["Text"]["Data"]
    assert "Dom" in kwargs["Message"]["Body"]["Text"]["Data"]


@patch("lambdas.common.ses_helper.ses_client")
def test_send_favorites_reminder_raises_on_client_error(mock_ses):
    mock_ses.send_email.side_effect = ClientError(
        {"Error": {"Code": "MessageRejected", "Message": "bad"}}, "SendEmail"
    )

    with pytest.raises(Exception):
        ses_helper.send_favorites_reminder_email("u@e.com", "Dom", 2026)
