"""
Tests for shares_react lambda

Critical coverage:
- happy path (queued / rated / unqueued / unrated)
- rating validation
- missing share → 404
- self-react does NOT fire a threshold push
- exactly-once push at the 3rd distinct reactor
- idempotent under simulated concurrent 3rd-reactor arrivals
- subsequent (4th, 5th, ...) reactors do NOT re-fire
- missing caller identity -> 401
"""

from __future__ import annotations

import json
from unittest.mock import patch

from lambdas.shares_react.handler import handler


# ---------------------------------------------------------------------- Helpers
def _event(authorized_event, body, email="bob@example.com"):
    return authorized_event(
        email=email,
        httpMethod="POST",
        path="/shares/react",
        body=json.dumps(body),
    )


def _share(share_id="share-1", author="alice@example.com"):
    return {
        "shareId": share_id,
        "email": author,
        "trackId": "spotify:track:1",
        "trackUri": "spotify:track:1",
        "trackName": "Song",
        "artistName": "Artist",
        "albumName": "Album",
        "albumArtUrl": "https://example.com/art.jpg",
    }


# -------------------------------------------------------------------- Happy path
@patch("lambdas.shares_react.handler._lambda_client")
@patch("lambdas.shares_react.handler.build_enrichment")
@patch("lambdas.shares_react.handler.count_distinct_reactors")
@patch("lambdas.shares_react.handler.mark_threshold_notified")
@patch("lambdas.shares_react.handler.clear_reaction")
@patch("lambdas.shares_react.handler.set_reaction")
@patch("lambdas.shares_react.handler.upsert_track_rating")
@patch("lambdas.shares_react.handler.get_share")
def test_shares_react_happy_queue(
    mock_get_share,
    mock_upsert_rating,
    mock_set_reaction,
    mock_clear_reaction,
    mock_mark_thresh,
    mock_count,
    mock_enrich,
    mock_lambda,
    mock_context,
    authorized_event,
):
    mock_get_share.return_value = _share()
    mock_count.return_value = 1
    mock_enrich.return_value = {
        "queuedCount": 1,
        "ratedCount": 0,
        "viewerHasQueued": True,
        "viewerRating": None,
        "sharerRating": None,
    }

    body = {"shareId": "share-1", "action": "queued"}
    response = handler(_event(authorized_event, body, email="bob@example.com"), mock_context)

    assert response["statusCode"] == 200
    payload = json.loads(response["body"])
    assert payload["queuedCount"] == 1
    assert payload["viewerHasQueued"] is True
    mock_set_reaction.assert_called_once()
    mock_clear_reaction.assert_not_called()
    mock_upsert_rating.assert_not_called()
    mock_mark_thresh.assert_not_called()
    mock_lambda.invoke.assert_not_called()


@patch("lambdas.shares_react.handler._lambda_client")
@patch("lambdas.shares_react.handler.build_enrichment")
@patch("lambdas.shares_react.handler.count_distinct_reactors")
@patch("lambdas.shares_react.handler.mark_threshold_notified")
@patch("lambdas.shares_react.handler.clear_reaction")
@patch("lambdas.shares_react.handler.set_reaction")
@patch("lambdas.shares_react.handler.upsert_track_rating")
@patch("lambdas.shares_react.handler.get_share")
def test_shares_react_happy_rate_upserts_canonical(
    mock_get_share,
    mock_upsert_rating,
    mock_set_reaction,
    mock_clear_reaction,
    mock_mark_thresh,
    mock_count,
    mock_enrich,
    mock_lambda,
    mock_context,
    authorized_event,
):
    mock_get_share.return_value = _share()
    mock_enrich.return_value = {
        "queuedCount": 0,
        "ratedCount": 1,
        "viewerHasQueued": False,
        "viewerRating": 4.5,
        "sharerRating": None,
    }

    body = {
        "shareId": "share-1",
        "action": "rated",
        "rating": 4.5,
    }
    response = handler(_event(authorized_event, body, email="bob@example.com"), mock_context)

    assert response["statusCode"] == 200
    payload = json.loads(response["body"])
    assert payload["viewerRating"] == 4.5
    mock_upsert_rating.assert_called_once()
    kwargs = mock_upsert_rating.call_args.kwargs
    assert kwargs["email"] == "bob@example.com"
    assert kwargs["track_id"] == "spotify:track:1"
    assert kwargs["rating"] == 4.5
    mock_set_reaction.assert_called_once()
    assert mock_set_reaction.call_args.kwargs["action"] == "rated"
    assert mock_set_reaction.call_args.kwargs["rating"] == 4.5


