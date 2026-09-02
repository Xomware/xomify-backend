"""
Tests for the gate every friend-scoped read goes through.

These are the security tests for the friend feature: they assert that a
non-friend, a private setting, and a missing user all deny equally.
"""

import json
from unittest.mock import patch

import pytest

from lambdas.common.errors import AuthorizationError, ValidationError
from lambdas.common.friend_visibility_gate import assert_can_read

CALLER = "dom@example.com"
FRIEND = "alex@example.com"
HANDLER = "test_handler"

GATE = "lambdas.common.friend_visibility_gate"


def _patches(user=None, friends=True, visible=True):
    return (
        patch(f"{GATE}.get_user_table_data", return_value=user),
        patch(f"{GATE}.are_users_friends", return_value=friends),
        patch(f"{GATE}.is_visible_to_friends", return_value=visible),
    )


def _run(**kw):
    a, b, c = _patches(**kw)
    with a, b, c:
        return assert_can_read(CALLER, FRIEND, "wrapped", HANDLER)


# --- allow ---------------------------------------------------------------

def test_accepted_friend_with_visible_artefact_is_allowed():
    assert _run(user={"email": FRIEND}, friends=True, visible=True) == {"email": FRIEND}


def test_reading_your_own_data_skips_both_checks():
    # A client landing on its own row must not 403. Note friends=False and
    # visible=False here: neither is consulted for self.
    a, b, c = _patches(user={"email": CALLER}, friends=False, visible=False)
    with a, b, c:
        assert assert_can_read(CALLER, CALLER, "wrapped", HANDLER) == {"email": CALLER}


# --- deny ----------------------------------------------------------------

def test_non_friend_is_denied():
    with pytest.raises(AuthorizationError):
        _run(user={"email": FRIEND}, friends=False, visible=True)


def test_private_artefact_is_denied_even_for_a_friend():
    with pytest.raises(AuthorizationError):
        _run(user={"email": FRIEND}, friends=True, visible=False)


def test_missing_user_record_is_denied_not_defaulted():
    # Fails CLOSED. The default-on decision applies to users we can read; it is
    # not a licence to serve data when the lookup itself failed.
    with pytest.raises(AuthorizationError):
        _run(user=None, friends=True, visible=True)


def test_missing_email_is_a_validation_error():
    with pytest.raises(ValidationError):
        assert_can_read(CALLER, "", "wrapped", HANDLER)


def test_non_friend_and_private_are_indistinguishable():
    # Same message either way, so this cannot be used to probe who has an
    # artefact enabled.
    def message(**kw):
        try:
            _run(**kw)
        except AuthorizationError as err:
            return str(err)
        return None

    assert message(user={"email": FRIEND}, friends=False, visible=True) == \
           message(user={"email": FRIEND}, friends=True, visible=False)
