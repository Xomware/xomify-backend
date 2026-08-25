"""
Tests for the notify() dispatch helper.

The two contracts that matter here are the two the module docstring states:
fail-open (a notification must never break the interaction that caused it) and
never-notify-yourself. Coalescing is the third, and the fiddliest.
"""

import json
from unittest.mock import MagicMock, patch


def _payload(mock_invoke, call_index=0):
    kwargs = mock_invoke.call_args_list[call_index].kwargs
    return json.loads(kwargs["Payload"].decode("utf-8"))


@patch("lambdas.common.notify._lambda_client")
def test_dispatches_rendered_copy_and_route(mock_client):
    from lambdas.common.notify import notify

    notify(
        "share_received",
        "recipient@e.com",
        actor_email="sam@e.com",
        actor_name="Sam",
        track_name="Midnight City",
        artist_name="M83",
        share_id="abc123",
    )

    assert mock_client.invoke.call_count == 1
    payload = _payload(mock_client.invoke)
    assert payload["kind"] == "share_received"
    assert payload["email"] == "recipient@e.com"
    assert payload["title"] == "Sam sent you a song"
    assert payload["body"] == "Midnight City — M83"
    assert payload["customData"]["route"] == "share:abc123"
    assert payload["customData"]["pushType"] == "share_received"


@patch("lambdas.common.notify._lambda_client")
def test_invoked_asynchronously(mock_client):
    """A push must never block the write that triggered it."""
    from lambdas.common.notify import notify

    notify("friend_request", "r@e.com", actor_email="a@e.com", actor_name="A")
    assert mock_client.invoke.call_args.kwargs["InvocationType"] == "Event"


@patch("lambdas.common.notify._lambda_client")
def test_never_notifies_the_actor_about_their_own_action(mock_client):
    from lambdas.common.notify import notify

    notify("share_comment", "same@e.com", actor_email="same@e.com", actor_name="Same")
    mock_client.invoke.assert_not_called()


@patch("lambdas.common.notify._lambda_client")
def test_unknown_kind_is_dropped_not_raised(mock_client):
    from lambdas.common.notify import notify

    notify("not_a_real_kind", "r@e.com")   # must not raise
    mock_client.invoke.assert_not_called()


@patch("lambdas.common.notify._lambda_client")
def test_missing_recipient_is_dropped_not_raised(mock_client):
    from lambdas.common.notify import notify

    notify("share_received", "")
    mock_client.invoke.assert_not_called()


@patch("lambdas.common.notify._lambda_client")
def test_invoke_failure_is_swallowed(mock_client):
    """Fail-open: APNs having a bad afternoon must not fail someone's comment."""
    from lambdas.common.notify import notify

    mock_client.invoke.side_effect = RuntimeError("lambda unavailable")
    notify("share_received", "r@e.com", actor_email="a@e.com")   # must not raise


# ── Coalescing ──────────────────────────────────────────────────────────

@patch("lambdas.common.notify.claim_or_merge")
@patch("lambdas.common.notify._lambda_client")
def test_first_of_a_coalescing_pair_is_parked_not_sent(mock_client, mock_claim):
    from lambdas.common.notify import notify

    mock_claim.return_value = None   # parked

    notify(
        "share_listened",
        "r@e.com",
        actor_email="sam@e.com",
        subject_id="share1",
        actor_name="Sam",
        track_name="Midnight City",
    )

    mock_client.invoke.assert_not_called()


@patch("lambdas.common.notify.claim_or_merge")
@patch("lambdas.common.notify._lambda_client")
def test_second_of_a_pair_sends_one_merged_push(mock_client, mock_claim):
    """One act of engagement, one interruption — the point of decision 11."""
    from lambdas.common.notify import notify

    mock_claim.return_value = {
        "merged": True,
        "ctx": {
            "actor_name": "Sam",
            "track_name": "Midnight City",
            "artist_name": "M83",
            "stars": "****",
        },
        "kinds": ["share_listened", "share_rated"],
    }

    notify(
        "share_rated",
        "r@e.com",
        actor_email="sam@e.com",
        subject_id="share1",
        actor_name="Sam",
        stars="****",
    )

    assert mock_client.invoke.call_count == 1
    payload = _payload(mock_client.invoke)
    assert payload["title"] == "Sam listened and rated ****"
    assert payload["body"] == "Midnight City — M83"


@patch("lambdas.common.notify.claim_or_merge")
@patch("lambdas.common.notify._lambda_client")
def test_coalescing_unavailable_falls_through_to_immediate_send(mock_client, mock_claim):
    """
    B1 ships before B6 provisions the table. Losing coalescing is cosmetic;
    losing the notification is not.
    """
    from lambdas.common.notify import notify

    mock_claim.return_value = {"merged": False, "ctx": {"actor_name": "Sam", "track_name": "T"}, "kinds": ["share_listened"]}

    notify(
        "share_listened",
        "r@e.com",
        actor_email="sam@e.com",
        subject_id="share1",
        actor_name="Sam",
        track_name="T",
    )

    assert mock_client.invoke.call_count == 1
    assert _payload(mock_client.invoke)["title"] == "Sam listened"


@patch("lambdas.common.notify.claim_or_merge")
@patch("lambdas.common.notify._lambda_client")
def test_coalescing_kind_without_a_subject_sends_immediately(mock_client, mock_claim):
    """No subject means nothing to coalesce ON — don't park it forever."""
    from lambdas.common.notify import notify

    notify("share_listened", "r@e.com", actor_email="sam@e.com", actor_name="Sam", track_name="T")

    mock_claim.assert_not_called()
    assert mock_client.invoke.call_count == 1


@patch("lambdas.common.notify._lambda_client")
def test_sweeper_dispatch_uses_solo_copy_not_merged(mock_client):
    """A listen with no rating is just a listen."""
    from lambdas.common.notify import dispatch_pending

    dispatch_pending({
        "kind": "share_listened",
        "recipientEmail": "r@e.com",
        "ctx": {"actor_name": "Sam", "track_name": "Midnight City"},
    })

    payload = _payload(mock_client.invoke)
    assert payload["title"] == "Sam listened"
    assert payload["body"] == "to Midnight City"


@patch("lambdas.common.notify._lambda_client")
def test_sweeper_dispatch_tolerates_an_unusable_row(mock_client):
    from lambdas.common.notify import dispatch_pending

    dispatch_pending({"kind": "nope", "recipientEmail": "r@e.com"})
    dispatch_pending({"kind": "share_listened"})
    mock_client.invoke.assert_not_called()
