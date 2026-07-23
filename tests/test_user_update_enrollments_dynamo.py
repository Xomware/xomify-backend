"""
Tests for ``update_user_table_enrollments`` partial-update semantics.

The double-flag clobber bug: toggling one enrollment (Wrapped) used to
overwrite the sibling flag (Release Radar) because the helper always wrote
BOTH ``activeWrapped`` and ``activeReleaseRadar`` from whatever the caller
passed. A ``None`` argument now means "leave this flag exactly as it is in
the stored row" so a single-flag update can never clobber its sibling.
"""

from __future__ import annotations

from unittest.mock import patch

from lambdas.common import dynamo_helpers


@patch("lambdas.common.dynamo_helpers.update_table_item")
@patch("lambdas.common.dynamo_helpers.get_item_by_key")
def test_wrapped_only_update_preserves_release_radar(mock_get, mock_put):
    """Passing release_radar_enrolled=None keeps the stored radar flag."""
    mock_get.return_value = {
        "email": "u@example.com",
        "activeWrapped": False,
        "activeReleaseRadar": True,
    }

    result = dynamo_helpers.update_user_table_enrollments(
        "u@example.com", wrapped_enrolled=True, release_radar_enrolled=None
    )

    assert result["activeWrapped"] is True
    # Sibling flag untouched — the clobber regression guard.
    assert result["activeReleaseRadar"] is True
    written = mock_put.call_args.args[1]
    assert written["activeWrapped"] is True
    assert written["activeReleaseRadar"] is True


@patch("lambdas.common.dynamo_helpers.update_table_item")
@patch("lambdas.common.dynamo_helpers.get_item_by_key")
def test_radar_only_update_preserves_wrapped(mock_get, mock_put):
    """Passing wrapped_enrolled=None keeps the stored wrapped flag."""
    mock_get.return_value = {
        "email": "u@example.com",
        "activeWrapped": True,
        "activeReleaseRadar": False,
    }

    result = dynamo_helpers.update_user_table_enrollments(
        "u@example.com", wrapped_enrolled=None, release_radar_enrolled=True
    )

    assert result["activeReleaseRadar"] is True
    assert result["activeWrapped"] is True


@patch("lambdas.common.dynamo_helpers.update_table_item")
@patch("lambdas.common.dynamo_helpers.get_item_by_key")
def test_both_flags_update_when_provided(mock_get, mock_put):
    """Both flags still update together when both are provided (unchanged)."""
    mock_get.return_value = {
        "email": "u@example.com",
        "activeWrapped": True,
        "activeReleaseRadar": True,
    }

    result = dynamo_helpers.update_user_table_enrollments(
        "u@example.com", wrapped_enrolled=False, release_radar_enrolled=False
    )

    assert result["activeWrapped"] is False
    assert result["activeReleaseRadar"] is False
