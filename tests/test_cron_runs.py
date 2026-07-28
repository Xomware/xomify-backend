"""
Tests for record_cron_run (cron-run instrumentation wrapper).
"""

from unittest.mock import patch

import pytest

from lambdas.common.cron_runs_dynamo import record_cron_run


@patch("lambdas.common.cron_runs_dynamo._write_run")
def test_record_cron_run_ok_writes_and_returns(mock_write):
    result = record_cron_run("wrapped", lambda: "RESPONSE", items=7)
    assert result == "RESPONSE"
    args = mock_write.call_args.args
    # (cron_name, started_at, finished_at, status, error, items)
    assert args[0] == "wrapped"
    assert args[3] == "ok"
    assert args[4] is None
    assert args[5] == 7


@patch("lambdas.common.cron_runs_dynamo._write_run")
def test_record_cron_run_items_callable(mock_write):
    holder = {}

    def _fn():
        holder["items"] = 3
        return "R"

    record_cron_run("release-radar", _fn, items=lambda: holder.get("items"))
    assert mock_write.call_args.args[5] == 3


@patch("lambdas.common.cron_runs_dynamo._write_run")
def test_record_cron_run_error_writes_and_reraises(mock_write):
    def _boom():
        raise ValueError("kaboom")

    with pytest.raises(ValueError, match="kaboom"):
        record_cron_run("wrapped", _boom, items=lambda: 5)

    args = mock_write.call_args.args
    assert args[3] == "error"
    assert "kaboom" in args[4]
    # callable items are not evaluated on the error path
    assert args[5] is None


def test_record_cron_run_write_failure_is_fail_open():
    # _write_run swallows its own DynamoDB errors; a successful fn still returns
    # even if CRON_RUNS_TABLE_NAME is unset (no-op write).
    assert record_cron_run("wrapped", lambda: "ok") == "ok"
