"""
POST /shares/create - Create a new share
"""

from lambdas.common.logger import get_logger
from lambdas.common.errors import handle_errors
from lambdas.common.utility_helpers import success_response, parse_body, require_fields
from lambdas.common.shares_dynamo import create_share

log = get_logger(__file__)

HANDLER = 'shares_create'

ALLOWED_TYPES = {"wrapped", "release_radar", "track", "playlist"}


@handle_errors(HANDLER)
def handler(event, context):
    body = parse_body(event)
    require_fields(body, 'email', 'type', 'payload')

    email = body.get('email')
    share_type = body.get('type')
    payload = body.get('payload')
    caption = body.get('caption')

    if share_type not in ALLOWED_TYPES:
        from lambdas.common.errors import ValidationError
        raise ValidationError(
            message=f"Invalid share type '{share_type}'. Must be one of: {sorted(ALLOWED_TYPES)}",
            handler=HANDLER,
            function='handler',
            field='type'
        )

    if not isinstance(payload, dict):
        from lambdas.common.errors import ValidationError
        raise ValidationError(
            message="payload must be a dictionary",
            handler=HANDLER,
            function='handler',
            field='payload'
        )

    log.info(f"User {email} creating share (type={share_type})")
    share_id = create_share(email, share_type, payload, caption)
    log.info(f"Share {share_id} created successfully")

    return success_response({'shareId': share_id})
