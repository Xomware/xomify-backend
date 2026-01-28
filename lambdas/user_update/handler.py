"""
POST /user/update - Update user (refresh token or enrollments)
"""

from lambdas.common.logger import get_logger
from lambdas.common.errors import handle_errors, ValidationError
from lambdas.common.utility_helpers import success_response, parse_body, require_fields
from lambdas.common.dynamo_helpers import update_user_table_refresh_token, update_user_table_enrollments

log = get_logger(__file__)

HANDLER = 'user_update'


@handle_errors(HANDLER)
def handler(event, context):
    body = parse_body(event)
    require_fields(body, 'email')

    # Determine which update type based on fields present
    has_enrollment_fields = 'wrappedEnrolled' in body or 'releaseRadarEnrolled' in body
    has_token_fields = 'refreshToken' in body and 'userId' in body

    if has_token_fields:
        # Update refresh token (also returns current enrollment status)
        response = update_user_table_refresh_token(
            body['email'],
            body['userId'],
            body['displayName'],
            body['refreshToken'],
            body['avatar']
        )
        log.info(f"Updated refresh token for {body['email']}")

    elif has_enrollment_fields:
        # Update enrollments
        wrapped = body.get('wrappedEnrolled', False)
        radar = body.get('releaseRadarEnrolled', False)

        response = update_user_table_enrollments(
            body['email'],
            wrapped,
            radar
        )
        log.info(f"Updated enrollments for {body['email']}: wrapped={wrapped}, radar={radar}")

    else:
        raise ValidationError(
            message="Invalid request - must include either (refreshToken, userId) or (wrappedEnrolled/releaseRadarEnrolled)",
            handler=HANDLER,
            function="handler"
        )

    return success_response(response)
