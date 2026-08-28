"""
XOMIFY APNs HTTP/2 Client
=========================
Minimal Apple Push Notification service (APNs) client using provider tokens
(ES256 JWT) for authentication.

Provider tokens are valid for up to 60 minutes; we refresh every 20 minutes
per Apple's recommendation. The `.p8` signing key, Key ID, Team ID, and
Bundle ID are all loaded lazily from SSM SecureString parameters.

Transport: httpx with http2=True. APNs is HTTP/2 ONLY -- it does not
upgrade an HTTP/1.1 request, it rejects it outright with
`Unexpected HTTP/1.x request: POST /3/device/...`, which is what every
push this service ever sent received. There is no stdlib HTTP/2 client,
so this is a real dependency rather than a preference.

The client is held open on the module singleton so a warm container
reuses one TLS connection and one HTTP/2 session across a fan-out.
"""

from __future__ import annotations

import logging
import time
from typing import Any, Optional

import httpx
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
        self._http: Optional[httpx.Client] = None

    @property
    def http(self) -> httpx.Client:
        """Lazy so constructing a client costs nothing until something sends."""
        if self._http is None:
            self._http = httpx.Client(http2=True, timeout=10.0)
        return self._http

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

        try:
            resp = self.http.post(url, json=payload, headers=headers)
        except httpx.HTTPError as err:
            raise ApnsError(
                message=f"APNs transport error: {err}",
                function="send",
            )

        if resp.is_success:
            return {
                "ok": True,
                "statusCode": resp.status_code,
                "reason": None,
                "token": device_token,
            }

        # APNs explains every rejection in a JSON `reason`, and the caller keys
        # token pruning off 410 -- so a failure is returned, not raised.
        try:
            reason = resp.json().get("reason")
        except Exception:
            reason = resp.text or None
        log.warning(f"APNs rejected push: status={resp.status_code} reason={reason}")
        return {
            "ok": False,
            "statusCode": resp.status_code,
            "reason": reason,
            "token": device_token,
        }


# Module-level singleton — warm-start reuse.
_default_client: Optional[ApnsClient] = None


def get_client() -> ApnsClient:
    global _default_client
    if _default_client is None:
        _default_client = ApnsClient()
    return _default_client
