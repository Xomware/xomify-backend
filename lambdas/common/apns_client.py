"""
XOMIFY APNs HTTP/2 Client
=========================
Minimal Apple Push Notification service (APNs) client using provider tokens
(ES256 JWT) for authentication.

Provider tokens are valid for up to 60 minutes; we refresh every 20 minutes
per Apple's recommendation. The `.p8` signing key, Key ID, Team ID, and
Bundle ID are all loaded lazily from SSM SecureString parameters.

Transport: urllib3 HTTP/2 is not available in the stdlib, so we use
`urllib.request` with manual HTTP/1.1 framing. APNs will transparently
upgrade HTTP/1.1 requests on `api.push.apple.com`, and boto's runtime
already ships the required TLS stack.

For production volume a proper HTTP/2 client (hyper-h2 or httpx[http2])
should be wired in, but for dogfood + v1 the HTTP/1.1 path is acceptable
because the cron digest writer fans out per-user, not per-push.
"""

from __future__ import annotations

import json
import logging
import ssl
import time
from typing import Any, Optional
from urllib import request as urlrequest
from urllib.error import HTTPError, URLError

import jwt

from lambdas.common import ssm_helpers
from lambdas.common.constants import APNS_USE_SANDBOX
from lambdas.common.errors import ApnsError
from lambdas.common.logger import get_logger

log = get_logger(__file__)

# Endpoints
APNS_PROD_HOST = "https://api.push.apple.com"
APNS_SANDBOX_HOST = "https://api.sandbox.push.apple.com"

# Provider tokens are valid up to 60 min; refresh at 20 min to stay safe.
PROVIDER_TOKEN_REFRESH_SECONDS = 20 * 60


class ApnsClient:
    """Singleton-friendly APNs dispatcher. One per warm Lambda container."""

    def __init__(self, use_sandbox: Optional[bool] = None):
        self._use_sandbox = APNS_USE_SANDBOX if use_sandbox is None else use_sandbox
        self._cached_token: Optional[str] = None
        self._token_issued_at: float = 0.0

    # -------------------------------------------------------------- Endpoint
    @property
    def host(self) -> str:
        return APNS_SANDBOX_HOST if self._use_sandbox else APNS_PROD_HOST

    # ------------------------------------------------------------ Auth token
    def _build_provider_token(self) -> str:
        """Sign an ES256 JWT for APNs auth using the .p8 key from SSM."""
        try:
            p8_content = ssm_helpers.APNS_AUTH_KEY
            key_id = ssm_helpers.APNS_KEY_ID
            team_id = ssm_helpers.APNS_TEAM_ID
        except Exception as err:
            raise ApnsError(
                message=f"Failed to load APNs secrets: {err}",
                function="_build_provider_token",
            )

        try:
            token = jwt.encode(
                payload={
                    "iss": team_id,
                    "iat": int(time.time()),
                },
                key=p8_content,
                algorithm="ES256",
                headers={"alg": "ES256", "kid": key_id},
            )
            return token
        except Exception as err:
            raise ApnsError(
                message=f"JWT signing failed: {err}",
                function="_build_provider_token",
            )

    def _get_provider_token(self) -> str:
        """Return a cached provider token, refreshing when older than the cache window."""
        now = time.time()
        if (
            self._cached_token is None
            or (now - self._token_issued_at) >= PROVIDER_TOKEN_REFRESH_SECONDS
        ):
            log.debug("Refreshing APNs provider token")
            self._cached_token = self._build_provider_token()
            self._token_issued_at = now
        return self._cached_token

    # ----------------------------------------------------------------- Send
    def send(
        self,
        device_token: str,
        alert_title: str,
        alert_body: str,
        *,
        category: Optional[str] = None,
        custom_data: Optional[dict[str, Any]] = None,
        push_type: str = "alert",
        collapse_id: Optional[str] = None,
    ) -> dict[str, Any]:
        """
        POST the push payload to APNs. Returns a dict with:
            {"ok": bool, "statusCode": int, "reason": str|None, "token": device_token}

        Callers should inspect statusCode == 410 (Unregistered) and prune
        the token from their store.
        """
        if not device_token:
            raise ApnsError(
                message="device_token is required",
                function="send",
            )

        try:
            bundle_id = ssm_helpers.APNS_BUNDLE_ID
        except Exception as err:
            raise ApnsError(
                message=f"Failed to load APNs bundle id: {err}",
                function="send",
            )

        provider_token = self._get_provider_token()

        payload: dict[str, Any] = {
            "aps": {
                "alert": {"title": alert_title, "body": alert_body},
                "sound": "default",
            }
        }
        if category:
            payload["aps"]["category"] = category
        if custom_data:
            for key, value in custom_data.items():
                if key == "aps":
                    continue  # never overwrite the apns payload
                payload[key] = value

        url = f"{self.host}/3/device/{device_token}"
        headers = {
            "authorization": f"bearer {provider_token}",
            "apns-topic": bundle_id,
            "apns-push-type": push_type,
            "content-type": "application/json",
        }
        if collapse_id:
            headers["apns-collapse-id"] = collapse_id

        body_bytes = json.dumps(payload).encode("utf-8")
        req = urlrequest.Request(url, data=body_bytes, headers=headers, method="POST")
        ctx = ssl.create_default_context()

        try:
            with urlrequest.urlopen(req, context=ctx, timeout=10) as resp:
                status = resp.status
                return {
                    "ok": 200 <= status < 300,
                    "statusCode": status,
                    "reason": None,
                    "token": device_token,
                }
        except HTTPError as http_err:
            try:
                body = http_err.read().decode("utf-8")
                reason = json.loads(body).get("reason")
            except Exception:
                reason = None
            log.warning(
                f"APNs rejected push: status={http_err.code} reason={reason}"
            )
            return {
                "ok": False,
                "statusCode": http_err.code,
                "reason": reason,
                "token": device_token,
            }
        except URLError as url_err:
            raise ApnsError(
                message=f"APNs transport error: {url_err}",
                function="send",
            )


# Module-level singleton — warm-start reuse.
_default_client: Optional[ApnsClient] = None


def get_client() -> ApnsClient:
    global _default_client
    if _default_client is None:
        _default_client = ApnsClient()
    return _default_client