@patch("lambdas.shares_react.handler._lambda_client")
@patch("lambdas.shares_react.handler.build_enrichment")
@patch("lambdas.shares_react.handler.count_distinct_reactors")
@patch("lambdas.shares_react.handler.mark_threshold_notified")
@patch("lambdas.shares_react.handler.clear_reaction")
@patch("lambdas.shares_react.handler.set_reaction")
@patch("lambdas.shares_react.handler.upsert_track_rating")
@patch("lambdas.shares_react.handler.get_share")
def test_shares_react_toggle_unqueue_clears_only(
    mock_get_share,
    mock_upsert_rating,
    mock_set_reaction,
    mock_clear_reaction,
    mock_mark_thresh,
    mock_count,
    mock_enrich,
    mock_lambda,
    mock_context,
    authorized_event,
):
    mock_get_share.return_value = _share()
    mock_enrich.return_value = {
        "queuedCount": 0,
        "ratedCount": 0,
        "viewerHasQueued": False,
        "viewerRating": None,
        "sharerRating": None,
    }

    body = {"shareId": "share-1", "action": "unqueued"}
    response = handler(_event(authorized_event, body, email="bob@example.com"), mock_context)

    assert response["statusCode"] == 200
    mock_clear_reaction.assert_called_once_with("share-1", "bob@example.com", "unqueued")
    mock_set_reaction.assert_not_called()
    mock_mark_thresh.assert_not_called()


# -------------------------------------------------------------- Validation errors
@patch("lambdas.shares_react.handler.get_share")
def test_shares_react_rejects_invalid_action(mock_get_share, mock_context, authorized_event):
    body = {"shareId": "share-1", "action": "bogus"}
    response = handler(_event(authorized_event, body), mock_context)
    assert response["statusCode"] == 400
    mock_get_share.assert_not_called()


@patch("lambdas.shares_react.handler.upsert_track_rating")
@patch("lambdas.shares_react.handler.get_share")
def test_shares_react_rated_missing_rating(mock_get_share, mock_upsert, mock_context, authorized_event):
    mock_get_share.return_value = _share()
    body = {"shareId": "share-1", "action": "rated"}
    response = handler(_event(authorized_event, body), mock_context)
    assert response["statusCode"] == 400


@patch("lambdas.shares_react.handler.upsert_track_rating")
@patch("lambdas.shares_react.handler.get_share")
def test_shares_react_rated_rating_out_of_range(mock_get_share, mock_upsert, mock_context, authorized_event):
    mock_get_share.return_value = _share()
    body = {"shareId": "share-1", "action": "rated", "rating": 6}
    response = handler(_event(authorized_event, body), mock_context)
    assert response["statusCode"] == 400


@patch("lambdas.shares_react.handler.get_share")
def test_shares_react_share_not_found(mock_get_share, mock_context, authorized_event):
    mock_get_share.return_value = None
    body = {"shareId": "missing", "action": "queued"}
    response = handler(_event(authorized_event, body), mock_context)
    assert response["statusCode"] == 404


@patch("lambdas.shares_react.handler.get_share")
def test_shares_react_missing_required_fields(mock_get_share, mock_context, authorized_event):
    body = {}
    response = handler(_event(authorized_event, body), mock_context)
    assert response["statusCode"] == 400
    mock_get_share.assert_not_called()


