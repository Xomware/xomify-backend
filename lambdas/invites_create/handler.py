"""
POST /invites/create - Create a new invite link
"""

from lambdas.common.logger import get_logger
from lambdas.common.errors import handle_errors
from lambdas.common.utility_helpers import success_response, parse_body, require_fields
from lambdas.common.invites_dynamo import create_invite
from lambdas.common.constants import XOMIFY_URL

log = get_logger(__file__)

HANDLER = 'invites_create'


@handle_errors(HANDLER)
def handler(event, context):
    body = parse_body(event)
    require_fields(body, 'email')

    email = body.get('email')

    log.info(f"User {email} creating invite")
    invite = create_invite(email)
    invite_code = invite.get('inviteCode')
    share_url = f"{XOMIFY_URL}/invite/{invite_code}"

    log.info(f"Invite {invite_code} issued for {email}")

    return success_response({
        'inviteCode': invite_code,
        'shareUrl': share_url,
        'expiresAt': invite.get('expiresAt'),
        'status': invite.get('status')
    })
