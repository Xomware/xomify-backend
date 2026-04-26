"""
POST /shares/comments - Create a comment on a share.

Body schema:
    {
        "shareId": "<uuid>",
        "body":    "comment text (<= 500 chars)"
    }

Caller identity is sourced from `requestContext.authorizer.email` via
`get_caller_email`; legacy callers may still send `email` in the body
during the Track 0 -> Track 1 migration window (see auth-identity epic).

Returns the persisted comment row, hydrated with displayName + avatar so
the iOS client can render it without a follow-up profile fetch.
"""

from __future__ import annotations

from lambdas.common.logger import get_logger
from lambdas.common.errors import (
    handle_errors,
    NotFoundError,
    ValidationError,
)
from lambdas.common.utility_helpers import (
    success_response,
    parse_body,
    require_fields,
    get_caller_email,
)
from lambdas.common.shares_dynamo import get_share
from lambdas.common.share_comments_dynamo import create_comment
from lambdas.common.share_visibility import viewer_can_see_share
from lambdas.common.dynamo_helpers import batch_get_users

log = get_logger(__file__)

HANDLER = "shares_comments_create"
BODY_MAX_LEN = 500


@handle_errors(HANDLER)
def handler(event, context):
    body = parse_body(event)
    require_fields(body, "shareId", "body")

    email: str = get_caller_email(event)
    share_id: str = body.get("shareId")
    text: str = body.get("body")

    if not isinstance(text, str):
        raise ValidationError(
            message="body must be a string",
            handler=HANDLER,
            function="handler",
            field="body",
        )

    text = text.strip()
    if not text:
        raise ValidationError(
            message="body must not be empty",
            handler=HANDLER,
            function="handler",
            field="body",
        )
    if len(text) > BODY_MAX_LEN:
        raise ValidationError(
            message=f"body exceeds {BODY_MAX_LEN} characters",
            handler=HANDLER,
            function="handler",
            field="body",
        )

    share = get_share(share_id)
    if not share:
        raise NotFoundError(
            message=f"Share {share_id} not found",
            handler=HANDLER,
            function="handler",
            resource="share",
        )

    # Visibility gate — return 404 for non-readers so existence isn't leaked.
    if not viewer_can_see_share(share, email):
        log.warning(
            f"Viewer {email} blocked from commenting on share {share_id}"
        )
        raise NotFoundError(
            message=f"Share {share_id} not found",
            handler=HANDLER,
            function="handler",
            resource="share",
        )

    comment = create_comment(share_id=share_id, email=email, body=text)

    # Hydrate author profile for the iOS card.
    profile_map: dict = {}
    try:
        profile_map = batch_get_users([email])
    except Exception as err:
        log.warning(f"Profile hydrate failed for {email}: {err}")

    profile = profile_map.get(email) or {}
    payload = {
        "commentId": comment.get("commentId"),
        "shareId": comment.get("shareId"),
        "email": comment.get("email"),
        "displayName": profile.get("displayName"),
        "avatar": profile.get("avatar"),
        "body": comment.get("body"),
        "createdAt": comment.get("createdAt"),
    }
    return success_response(payload)