# ----------------------------------------------------------------- Threshold push
@patch("lambdas.shares_react.handler._lambda_client")
@patch("lambdas.shares_react.handler.build_enrichment")
@patch("lambdas.shares_react.handler.count_distinct_reactors")
@patch("lambdas.shares_react.handler.mark_threshold_notified")
@patch("lambdas.shares_react.handler.set_reaction")
@patch("lambdas.shares_react.handler.upsert_track_rating")
@patch("lambdas.shares_react.handler.get_share")
def test_shares_react_threshold_fires_once_at_third_reactor(
    mock_get_share,
    mock_upsert,
    mock_set_reaction,
    mock_mark_thresh,
    mock_count,
    mock_enrich,
    mock_lambda,
    mock_context,
    authorized_event,
):
    mock_get_share.return_value = _share(author="alice@example.com")
    mock_count.return_value = 3
    mock_mark_thresh.return_value = True
    mock_enrich.return_value = {
        "queuedCount": 3,
        "ratedCount": 0,
        "viewerHasQueued": True,
        "viewerRating": None,
        "sharerRating": None,
    }

    # Set env so invocation path runs
    import os

    os.environ["NOTIFICATIONS_SEND_FUNCTION_NAME"] = "xomify-notifications-send"
    # constants.py read the env var at import — monkey-patch the imported constant too.
    import lambdas.shares_react.handler as sr_handler

    original = sr_handler.NOTIFICATIONS_SEND_FUNCTION_NAME
    sr_handler.NOTIFICATIONS_SEND_FUNCTION_NAME = "xomify-notifications-send"
    try:
        body = {"shareId": "share-1", "action": "queued"}
        response = handler(_event(authorized_event, body, email="bob@example.com"), mock_context)
    finally:
        sr_handler.NOTIFICATIONS_SEND_FUNCTION_NAME = original

    assert response["statusCode"] == 200
    mock_mark_thresh.assert_called_once_with("share-1", 3)
    mock_lambda.invoke.assert_called_once()
    payload = json.loads(mock_lambda.invoke.call_args.kwargs["Payload"].decode())
    assert payload["kind"] == "queue_threshold"
    assert payload["email"] == "alice@example.com"


@patch("lambdas.shares_react.handler._lambda_client")
@patch("lambdas.shares_react.handler.build_enrichment")
@patch("lambdas.shares_react.handler.count_distinct_reactors")
@patch("lambdas.shares_react.handler.mark_threshold_notified")
@patch("lambdas.shares_react.handler.set_reaction")
@patch("lambdas.shares_react.handler.upsert_track_rating")
@patch("lambdas.shares_react.handler.get_share")
def test_shares_react_threshold_idempotent_under_concurrency(
    mock_get_share,
    mock_upsert,
    mock_set_reaction,
    mock_mark_thresh,
    mock_count,
    mock_enrich,
    mock_lambda,
    mock_context,
    authorized_event,
):
    """
    Simulate three reactors hitting the handler simultaneously (all reading
    count=3). The conditional UpdateItem (mocked via mark_threshold_notified)
    must grant the latch to exactly one caller; the other two must see False
    and must NOT invoke notifications_send.
    """
    mock_get_share.return_value = _share(author="alice@example.com")
    mock_count.return_value = 3
    # First call wins, next two lose.
    mock_mark_thresh.side_effect = [True, False, False]
    mock_enrich.return_value = {
        "queuedCount": 3,
        "ratedCount": 0,
        "viewerHasQueued": True,
        "viewerRating": None,
        "sharerRating": None,
    }

    import lambdas.shares_react.handler as sr_handler

    original = sr_handler.NOTIFICATIONS_SEND_FUNCTION_NAME
    sr_handler.NOTIFICATIONS_SEND_FUNCTION_NAME = "xomify-notifications-send"
    try:
        reactors = ["bob@example.com", "carol@example.com", "dave@example.com"]
        for reactor in reactors:
            body = {"shareId": "share-1", "action": "queued"}
            resp = handler(_event(authorized_event, body, email=reactor), mock_context)
            assert resp["statusCode"] == 200
    finally:
        sr_handler.NOTIFICATIONS_SEND_FUNCTION_NAME = original

    # All three attempted to latch, but only ONE invocation went through.
    assert mock_mark_thresh.call_count == 3
    assert mock_lambda.invoke.call_count == 1, (
        "expected exactly one notifications_send invocation across 3 simultaneous 3rd reactors"
    )


