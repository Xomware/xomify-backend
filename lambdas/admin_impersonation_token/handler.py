"""
GET /admin/impersonation-token?email= - Mint a fresh Spotify access token for
any user (admin only).

Unlike `/admin/view-as` (a read-only projection of the target's own
email-keyed data), this endpoint hands back a short-lived, LIVE Spotify access
token minted from the target user's stored `refreshToken`. It lets an admin
impersonate the target against Spotify-derived surfaces (top items,
recently-played, now-playing, playlists, profile) exactly as that user would.

Security:
- The admin gate (`require_admin`) resolves the TRUE caller identity from the
  authorizer context and enforces `email == ADMIN_EMAIL`. It never trusts an
  impersonated identity, and non-admins receive HTTP 403.
- Only the target's short-lived ACCESS token is returned. The refresh token is
  never returned and token values are never logged (masked in structured logs).
- The request-log hook already audits this call like any other route.

Response (200):
{
  "accessToken": "<short-lived Spotify access token>",
  "expiresIn": 3600
}

Errors:
- 400 if `email` query param is missing.
- 403 if the caller is not the configured admin.
- 404 if the target user (or their refresh token) does not exist.
"""

from lambdas.common.admin import require_admin
from lambdas.common.dynamo_helpers import get_user_table_data
from lambdas.common.errors import (
    NotFoundError,
    ValidationError,
    handle_errors,
    mask_sensitive_data,
)
from lambdas.common.logger import get_logger
from lambdas.common.spotify import Spotify
from lambdas.common.utility_helpers import get_query_params, success_response

log = get_logger(__file__)

HANDLER = "admin_impersonation_token"

# Spotify short-lived access tokens default to 3600s; used only when Spotify
# omits `expires_in` from its refresh response.
_DEFAULT_EXPIRES_IN = 3600


@handle_errors(HANDLER)
def handler(event, context):
    # Admin gate: resolves and verifies the TRUE caller (never an impersonated
    # identity). Raises 401 if unauthenticated, 403 if not the admin.
    admin_email = require_admin(event)

    params = get_query_params(event)
    email = params.get("email")
    if not email:
        raise ValidationError("email is required", handler=HANDLER, field="email")

    try:
        user = get_user_table_data(email)
    except NotFoundError:
        raise NotFoundError(
            message=f"No user found for {email}",
            handler=HANDLER,
            resource=email,
        )

    if not user.get("refreshToken"):
        # Target exists but never connected Spotify (or token was cleared) —
        # nothing to impersonate.
        raise NotFoundError(
            message=f"No Spotify refresh token for {email}",
            handler=HANDLER,
            resource=email,
        )

    # Reuse the SAME client-credentials + refresh flow the crons use
    # (Spotify.get_access_token, invoked by the sync constructor). This mints a
    # fresh access token from the target's stored refresh token.
    spotify = Spotify(user)
    access_token = spotify.access_token
    expires_in = spotify.token_expires_in or _DEFAULT_EXPIRES_IN

    if not access_token:
        # Defensive: the refresh flow raises on failure, but never hand back a
        # null token.
        raise NotFoundError(
            message=f"Could not mint Spotify access token for {email}",
            handler=HANDLER,
            resource=email,
        )

    # Never log token values.
    log.info(
        "admin_impersonation_token by=%s target=%s minted=%s",
        admin_email,
        email,
        mask_sensitive_data({"accessToken": access_token}),
    )

    return success_response({
        "accessToken": access_token,
        "expiresIn": expires_in,
    })
