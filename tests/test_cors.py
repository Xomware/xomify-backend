"""CORS origin resolution (#121)."""

import pytest

from lambdas.common import cors
from lambdas.common.cors import (
    cors_headers,
    resolve_origin,
    set_request_origin,
)
from lambdas.common.errors import ValidationError, handle_errors
from lambdas.common.utility_helpers import success_response

PRIMARY = "https://xomify.xomware.com"
SECONDARY = "https://xomware.com"


@pytest.fixture(autouse=True)
def clear_origin():
    """Each test starts with no origin recorded — a ContextVar set by one test
    would otherwise leak into the next."""
    set_request_origin(None)
    yield
    set_request_origin(None)


def test_no_origin_falls_back_to_primary():
    assert resolve_origin() == PRIMARY


def test_allowed_origin_is_echoed():
    set_request_origin({"headers": {"Origin": SECONDARY}})
    assert resolve_origin() == SECONDARY


def test_lowercase_origin_header_is_read():
    # API Gateway v1 passes header casing through, and proxies vary.
    set_request_origin({"headers": {"origin": SECONDARY}})
    assert resolve_origin() == SECONDARY


def test_unknown_origin_gets_the_primary_not_itself():
    """The attack this fixes: an arbitrary site must not be told it is allowed."""
    set_request_origin({"headers": {"Origin": "https://evil.example.com"}})
    assert resolve_origin() == PRIMARY


def test_no_response_ever_says_star():
    set_request_origin({"headers": {"Origin": "https://evil.example.com"}})
    assert cors_headers()["Access-Control-Allow-Origin"] != "*"


def test_vary_origin_is_set():
    # Without it a shared cache can hand one origin's response to another.
    assert cors_headers()["Vary"] == "Origin"


def test_allowlist_comes_from_the_environment(monkeypatch):
    monkeypatch.setenv("CORS_ALLOWED_ORIGINS", "https://a.test,https://b.test")
    set_request_origin({"headers": {"Origin": "https://b.test"}})
    assert resolve_origin() == "https://b.test"

    set_request_origin({"headers": {"Origin": PRIMARY}})
    assert resolve_origin() == "https://a.test"


def test_blank_environment_value_falls_back_to_defaults(monkeypatch):
    monkeypatch.setenv("CORS_ALLOWED_ORIGINS", "")
    assert resolve_origin() == PRIMARY


def test_defaults_match_the_terraform_variable():
    """`var.cors_allowed_origins` in xomify-infrastructure. If these drift, a
    preflight can succeed and the real response still be rejected."""
    assert cors.allowed_origins() == [
        "https://xomify.xomware.com",
        "https://xomware.com",
        "https://www.xomware.com",
    ]


def test_missing_headers_key_is_not_an_error():
    set_request_origin({})
    assert resolve_origin() == PRIMARY


def test_null_headers_is_not_an_error():
    # API Gateway sends `"headers": null` for some test invocations.
    set_request_origin({"headers": None})
    assert resolve_origin() == PRIMARY


# ---------------------------------------------------------------- integration


@handle_errors("cors_probe")
def _ok_handler(event, context):
    return success_response({"ok": True})


@handle_errors("cors_probe")
def _raising_handler(event, context):
    raise ValidationError("nope", handler="cors_probe")


def test_decorator_records_the_origin_for_success_responses():
    response = _ok_handler({"headers": {"Origin": SECONDARY}}, None)
    assert response["headers"]["Access-Control-Allow-Origin"] == SECONDARY


def test_error_responses_carry_cors_too():
    """An error without CORS headers surfaces in the browser as an opaque
    network failure instead of the 400 it actually is."""
    response = _raising_handler({"headers": {"Origin": SECONDARY}}, None)
    assert response["statusCode"] == 400
    assert response["headers"]["Access-Control-Allow-Origin"] == SECONDARY


def test_origin_does_not_leak_between_invocations():
    _ok_handler({"headers": {"Origin": SECONDARY}}, None)
    response = _ok_handler({"headers": {}}, None)
    assert response["headers"]["Access-Control-Allow-Origin"] == PRIMARY
