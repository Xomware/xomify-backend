"""
Tests for share_visibility helper.

Covers the rule + the regression hardening (transient DDB failures on
membership lookup must not bubble as 500 — they're treated as "not a
member" and we move on).
"""

from __future__ import annotations

from unittest.mock import patch

from lambdas.common.share_visibility import viewer_can_see_share


def _share(public=True, author="alice@example.com", group_ids=None):
    return {
        "shareId": "share-1",
        "email": author,
        "public": public,
        "groupIds": group_ids or [],
    }


# ---------------------------------------------------------------- Rule basics
def test_public_share_is_visible_to_anyone():
    assert viewer_can_see_share(_share(public=True), "stranger@example.com") is True


def test_missing_share_is_not_visible():
    assert viewer_can_see_share({}, "anyone@example.com") is False
    assert viewer_can_see_share(None, "anyone@example.com") is False  # type: ignore[arg-type]


def test_private_share_visible_to_author():
    share = _share(public=False, author="alice@example.com", group_ids=["g1"])
    assert viewer_can_see_share(share, "alice@example.com") is True


@patch("lambdas.common.share_visibility.is_member_of_group")
def test_private_share_visible_to_group_member(mock_member):
    mock_member.return_value = True
    share = _share(public=False, author="alice@example.com", group_ids=["g1"])
    assert viewer_can_see_share(share, "bob@example.com") is True
    mock_member.assert_called_once_with("bob@example.com", "g1")


@patch("lambdas.common.share_visibility.is_member_of_group")
def test_private_share_hidden_from_non_member(mock_member):
    mock_member.return_value = False
    share = _share(public=False, author="alice@example.com", group_ids=["g1"])
    assert viewer_can_see_share(share, "stranger@example.com") is False


# -------------------------------------------------------------- Hardening
# Bug repro: TestFlight saw 500s on comments_create / reactions_toggle
# because `is_member_of_group` raised a DynamoDBError on a transient
# read failure. The previous implementation let that bubble through the
# decorator as a generic 500. We now treat per-group lookup failures
# as "not a member of that group" and continue scanning the rest.
@patch("lambdas.common.share_visibility.is_member_of_group")
def test_membership_lookup_failure_does_not_raise(mock_member):
    mock_member.side_effect = RuntimeError("DDB hiccup")
    share = _share(public=False, group_ids=["g1"])

    # Should not raise — treats failed lookup as "not visible".
    assert viewer_can_see_share(share, "stranger@example.com") is False


@patch("lambdas.common.share_visibility.is_member_of_group")
def test_one_failed_group_does_not_block_other_groups(mock_member):
    """If g1 raises but g2 succeeds, visibility wins."""
    def _side_effect(viewer, gid):
        if gid == "g1":
            raise RuntimeError("transient")
        return gid == "g2"

    mock_member.side_effect = _side_effect
    share = _share(public=False, group_ids=["g1", "g2"])

    assert viewer_can_see_share(share, "viewer@example.com") is True
