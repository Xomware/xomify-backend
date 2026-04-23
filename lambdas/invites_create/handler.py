"""
POST /invites/create - Issue a new invite code for a sender (rate-limited).
"""

from botocore.exceptions import ClientError

from lambdas.common.logger import get_logger
from lambdas.common.errors import handle_errors, ValidationError, XomifyError
from lambdas.common.utility_helpers import success_response, parse_body, require_fields
from lambdas.common.invites_dynamo import (
    create_invite,
    generate_invite_code,
    count_outstanding_invites_for_sender,
    MAX_OUTSTANDING_INVITES_PER_SENDER,
)
from lambdas.common.constants import INVITE_URL_TEMPLATE

log = get_logger(__file__)

HANDLER = 'invites_create'

# How many distinct codes to try before giving up on collision retries.
COLLISION_RETRY_LIMIT = 2


@handle_errors(HANDLER)
def handler(event, context):
    body = parse_body(event)
    require_fields(body, 'email')

    sender_email = body.get('email')

    # Rate limit — max 10 outstanding invites per sender
    outstanding = count_outstanding_invites_for_sender(sender_email)
    log.info(f"{sender_email} has {outstanding} outstanding invites")
    if outstanding >= MAX_OUTSTANDING_INVITES_PER_SENDER:
        raise XomifyError(
            message=f"Max {MAX_OUTSTANDING_INVITES_PER_SENDER} outstanding invites",
            handler=HANDLER,
            function='handler',
            status=429,
            details={"field": "rateLimit"},
        )

    last_err: Exception | None = None
    item = None
    for attempt in range(COLLISION_RETRY_LIMIT + 1):
        code = generate_invite_code()
        try:
            item = create_invite(sender_email, code)
            break
        except ClientError as err:
            if err.response.get("Error", {}).get("Code") == "ConditionalCheckFailedException":
                log.warning(f"Invite code collision on attempt {attempt + 1}: {code}")
                last_err = err
                continue
            raise

    if item is None:
        log.error(f"Exhausted {COLLISION_RETRY_LIMIT + 1} invite code attempts")
        raise ValidationError(
            message="Could not allocate a unique invite code, try again",
            handler=HANDLER,
            function='handler',
            field='inviteCode',
        )

    invite_code = item['inviteCode']
    invite_url = INVITE_URL_TEMPLATE.format(code=invite_code)

    log.info(f"Invite {invite_code} issued for {sender_email}")

    return success_response({
        'inviteCode': invite_code,
        'inviteUrl': invite_url,
        'expiresAt': item.get('expiresAt'),
        'createdAt': item.get('createdAt'),
    })
