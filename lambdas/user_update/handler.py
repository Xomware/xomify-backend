"""
POST /user/update - Update the caller's row (refresh token or enrollments).

Caller identity (`email`, `userId`) comes from the trusted authorizer
context when present, falling back to the request body during the Track-1
migration window. Profile data being persisted (`displayName`,
`refreshToken`, `avatar`) and the enrollment flags (`wrappedEnrolled`,
`releaseRadarEnrolled`) continue to live in the body — they are payload,
not caller-identity claims.

Branch detection:
- Token-persistence path: body contains `refreshToken`. Caller `userId`
  is also required for this path and is resolved from context (or body
  fallback). Triggered post-Spotify-OAuth on iOS.
- Enrollment path: body contains `wrappedEnrolled` or `releaseRadarEnrolled`.
"""

from lambdas.common.dynamo_helpers import (
    update_user_table_enrollments,
    update_user_table_refresh_token,
)
from lambdas.common.errors import ValidationError, handle_errors
from lambdas.common.logger import get_logger
from lambdas.common.utility_helpers import (
    get_caller_email,
    get_caller_user_id,
    parse_body,
    success_response,
)

log = get_logger(__file__)

HANDLER = 'user_update'


@handle_errors(HANDLER)
def handler(event, context):
    body = parse_body(event)
    caller_email = get_caller_email(event)

    has_enrollment_fields = 'wrappedEnrolled' in body or 'releaseRadarEnrolled' in body
    has_token_fields = 'refreshToken' in body

    if has_token_fields:
        # Token-persistence path. userId, displayName, refreshToken, avatar
        # are all required for this branch. userId is caller identity (resolved
        # via context, or fallback to body during migration); the rest are
        # profile fields that live in the body.
        caller_user_id = get_caller_user_id(event)
        display_name = body.get('displayName')
        refresh_token = body.get('refreshToken')
        avatar = body.get('avatar')

        missing = [
            name for name, value in (
                ('displayName', display_name),
                ('refreshToken', refresh_token),
                ('avatar', avatar),
            )
            if value is None
        ]
        if missing:
            raise ValidationError(
                message=f"Missing required fields: {', '.join(missing)}",
                handler=HANDLER,
                function='handler',
                field=missing[0],
            )

        response = update_user_table_refresh_token(
            caller_email,
            caller_user_id,
            display_name,
            refresh_token,
            avatar,
        )
        log.info(f"Updated refresh token for {caller_email}")

    elif has_enrollment_fields:
        wrapped = body.get('wrappedEnrolled', False)
        radar = body.get('releaseRadarEnrolled', False)

        response = update_user_table_enrollments(
            caller_email,
            wrapped,
            radar,
        )
        log.info(
            f"Updated enrollments for {caller_email}: wrapped={wrapped}, radar={radar}"
        )

    else:
        raise ValidationError(
            message=(
                "Invalid request - must include either refreshToken (with "
                "displayName + avatar) or wrappedEnrolled/releaseRadarEnrolled"
            ),
            handler=HANDLER,
            function='handler',
        )

    return success_response(response)
