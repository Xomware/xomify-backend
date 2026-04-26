"""
Tests for caller-identity helpers in lambdas.common.utility_helpers.

Covers:
- Trusted authorizer-context resolution (preferred path).
- Query-string fallback (transition window).
- JSON-body fallback (transition window).
- Missing identity (raises MissingCallerIdentityError -> HTTP 401).
- Edge cases: missing requestContext / missing authorizer keys.

The WARN log emitted on the fallback path is what we grep CloudWatch for to
gate the Track 1l cleanup. Tests assert on that log string explicitly.
"""

import json
import logging

import pytest

from lambdas.common.errors import MissingCallerIdentityError
from lambdas.common.utility_helpers import (
    get_caller_email,
    get_caller_user_id,
)


@pytest.fixture(autouse=True)
def _propagate_xomify_logs():
    """
    The xomify logger is configured with `propagate=False` to prevent duplicate
    Lambda log lines. caplog intercepts records through propagation to the root
    logger, so we flip propagation on for the duration of each test in this
    module. The change is reverted afterwards so other tests are unaffected.
    """
    logger = logging.getLogger("xomify")
    original = logger.propagate
    logger.propagate = True
    try:
        yield
    finally:
        logger.propagate = original


# ============================================
# get_caller_email
# ============================================

class TestGetCallerEmail:
    def test_returns_context_value_when_authorizer_populated(
        self, authorized_event, caplog
    ):
        event = authorized_event(email="alice@example.com")
        with caplog.at_level(logging.WARNING, logger="xomify"):
            result = get_caller_email(event)
        assert result == "alice@example.com"
        assert not any("auth_path=fallback" in r.message for r in caplog.records)

    def test_returns_query_param_when_context_empty(self, legacy_event, caplog):
        event = legacy_event(email="bob@example.com")
        event["headers"]["User-Agent"] = "XomifyiOS/1.2.3"
        with caplog.at_level(logging.WARNING, logger="xomify"):
            result = get_caller_email(event)
        assert result == "bob@example.com"
        warn_messages = [
            r.message for r in caplog.records if r.levelno == logging.WARNING
        ]
        assert any(
            "auth_path=fallback" in m
            and "field=email" in m
            and "user_agent=XomifyiOS/1.2.3" in m
            for m in warn_messages
        )

    def test_returns_body_value_when_context_and_query_empty(
        self, legacy_event, caplog
    ):
        event = legacy_event()
        event["body"] = json.dumps({"email": "carol@example.com"})
        event["headers"]["user-agent"] = "AngularApp/0.9"  # case-insensitive header
        with caplog.at_level(logging.WARNING, logger="xomify"):
            result = get_caller_email(event)
        assert result == "carol@example.com"
        warn_messages = [
            r.message for r in caplog.records if r.levelno == logging.WARNING
        ]
        assert any(
            "auth_path=fallback" in m
            and "source=body" in m
            and "user_agent=AngularApp/0.9" in m
            for m in warn_messages
        )

    def test_user_agent_unknown_when_header_missing(self, legacy_event, caplog):
        event = legacy_event(email="dan@example.com")
        event["headers"] = {}  # strip headers
        with caplog.at_level(logging.WARNING, logger="xomify"):
            result = get_caller_email(event)
        assert result == "dan@example.com"
        warn_messages = [
            r.message for r in caplog.records if r.levelno == logging.WARNING
        ]
        assert any("user_agent=unknown" in m for m in warn_messages)

    def test_raises_when_nothing_present(self, legacy_event):
        event = legacy_event()
        with pytest.raises(MissingCallerIdentityError) as exc_info:
            get_caller_email(event)
        assert exc_info.value.status == 401
        assert exc_info.value.details.get("field") == "email"

    def test_handles_missing_request_context_gracefully(self, legacy_event):
        event = legacy_event(email="eve@example.com")
        event.pop("requestContext", None)
        result = get_caller_email(event)
        assert result == "eve@example.com"

    def test_handles_missing_authorizer_key_gracefully(self, legacy_event):
        event = legacy_event(email="frank@example.com")
        event["requestContext"] = {}  # no `authorizer`
        result = get_caller_email(event)
        assert result == "frank@example.com"

    def test_empty_string_in_context_falls_back(self, legacy_event, caplog):
        event = legacy_event(email="grace@example.com")
        event["requestContext"] = {"authorizer": {"email": ""}}
        with caplog.at_level(logging.WARNING, logger="xomify"):
            result = get_caller_email(event)
        assert result == "grace@example.com"

    def test_malformed_body_does_not_raise_value_error(self, legacy_event):
        event = legacy_event()
        event["body"] = "{not valid json"
        with pytest.raises(MissingCallerIdentityError):
            get_caller_email(event)


