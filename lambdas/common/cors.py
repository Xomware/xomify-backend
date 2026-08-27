"""
CORS origin resolution.

Every response used to send `Access-Control-Allow-Origin: *`, which let any
site on the internet read authenticated API responses from a logged-in user's
browser (#121).

A single hardcoded origin would not work: `xomware.com` calls this API too (its
music ticker and release-radar widget), and a browser only accepts a response
whose `Access-Control-Allow-Origin` matches the requesting origin exactly. So
the caller's `Origin` is echoed back when it is on the allowlist, and falls
back to the primary origin otherwise — the same rule the API Gateway module
already applies to OPTIONS preflight, so preflight and the real response agree.

The origin is stashed per invocation by `handle_errors`, which wraps every
handler and is the only place that sees `event` on the way in.
"""

from __future__ import annotations

import os
from contextvars import ContextVar

#: Comma-delimited, primary first. Mirrors `var.cors_allowed_origins` in
#: xomify-infrastructure — a value added there must be added here too, or the
#: real response will disagree with the preflight that let it through.
DEFAULT_ALLOWED_ORIGINS = (
    "https://xomify.xomware.com,https://xomware.com,https://www.xomware.com"
)

_request_origin: ContextVar[str | None] = ContextVar("request_origin", default=None)


def allowed_origins() -> list[str]:
    """Read on every call rather than at import: a Lambda container outlives a
    configuration change, and this is cheap."""
    raw = os.environ.get("CORS_ALLOWED_ORIGINS") or DEFAULT_ALLOWED_ORIGINS
    return [origin.strip() for origin in raw.split(",") if origin.strip()]


def set_request_origin(event: dict | None) -> None:
    """Record the caller's `Origin` for this invocation.

    Header casing is not guaranteed — API Gateway v1 passes through whatever the
    client sent, and browsers send `Origin` while some proxies lowercase it.
    """
    origin = None
    headers = (event or {}).get("headers") or {}
    if isinstance(headers, dict):
        for key, value in headers.items():
            if isinstance(key, str) and key.lower() == "origin":
                origin = value
                break
    _request_origin.set(origin)


def resolve_origin() -> str:
    """The value for `Access-Control-Allow-Origin`.

    An unrecognised origin gets the primary one, which the browser then refuses
    — the request fails on the client, as it should, without this API ever
    confirming which origins are valid.
    """
    origins = allowed_origins()
    primary = origins[0] if origins else ""
    current = _request_origin.get()
    return current if current in origins else primary


def cors_headers(content_type: str = "application/json") -> dict:
    """Response headers for an API response."""
    return {
        "Access-Control-Allow-Origin": resolve_origin(),
        # Set because the API Gateway preflight sets it. A browser rejects a
        # credentialed request whose actual response omits it, and the two must
        # agree.
        "Access-Control-Allow-Credentials": "true",
        # Tells shared caches that a cached response is only valid for the
        # origin it was fetched for. Without it, CloudFront could serve
        # xomware.com's copy to xomify.xomware.com and break the page.
        "Vary": "Origin",
        "Content-Type": content_type,
    }