@patch("lambdas.shares_react.handler._lambda_client")
@patch("lambdas.shares_react.handler.build_enrichment")
@patch("lambdas.shares_react.handler.count_distinct_reactors")
@patch("lambdas.shares_react.handler.mark_threshold_notified")
@patch("lambdas.shares_react.handler.set_reaction")
@patch("lambdas.shares_react.handler.upsert_track_rating")
@patch("lambdas.shares_react.handler.get_share")
def test_shares_react_threshold_does_not_refire_past_third(
    mock_get_share,
    mock_upsert,
    mock_set_reaction,
    mock_mark_thresh,
    mock_count,
    mock_enrich,
    mock_lambda,
    mock_context,
    authorized_event,
):
    mock_get_share.return_value = _share(author="alice@example.com")
    mock_count.return_value = 5  # well past the threshold
    mock_mark_thresh.return_value = False  # latch already held
    mock_enrich.return_value = {
        "queuedCount": 5,
        "ratedCount": 0,
        "viewerHasQueued": True,
        "viewerRating": None,
        "sharerRating": None,
    }

    import lambdas.shares_react.handler as sr_handler

    original = sr_handler.NOTIFICATIONS_SEND_FUNCTION_NAME
    sr_handler.NOTIFICATIONS_SEND_FUNCTION_NAME = "xomify-notifications-send"
    try:
        body = {"shareId": "share-1", "action": "queued"}
        response = handler(_event(authorized_event, body, email="eve@example.com"), mock_context)
    finally:
        sr_handler.NOTIFICATIONS_SEND_FUNCTION_NAME = original

    assert response["statusCode"] == 200
    mock_mark_thresh.assert_called_once_with("share-1", 3)
    mock_lambda.invoke.assert_not_called()


@patch("lambdas.shares_react.handler._lambda_client")
@patch("lambdas.shares_react.handler.build_enrichment")
@patch("lambdas.shares_react.handler.count_distinct_reactors")
@patch("lambdas.shares_react.handler.mark_threshold_notified")
@patch("lambdas.shares_react.handler.set_reaction")
@patch("lambdas.shares_react.handler.get_share")
def test_shares_react_self_react_does_not_trigger_push(
    mock_get_share,
    mock_set_reaction,
    mock_mark_thresh,
    mock_count,
    mock_enrich,
    mock_lambda,
    mock_context,
    authorized_event,
):
    mock_get_share.return_value = _share(author="alice@example.com")
    mock_count.return_value = 3
    mock_enrich.return_value = {
        "queuedCount": 3,
        "ratedCount": 0,
        "viewerHasQueued": True,
        "viewerRating": None,
        "sharerRating": None,
    }

    # Author reacts to their own share
    body = {"shareId": "share-1", "action": "queued"}
    response = handler(_event(authorized_event, body, email="alice@example.com"), mock_context)

    assert response["statusCode"] == 200
    mock_mark_thresh.assert_not_called()
    mock_lambda.invoke.assert_not_called()
    # count_distinct_reactors must not even be queried in the self-react fast-path
    mock_count.assert_not_called()


# ------------------------------------------------------------------ Auth
@patch("lambdas.shares_react.handler.get_share")
def test_shares_react_missing_caller_identity_returns_401(
    mock_get_share, mock_context, api_gateway_event
):
    event = {
        **api_gateway_event,
        "httpMethod": "POST",
        "path": "/shares/react",
        "body": json.dumps({"shareId": "share-1", "action": "queued"}),
    }
    response = handler(event, mock_context)
    assert response["statusCode"] == 401
    mock_get_share.assert_not_called()
