"""APNs transport (HTTP/2)."""

import httpx
import pytest

from lambdas.common.apns_client import ApnsClient


def test_client_negotiates_http2():
    """APNs rejects HTTP/1.1 outright with `Unexpected HTTP/1.x request`, which
    is what every push this service sent used to get. The flag is the fix."""
    client = ApnsClient()
    assert isinstance(client.http, httpx.Client)
    # httpx exposes the negotiated protocols on the transport it built.
    assert client.http._transport._pool._http2 is True


def test_http_client_is_reused_across_sends():
    """One TLS connection and one HTTP/2 session per warm container — a fan-out
    that reconnects per push is the thing HTTP/2 exists to avoid."""
    client = ApnsClient()
    assert client.http is client.http
