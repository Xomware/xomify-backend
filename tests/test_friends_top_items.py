"""Tests for friends_top_items — notably that it never fetches from Spotify."""

import json
from unittest.mock import patch

from lambdas.common.errors import AuthorizationError
from lambdas.friends_top_items.handler import handler

MOD = "lambdas.friends_top_items.handler"


def _event(email="alex@example.com", caller="dom@example.com"):
    return {
        "queryStringParameters": {"email": email},
        "requestContext": {"authorizer": {"email": caller}},
    }


def _body(resp):
    return json.loads(resp["body"])


@patch(f"{MOD}.get_cached", return_value=None)
@patch(f"{MOD}.assert_can_read", return_value={"email": "alex@example.com"})
def test_cold_cache_returns_empty_rather_than_fetching(_gate, _cached):
    # Fetching would spend the SUBJECT's Spotify budget because someone else
    # looked at their profile. The handler must not import a fetch path at all.
    body = _body(handler(_event(), None))
    assert body["cached"] is False
    assert body["tracks"] == {} and body["artists"] == {} and body["genres"] == {}


def test_handler_has_no_fetch_import():
    import lambdas.friends_top_items.handler as h
    source = open(h.__file__).read()
    assert "top_items_fetch" not in source
    assert "set_cached" not in source


@patch(f"{MOD}.derive_albums_by_range", return_value={"short_term": []})
@patch(f"{MOD}.get_cached", return_value={"tracks": {"short_term": [{"id": "t1"}]}})
@patch(f"{MOD}.assert_can_read", return_value={"email": "alex@example.com"})
def test_warm_cache_is_served_with_albums_derived(_gate, _cached, _albums):
    body = _body(handler(_event(), None))
    assert body["cached"] is True
    assert body["email"] == "alex@example.com"
    assert body["albums"] == {"short_term": []}


@patch(f"{MOD}.get_cached")
@patch(f"{MOD}.assert_can_read", side_effect=AuthorizationError(
    message="Not available", handler="friends_top_items", function="assert_can_read"))
def test_a_denied_read_never_touches_the_cache(_gate, mock_cached):
    # @handle_errors turns the denial into a 403 response, so assert on the
    # status and on the cache never being consulted -- if the gate is ever
    # moved below the read, this fails.
    resp = handler(_event(), None)
    # 401, not 403: AuthorizationError maps to 401 across this codebase.
    assert resp["statusCode"] == 401
    mock_cached.assert_not_called()
