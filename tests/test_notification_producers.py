"""
Tests for the interaction producers (B4).

These guard the wiring, not the dispatch — notify() itself is covered in
test_notify.py. What matters here is that each producer picks the RIGHT
RECIPIENT (several of them are easy to get backwards) and fires on the right
edge.
"""

import json
from unittest.mock import MagicMock, patch

import pytest


def _authed(email, body=None):
    event = {"requestContext": {"authorizer": {"email": email}}}
    if body is not None:
        event["body"] = json.dumps(body)
    return event


# ── friends: the recipient is the easy thing to get backwards ────────────

@patch("lambdas.friends_request.handler.display_name_for", return_value="Sam")
@patch("lambdas.friends_request.handler.notify")
@patch("lambdas.friends_request.handler.send_friend_request", return_value=True)
def test_friend_request_notifies_the_target(mock_send, mock_notify, _name, mock_context):
    from lambdas.friends_request.handler import handler

    handler(_authed("sam@e.com", {"requestEmail": "target@e.com"}), mock_context)

    args, kwargs = mock_notify.call_args
    assert args[0] == "friend_request"
    assert args[1] == "target@e.com"          # the target, not the sender
    assert kwargs["actor_email"] == "sam@e.com"


@patch("lambdas.friends_request.handler.display_name_for", return_value="Sam")
@patch("lambdas.friends_request.handler.notify")
@patch("lambdas.friends_request.handler.send_friend_request", return_value=False)
def test_failed_friend_request_notifies_nobody(mock_send, mock_notify, _n, mock_context):
    """A failed write must not tell the target someone tried."""
    from lambdas.friends_request.handler import handler

    handler(_authed("sam@e.com", {"requestEmail": "target@e.com"}), mock_context)
    mock_notify.assert_not_called()


@patch("lambdas.friends_accept.handler.display_name_for", return_value="Target")
@patch("lambdas.friends_accept.handler.notify")
@patch("lambdas.friends_accept.handler.accept_friend_request", return_value=True)
def test_friend_accept_notifies_the_original_sender(mock_accept, mock_notify, _n, mock_context):
    """
    The accepter already knows they accepted. The notification goes to whoever
    SENT the request — the reverse of friends_request.
    """
    from lambdas.friends_accept.handler import handler

    handler(_authed("target@e.com", {"requestEmail": "sam@e.com"}), mock_context)

    args, kwargs = mock_notify.call_args
    assert args[0] == "friend_accepted"
    assert args[1] == "sam@e.com"             # the requester
    assert kwargs["actor_email"] == "target@e.com"


# ── shares_create fan-out ────────────────────────────────────────────────

@patch("lambdas.shares_create.handler.display_name_for", return_value="Sam")
@patch("lambdas.shares_create.handler.notify_friends_of")
def test_public_share_fans_out_to_friends(mock_fanout, _name):
    """A share is a friends-graph broadcast, not an addressed message."""
    import lambdas.shares_create.handler as mod

    with patch.object(mod, "create_share", return_value={"shareId": "s1", "public": True}), \
         patch.object(mod, "mark_listened"), \
         patch.object(mod, "upsert_track_rating"):
        mod.handler(_authed("sam@e.com", {
            "trackId": "t1", "trackUri": "spotify:track:t1",
            "trackName": "Midnight City", "artistName": "M83",
            "albumName": "Hurry Up", "albumArtUrl": "http://img",
            "public": True,
        }), MagicMock())

    assert mock_fanout.call_count == 1
    args, kwargs = mock_fanout.call_args
    assert args[0] == "sam@e.com"
    assert args[1] == "share_received"
    assert kwargs["track_name"] == "Midnight City"


# ── fan-out helper ───────────────────────────────────────────────────────