# ============================================
# get_caller_user_id
# ============================================

class TestGetCallerUserId:
    def test_returns_context_value_when_authorizer_populated(
        self, authorized_event, caplog
    ):
        event = authorized_event(user_id="spotifyAlice")
        with caplog.at_level(logging.WARNING, logger="xomify"):
            result = get_caller_user_id(event)
        assert result == "spotifyAlice"
        assert not any("auth_path=fallback" in r.message for r in caplog.records)

    def test_returns_query_param_when_context_empty(self, legacy_event, caplog):
        event = legacy_event(user_id="spotifyBob")
        event["headers"]["User-Agent"] = "XomifyiOS/2.0"
        with caplog.at_level(logging.WARNING, logger="xomify"):
            result = get_caller_user_id(event)
        assert result == "spotifyBob"
        warn_messages = [
            r.message for r in caplog.records if r.levelno == logging.WARNING
        ]
        assert any(
            "auth_path=fallback" in m
            and "field=userId" in m
            and "user_agent=XomifyiOS/2.0" in m
            for m in warn_messages
        )

    def test_returns_body_value_when_context_and_query_empty(
        self, legacy_event, caplog
    ):
        event = legacy_event()
        event["body"] = json.dumps({"userId": "spotifyCarol"})
        with caplog.at_level(logging.WARNING, logger="xomify"):
            result = get_caller_user_id(event)
        assert result == "spotifyCarol"
        warn_messages = [
            r.message for r in caplog.records if r.levelno == logging.WARNING
        ]
        assert any("source=body" in m for m in warn_messages)

    def test_raises_when_nothing_present(self, legacy_event):
        event = legacy_event()
        with pytest.raises(MissingCallerIdentityError) as exc_info:
            get_caller_user_id(event)
        assert exc_info.value.status == 401
        assert exc_info.value.details.get("field") == "userId"

    def test_handles_missing_request_context_gracefully(self, legacy_event):
        event = legacy_event(user_id="spotifyEve")
        event.pop("requestContext", None)
        result = get_caller_user_id(event)
        assert result == "spotifyEve"

    def test_handles_missing_authorizer_key_gracefully(self, legacy_event):
        event = legacy_event(user_id="spotifyFrank")
        event["requestContext"] = {}
        result = get_caller_user_id(event)
        assert result == "spotifyFrank"

    def test_context_takes_precedence_over_query(self, authorized_event):
        event = authorized_event(user_id="contextWinner")
        event["queryStringParameters"] = {"userId": "queryLoser"}
        result = get_caller_user_id(event)
        assert result == "contextWinner"


# ============================================
# Fixture sanity
# ============================================

class TestFixtures:
    def test_authorized_event_default_shape(self, authorized_event):
        event = authorized_event()
        assert event["requestContext"]["authorizer"]["email"] == "test@example.com"
        assert event["requestContext"]["authorizer"]["userId"] == "spotify123"
        assert event["requestContext"]["authorizer"]["tokenType"] == "user"

    def test_authorized_event_overrides(self, authorized_event):
        event = authorized_event(httpMethod="POST", path="/foo", body='{"x":1}')
        assert event["httpMethod"] == "POST"
        assert event["path"] == "/foo"
        assert event["body"] == '{"x":1}'

    def test_legacy_event_no_identity_in_context(self, legacy_event):
        event = legacy_event()
        assert "email" not in event["requestContext"]["authorizer"]
        assert "userId" not in event["requestContext"]["authorizer"]
        assert event["requestContext"]["authorizer"]["tokenType"] == "legacy"
        assert event["queryStringParameters"] == {}

    def test_legacy_event_with_identity_routes_to_query(self, legacy_event):
        event = legacy_event(email="x@y.z", user_id="abc")
        assert event["queryStringParameters"] == {"email": "x@y.z", "userId": "abc"}
