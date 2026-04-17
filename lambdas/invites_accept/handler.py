"""
POST /invites/accept - Accept an invite code and auto-friend the issuer
"""

from lambdas.common.logger import get_logger
from lambdas.common.errors import handle_errors, NotFoundError, ValidationError
from lambdas.common.utility_helpers import success_response, parse_body, require_fields
from lambdas.common.invites_dynamo import (
    get_invite,
    is_invite_expired,
    mark_invite_accepted,
)
from lambdas.common.friendships_dynamo import (
    send_friend_request,
    accept_friend_request,
)

log = get_logger(__file__)

HANDLER = 'invites_accept'


@handle_errors(HANDLER)
def handler(event, context):
    body = parse_body(event)
    require_fields(body, 'email', 'inviteCode')

    email = body.get('email')
    invite_code = body.get('inviteCode')

    log.info(f"User {email} attempting to accept invite {invite_code}")

    invite = get_invite(invite_code)
    if not invite:
        raise NotFoundError(
            message=f"Invite code {invite_code} not found",
            handler=HANDLER,
            function='handler',
            resource='invite'
        )

    status = invite.get('status')
    if status != 'pending':
        raise ValidationError(
            message=f"Invite is not pending (current status: {status})",
            handler=HANDLER,
            function='handler',
            field='status'
        )

    if is_invite_expired(invite):
        raise ValidationError(
            message="Invite has expired",
            handler=HANDLER,
            function='handler',
            field='expiresAt'
        )

    issuer_email = invite.get('email')
    if not issuer_email:
        raise ValidationError(
            message="Invite is missing issuer email",
            handler=HANDLER,
            function='handler',
            field='email'
        )

    if issuer_email == email:
        raise ValidationError(
            message="You cannot accept your own invite",
            handler=HANDLER,
            function='handler',
            field='email'
        )

    # Mark invite accepted
    mark_invite_accepted(invite_code, email)

    # Auto-friend: issuer sends request, acceptor accepts, resulting in immediate friendship
    log.info(f"Auto-friending {issuer_email} and {email} via invite {invite_code}")
    send_friend_request(issuer_email, email)
    accept_friend_request(email, issuer_email)

    log.info(f"Invite {invite_code} accepted and friendship established")

    return success_response({
        'success': True,
        'inviteCode': invite_code,
        'friendEmail': issuer_email
    })