@patch("lambdas.common.notify.notify")
def test_fanout_only_reaches_accepted_friendships(mock_notify):
    """
    list_all_friends_for_user returns the whole partition — pending and blocked
    included. An unfiltered fan-out would push to people who declined or
    blocked you.
    """
    import lambdas.common.notify as mod

    rows = [
        {"friendEmail": "ok@e.com", "status": "accepted"},
        {"friendEmail": "pending@e.com", "status": "pending"},
        {"friendEmail": "blocked@e.com", "status": "blocked"},
    ]
    with patch("lambdas.common.friendships_dynamo.list_all_friends_for_user", return_value=rows):
        count = mod.notify_friends_of("sam@e.com", "share_received", share_id="s1")

    assert count == 1
    assert mock_notify.call_args.args[1] == "ok@e.com"


@patch("lambdas.common.notify.notify")
def test_fanout_is_capped(mock_notify):
    import lambdas.common.notify as mod

    rows = [
        {"friendEmail": f"f{i}@e.com", "status": "accepted"}
        for i in range(mod.MAX_FANOUT + 25)
    ]
    with patch("lambdas.common.friendships_dynamo.list_all_friends_for_user", return_value=rows):
        assert mod.notify_friends_of("sam@e.com", "share_received") == mod.MAX_FANOUT


@patch("lambdas.common.notify.notify")
def test_fanout_survives_a_friends_lookup_failure(mock_notify):
    """Fail-open: a broken graph read must not fail the share that triggered it."""
    import lambdas.common.notify as mod

    with patch("lambdas.common.friendships_dynamo.list_all_friends_for_user",
               side_effect=RuntimeError("dynamo down")):
        assert mod.notify_friends_of("sam@e.com", "share_received") == 0
    mock_notify.assert_not_called()


def test_display_name_falls_back_to_the_local_part():
    """Never leak a full email address onto someone's lock screen."""
    import lambdas.common.notify as mod

    with patch("lambdas.common.dynamo_helpers.batch_get_users", return_value={}):
        assert mod.display_name_for("dominick@example.com") == "dominick"
    with patch("lambdas.common.dynamo_helpers.batch_get_users",
               side_effect=RuntimeError("boom")):
        assert mod.display_name_for("dominick@example.com") == "dominick"
    assert mod.display_name_for("") == "Someone"


def test_display_name_prefers_the_stored_display_name():
    import lambdas.common.notify as mod

    with patch("lambdas.common.dynamo_helpers.batch_get_users",
               return_value={"d@e.com": {"displayName": "Dom G"}}):
        assert mod.display_name_for("d@e.com") == "Dom G"


# ── reactions fire on one edge only ──────────────────────────────────────

@patch("lambdas.common.notify.notify")
def test_reaction_notifies_on_add_but_not_on_remove(mock_notify):
    """Pushing on both edges turns a toggle into a notification machine gun."""
    import lambdas.shares_reactions_toggle.handler as mod

    share = {"shareId": "s1", "email": "author@e.com", "trackName": "Midnight City"}
    common = dict(
        get_share=MagicMock(return_value=share),
        viewer_can_see_share=MagicMock(return_value=True),
        build_reaction_summary=MagicMock(return_value={"counts": {}, "viewerReactions": []}),
        add_reaction=MagicMock(),
        remove_reaction=MagicMock(),
    )

    # ADD -> notified
    with patch.multiple(mod, get_reaction=MagicMock(return_value=None), **common):
        mod.handler(_authed("fan@e.com", {"shareId": "s1", "reaction": "fire"}), MagicMock())
    assert mock_notify.call_count == 1
    assert mock_notify.call_args.args[0] == "share_reaction"
    # Slug in, glyph out — "Sam reacted fire" is not a sentence.
    assert mock_notify.call_args.kwargs["emoji"] == "🔥"

    mock_notify.reset_mock()

    # REMOVE -> silent
    with patch.multiple(mod, get_reaction=MagicMock(return_value={"x": 1}), **common):
        mod.handler(_authed("fan@e.com", {"shareId": "s1", "reaction": "fire"}), MagicMock())
    mock_notify.assert_not_called()
