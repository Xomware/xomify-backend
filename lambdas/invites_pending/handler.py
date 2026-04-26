"""
GET /invites/pending - List outstanding invite codes issued by the caller.

Invites in this system are deep-link codes minted by a sender and shared via
URL — they have no recipient email until somebody accepts. This endpoint
therefore returns invites where the authenticated user is the SENDER and
the invite is still outstanding (not yet consumed, not yet expired). The
iOS Friends screen uses this to show "your outstanding invites" so the user
can manage / resend them.

Caller identity:
    Sourced from the authorizer context (per-user JWT). Falls back to
    `queryStringParameters.email` during the Track 0 -> Track 1 migration
    window so legacy static-token clients still work.

Response:
    {
        "invites": [ {inviteCode, senderEmail, createdAt, expiresAt, ...}, ... ],
        "count": int
    }
"""

from __future__ import annotations

from lambdas.common.logger import get_logger
from lambdas.common.errors import handle_errors
from lambdas.common.utility_helpers import (
    success_response,
    get_caller_email,
)
from lambdas.common.invites_dynamo import list_invites_by_sender
from lambdas.common.constants import INVITE_URL_TEMPLATE

log = get_logger(__file__)

HANDLER = "invites_pending"


@handle_errors(HANDLER)
def handler(event, context):
    # Caller identity comes from the authorizer context (per-user JWT). During
    # the Track 0 -> Track 1 migration window the helper falls back to the
    # query-string `email` so legacy static-token clients still work.
    email = get_caller_email(event)

    log.info(f"Listing pending (outstanding) invites for {email}")
    invites = list_invites_by_sender(email, active_only=True)

    # Hydrate each invite with the shareable URL so the client doesn't have
    # to know the template.
    hydrated = []
    for invite in invites:
        code = invite.get("inviteCode")
        if code:
            invite["inviteUrl"] = INVITE_URL_TEMPLATE.format(code=code)
        hydrated.append(invite)

    return success_response({
        "email": email,
        "invites": hydrated,
        "count": len(hydrated),
    })
