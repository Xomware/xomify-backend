"""
POST /invites/decline - Atomically decline (no-op consume) an invite code.

Body:
    {
        "inviteCode": "<code>"
    }

Caller identity (the decliner) is sourced from the authorizer context
(per-user JWT). Falls back to body / query-string `email` during the Track 0
-> Track 1 migration window so legacy static-token clients still work.

Mirrors the invites_accept consume latch so a declined code cannot be
accepted later, and an accepted code cannot be declined afterwards.
"""

from __future__ import annotations

from datetime import datetime, timezone

from botocore.exceptions import ClientError

from lambdas.common.logger import get_logger
from lambdas.common.errors import (
    handle_errors,
    NotFoundError,
    ValidationError,
    XomifyError,
    DynamoDBError,
)
from lambdas.common.utility_helpers import (
    success_response,
    parse_body,
    require_fields,
    get_caller_email,
)
from lambdas.common.invites_dynamo import get_invite, decline_invite

log = get_logger(__file__)

HANDLER = "invites_decline"


def _parse_iso(ts: str | None) -> datetime | None:
    if not ts:
        return None
    try:
        dt = datetime.fromisoformat(ts)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt
    except ValueError:
        return None


@handle_errors(HANDLER)
def handler(event, context):
    body = parse_body(event)
    require_fields(body, "inviteCode")

    # Caller identity comes from the authorizer context (per-user JWT). During
    # the Track 0 -> Track 1 migration window the helper falls back to the
    # body/query-string `email` so legacy static-token clients still work.
    email = get_caller_email(event)
    invite_code = body.get("inviteCode")

    log.info(f"User {email} declining invite {invite_code}")

    invite = get_invite(invite_code)
    if not invite:
        raise NotFoundError(
            message=f"Invite code {invite_code} not found",
            handler=HANDLER,
            function="handler",
            resource="invite",
        )

    if invite.get("consumedAt"):
        raise XomifyError(
            message="Invite has already been consumed",
            handler=HANDLER,
            function="handler",
            status=410,
            details={"error_code": "INVITE_CONSUMED"},
        )

    expires_at = _parse_iso(invite.get("expiresAt"))
    if expires_at is None or expires_at < datetime.now(timezone.utc):
        raise XomifyError(
            message="Invite has expired",
            handler=HANDLER,
            function="handler",
            status=410,
            details={"error_code": "INVITE_EXPIRED"},
        )

    sender_email = invite.get("senderEmail")
    if sender_email == email:
        raise ValidationError(
            message="You cannot decline your own invite",
            handler=HANDLER,
            function="handler",
            field="email",
        )

    try:
        decline_invite(invite_code, email)
    except ClientError as err:
        code = err.response.get("Error", {}).get("Code")
        if code == "ConditionalCheckFailedException":
            raise XomifyError(
                message="Invite is no longer available",
                handler=HANDLER,
                function="handler",
                status=410,
                details={"error_code": "INVITE_UNAVAILABLE"},
            )
        raise DynamoDBError(
            message=str(err),
            handler=HANDLER,
            function="decline_invite",
        )

    log.info(f"Invite {invite_code} declined by {email}")

    return success_response({
        "ok": True,
        "inviteCode": invite_code,
        "senderEmail": sender_email,
    })
