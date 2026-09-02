"""Tests for users_set_visibility (POST /users/visibility)."""

from unittest.mock import patch

from lambdas.common.user_visibility import (
    FRIENDS,
    PRIVATE,
    is_visible_to_friends,
    read_visibility,
)
from lambdas.users_set_visibility.handler import handler


def _event(body: dict, email: str = "dom@example.com") -> dict:
    return {
        "body": __import__("json").dumps(body),
        "requestContext": {"authorizer": {"email": email}},
    }


# --- defaults -------------------------------------------------------------

def test_missing_attributes_default_to_friends():
    # Users predating this feature have no attribute at all; they must read as
    # friends, which is the decision recorded in the plan.
    assert read_visibility({}) == {
        "wrapped": FRIENDS, "releaseRadar": FRIENDS, "topItems": FRIENDS
    }


def test_explicit_private_is_honoured():
    assert read_visibility({"wrapped_visibility": PRIVATE})["wrapped"] == PRIVATE


def test_garbage_value_falls_back_to_friends_not_a_crash():
    assert read_visibility({"wrapped_visibility": "banana"})["wrapped"] == FRIENDS


def test_unknown_artefact_is_never_visible():
    assert is_visible_to_friends({}, "nope") is False


# --- endpoint -------------------------------------------------------------

@patch("lambdas.users_set_visibility.handler.set_visibility")
def test_partial_update_only_sends_given_keys(mock_set):
    mock_set.return_value = {"wrapped": PRIVATE, "releaseRadar": FRIENDS, "topItems": FRIENDS}
    handler(_event({"wrapped": PRIVATE}), None)
    # Sending one key must not reset the other two -- the clobber that the
    # enrollment flags used to have.
    mock_set.assert_called_once_with("dom@example.com", {"wrapped": PRIVATE})


@patch("lambdas.users_set_visibility.handler.set_visibility")
def test_returns_the_full_map(mock_set):
    full = {"wrapped": PRIVATE, "releaseRadar": FRIENDS, "topItems": FRIENDS}
    mock_set.return_value = full
    resp = handler(_event({"wrapped": PRIVATE}), None)
    body = __import__("json").loads(resp["body"])
    assert body["visibility"] == full


@patch("lambdas.users_set_visibility.handler.set_visibility")
def test_caller_comes_from_authorizer_not_the_body(mock_set):
    mock_set.return_value = read_visibility({})
    # An email in the body must be ignored, not honoured.
    handler(_event({"wrapped": PRIVATE, "email": "someone-else@example.com"}), None)
    assert mock_set.call_args[0][0] == "dom@example.com"


# @handle_errors turns a raised ValidationError into a 400 response rather than
# letting it escape, so these assert on the status, not on the exception.

def test_empty_body_is_rejected():
    assert handler(_event({}), None)["statusCode"] == 400


def test_unknown_field_alone_is_rejected():
    assert handler(_event({"nope": PRIVATE}), None)["statusCode"] == 400


# --- user_data exposes the normalized map --------------------------------

@patch("lambdas.user_data.handler.get_user_table_data")
def test_user_data_reports_visibility_defaults(mock_get):
    from lambdas.user_data.handler import handler as user_data_handler
    mock_get.return_value = {"email": "dom@example.com"}
    resp = user_data_handler(
        {"requestContext": {"authorizer": {"email": "dom@example.com"}}}, None
    )
    body = __import__("json").loads(resp["body"])
    # A user who never touched the setting must read as friends, not as absent
    # — the client should never have to guess the default.
    assert body["visibility"] == {
        "wrapped": FRIENDS, "releaseRadar": FRIENDS, "topItems": FRIENDS
    }


@patch("lambdas.user_data.handler.get_user_table_data")
def test_user_data_reports_an_explicit_private(mock_get):
    from lambdas.user_data.handler import handler as user_data_handler
    mock_get.return_value = {"email": "dom@example.com", "wrapped_visibility": PRIVATE}
    resp = user_data_handler(
        {"requestContext": {"authorizer": {"email": "dom@example.com"}}}, None
    )
    body = __import__("json").loads(resp["body"])
    assert body["visibility"]["wrapped"] == PRIVATE
