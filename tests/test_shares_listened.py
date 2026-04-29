"""
Tests for shares_listened lambda.

Coverage:
- happy path: writes mark_listened for every existing share
- caps at 25 share ids
- rejects empty list / wrong shape
- rejects unknown source values
- skips share ids that don't exist (logs them; does NOT 404 the batch)
- handles auth via authorizer-context email; missing context -> 401
- continues past per-row mark_listened failures (skipped, not 500)
"""

from __future__ import annotations

import json
from unittest.mock import patch

from lambdas.shares_listened.handler import handler


# ---------------------------------------------------------------------- Helpers
def _event(authorized_event, body, email="bob@example.com"):
    return authorized_event(
        email=email,
        httpMethod="POST",
        path="/shares/listened",
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


# ---------------------------------------------------------------- Happy path
@patch("lambdas.shares_listened.handler.mark_listened")
@patch("lambdas.shares_listened.handler.get_share")
def test_shares_listened_happy_path_writes_each_share(
    mock_get_share, mock_mark, mock_context, authorized_event
):
    mock_get_share.side_effect = lambda sid: _share(sid)
    body = {"shareIds": ["s1", "s2", "s3"], "source": "queue"}

    response = handler(_event(authorized_event, body), mock_context)

    assert response["statusCode"] == 200
    payload = json.loads(response["body"])
    assert payload["ok"] is True
    assert payload["listened"] == ["s1", "s2", "s3"]
    assert payload["skipped"] == []
    assert mock_mark.call_count == 3
    for call in mock_mark.call_args_list:
        assert call.args[1] == "bob@example.com"
        assert call.kwargs["source"] == "queue"


@patch("lambdas.shares_listened.handler.mark_listened")
@patch("lambdas.shares_listened.handler.get_share")
def test_shares_listened_default_source_is_queue(
    mock_get_share, mock_mark, mock_context, authorized_event
):
    mock_get_share.return_value = _share()
    body = {"shareIds": ["s1"]}  # no source

    response = handler(_event(authorized_event, body), mock_context)

    assert response["statusCode"] == 200
    assert mock_mark.call_args.kwargs["source"] == "queue"


@patch("lambdas.shares_listened.handler.mark_listened")
@patch("lambdas.shares_listened.handler.get_share")
def test_shares_listened_accepts_source_play(
    mock_get_share, mock_mark, mock_context, authorized_event
):
    mock_get_share.return_value = _share()
    body = {"shareIds": ["s1"], "source": "play"}

    response = handler(_event(authorized_event, body), mock_context)

    assert response["statusCode"] == 200
    assert mock_mark.call_args.kwargs["source"] == "play"


@patch("lambdas.shares_listened.handler.mark_listened")
@patch("lambdas.shares_listened.handler.get_share")
def test_shares_listened_dedupes_share_ids(
    mock_get_share, mock_mark, mock_context, authorized_event
):
    mock_get_share.return_value = _share()
    body = {"shareIds": ["s1", "s1", "s2", "s1"]}

    response = handler(_event(authorized_event, body), mock_context)

    assert response["statusCode"] == 200
    payload = json.loads(response["body"])
    # Dedupes to s1, s2 — order preserved.
    assert payload["listened"] == ["s1", "s2"]
    assert mock_mark.call_count == 2


# ----------------------------------------------------------- Skip missing shares
@patch("lambdas.shares_listened.handler.mark_listened")
@patch("lambdas.shares_listened.handler.get_share")
def test_shares_listened_skips_unknown_shares(
    mock_get_share, mock_mark, mock_context, authorized_event
):
    def _side(share_id):
        return _share(share_id) if share_id != "missing" else None

    mock_get_share.side_effect = _side
    body = {"shareIds": ["s1", "missing", "s3"]}

    response = handler(_event(authorized_event, body), mock_context)

    # Whole batch must NOT 404; missing rows are quietly skipped.
    assert response["statusCode"] == 200
    payload = json.loads(response["body"])
    assert payload["listened"] == ["s1", "s3"]
    assert payload["skipped"] == ["missing"]
    assert mock_mark.call_count == 2


@patch("lambdas.shares_listened.handler.mark_listened")
@patch("lambdas.shares_listened.handler.get_share")
def test_shares_listened_continues_past_mark_listened_failure(
    mock_get_share, mock_mark, mock_context, authorized_event
):
    """A single mark_listened failure must NOT 500 the whole batch."""
    mock_get_share.side_effect = lambda sid: _share(sid)

    def _maybe_fail(share_id, email, source="queue"):
        if share_id == "s2":
            raise RuntimeError("ddb down")
        return {}

    mock_mark.side_effect = _maybe_fail

    body = {"shareIds": ["s1", "s2", "s3"]}
    response = handler(_event(authorized_event, body), mock_context)

    assert response["statusCode"] == 200
    payload = json.loads(response["body"])
    assert payload["listened"] == ["s1", "s3"]
    assert payload["skipped"] == ["s2"]


# ----------------------------------------------------------- Validation errors
@patch("lambdas.shares_listened.handler.mark_listened")
@patch("lambdas.shares_listened.handler.get_share")
def test_shares_listened_missing_share_ids_field(
    mock_get_share, mock_mark, mock_context, authorized_event
):
    response = handler(_event(authorized_event, {}), mock_context)
    assert response["statusCode"] == 400
    mock_get_share.assert_not_called()
    mock_mark.assert_not_called()


@patch("lambdas.shares_listened.handler.mark_listened")
@patch("lambdas.shares_listened.handler.get_share")
def test_shares_listened_share_ids_not_a_list(
    mock_get_share, mock_mark, mock_context, authorized_event
):
    response = handler(_event(authorized_event, {"shareIds": "s1"}), mock_context)
    assert response["statusCode"] == 400


@patch("lambdas.shares_listened.handler.mark_listened")
@patch("lambdas.shares_listened.handler.get_share")
def test_shares_listened_empty_list(
    mock_get_share, mock_mark, mock_context, authorized_event
):
    response = handler(_event(authorized_event, {"shareIds": []}), mock_context)
    assert response["statusCode"] == 400


@patch("lambdas.shares_listened.handler.mark_listened")
@patch("lambdas.shares_listened.handler.get_share")
def test_shares_listened_caps_at_25(
    mock_get_share, mock_mark, mock_context, authorized_event
):
    body = {"shareIds": [f"s{i}" for i in range(26)]}
    response = handler(_event(authorized_event, body), mock_context)
    assert response["statusCode"] == 400
    mock_get_share.assert_not_called()


@patch("lambdas.shares_listened.handler.mark_listened")
@patch("lambdas.shares_listened.handler.get_share")
def test_shares_listened_rejects_unknown_source(
    mock_get_share, mock_mark, mock_context, authorized_event
):
    body = {"shareIds": ["s1"], "source": "bogus"}
    response = handler(_event(authorized_event, body), mock_context)
    assert response["statusCode"] == 400
    mock_get_share.assert_not_called()


@patch("lambdas.shares_listened.handler.mark_listened")
@patch("lambdas.shares_listened.handler.get_share")
def test_shares_listened_rejects_blank_share_id_entries(
    mock_get_share, mock_mark, mock_context, authorized_event
):
    body = {"shareIds": ["s1", "   "]}
    response = handler(_event(authorized_event, body), mock_context)
    assert response["statusCode"] == 400


# -------------------------------------------------------------------- Auth
@patch("lambdas.shares_listened.handler.get_share")
def test_shares_listened_missing_caller_identity_returns_401(
    mock_get_share, mock_context, api_gateway_event
):
    event = {
        **api_gateway_event,
        "httpMethod": "POST",
        "path": "/shares/listened",
        "body": json.dumps({"shareIds": ["s1"]}),
    }
    response = handler(event, mock_context)
    assert response["statusCode"] == 401
    mock_get_share.assert_not_called()
