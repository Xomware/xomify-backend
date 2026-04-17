"""
POST /shares/react - React to a share (or toggle off with action="none")
"""

from lambdas.common.logger import get_logger
from lambdas.common.errors import handle_errors
from lambdas.common.utility_helpers import success_response, parse_body, require_fields
from lambdas.common.interactions_dynamo import upsert_interaction, delete_interaction

log = get_logger(__file__)

HANDLER = 'shares_react'


@handle_errors(HANDLER)
def handler(event, context):
    body = parse_body(event)
    require_fields(body, 'shareId', 'email', 'action')

    share_id = body.get('shareId')
    email = body.get('email')
    action = body.get('action')

    if action == 'none':
        log.info(f"User {email} removing reaction from share {share_id}")
        success = delete_interaction(share_id, email)
    else:
        log.info(f"User {email} reacting to share {share_id} with action={action}")
        success = upsert_interaction(share_id, email, action)

    return success_response({'success': success})
