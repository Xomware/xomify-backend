"""
POST /invites/accept - Consume an invite code and auto-friend the sender.
"""

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
from lambdas.common.utility_helpers import success_response, parse_body, require_fields
from lambdas.common.invites_dynamo import get_invite, consume_invite
from lambdas.common.friendships_dynamo import (
    list_all_friends_for_user,
    create_accepted_friendship,
)

log = get_logger(__file__)

HANDLER = 'invites_accept'


def _parse_iso(ts: str | None) -> datetime | None:
    if not ts:
        return None
    try:
        # fromisoformat accepts the isoformat() output produced by _iso_now()
        dt = datetime.fromisoformat(ts)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt
    except ValueError:
        return None


def _is_already_friends(email: str, other_email: str) -> bool:
    friends = list_all_friends_for_user(email)
    for f in friends:
        if f.get('friendEmail') == other_email and f.get('status') == 'accepted':
            return True
    return False


@handle_errors(HANDLER)
def handler(event, context):
    body = parse_body(event)
    require_fields(body, 'email', 'inviteCode')

    email = body.get('email')
    invite_code = body.get('inviteCode')

    log.info(f"User {email} accepting invite {invite_code}")

    invite = get_invite(invite_code)
    if not invite:
        raise NotFoundError(
            message=f"Invite code {invite_code} not found",
            handler=HANDLER,
            function='handler',
            resource='invite',
        )

    sender_email = invite.get('senderEmail')
    if not sender_email:
        raise ValidationError(
            message="Invite is missing senderEmail",
            handler=HANDLER,
            function='handler',
            field='senderEmail',
        )

    if sender_email == email:
        raise ValidationError(
            message="You cannot accept your own invite",
            handler=HANDLER,
            function='handler',
            field='email',
        )

    # 410 Gone: already consumed
    if invite.get('consumedAt'):
        raise XomifyError(
            message="Invite has already been consumed",
            handler=HANDLER,
            function='handler',
            status=410,
            details={"error_code": "INVITE_CONSUMED"},
        )

    # 410 Gone: expired
    expires_at = _parse_iso(invite.get('expiresAt'))
    if expires_at is None or expires_at < datetime.now(timezone.utc):
        raise XomifyError(
            message="Invite has expired",
            handler=HANDLER,
            function='handler',
            status=410,
            details={"error_code": "INVITE_EXPIRED"},
        )

    # 409 Conflict: already friends
    if _is_already_friends(email, sender_email):
        raise XomifyError(
            message=f"You are already friends with {sender_email}",
            handler=HANDLER,
            function='handler',
            status=409,
            details={"error_code": "ALREADY_FRIENDS"},
        )

    # Atomic consume — guards against concurrent accepts
    try:
        consume_invite(invite_code, email)
    except ClientError as err:
        code = err.response.get("Error", {}).get("Code")
        if code == "ConditionalCheckFailedException":
            raise XomifyError(
                message="Invite is no longer available",
                handler=HANDLER,
                function='handler',
                status=410,
                details={"error_code": "INVITE_UNAVAILABLE"},
            )
        raise DynamoDBError(
            message=str(err),
            handler=HANDLER,
            function='consume_invite',
        )

    # Establish accepted friendship in one transaction
    create_accepted_friendship(sender_email, email)

    log.info(f"Invite {invite_code} accepted; {sender_email} <-> {email} now friends")

    return success_response({
        'ok': True,
        'senderEmail': sender_email,
        'inviteCode': invite_code,
    })
