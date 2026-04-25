"""
GET /shares/comments - Paginated list of comments on a share, newest first.

Query params:
    email    (required) - viewer email (used for visibility gate)
    shareId  (required) - parent share
    limit    (optional) - page size, default 20, capped at 100
    before   (optional) - ISO8601 createdAt cursor; only items strictly older

Response:
    {
        "comments": [
            {commentId, shareId, email, displayName, avatar, body, createdAt}
            ...
        ],
        "nextBefore": "<ISO8601>" | null
    }
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
    get_query_params,
    require_fields,
)
from lambdas.common.shares_dynamo import get_share
from lambdas.common.share_comments_dynamo import list_comments
from lambdas.common.share_visibility import viewer_can_see_share
from lambdas.common.dynamo_helpers import batch_get_users

log = get_logger(__file__)

HANDLER = "shares_comments_list"
DEFAULT_LIMIT = 20
MAX_LIMIT = 100


def _parse_limit(raw):
    if raw is None:
        return DEFAULT_LIMIT
    try:
        limit = int(raw)
    except (TypeError, ValueError):
        raise ValidationError(
            message="limit must be an integer",
            handler=HANDLER,
            function="handler",
            field="limit",
        )
    if limit <= 0:
        raise ValidationError(
            message="limit must be > 0",
            handler=HANDLER,
            function="handler",
            field="limit",
        )
    if limit > MAX_LIMIT:
        raise ValidationError(
            message=f"limit cannot exceed {MAX_LIMIT}",
            handler=HANDLER,
            function="handler",
            field="limit",
        )
    return limit


@handle_errors(HANDLER)
def handler(event, context):
    params = get_query_params(event)
    require_fields(params, "email", "shareId")

    viewer_email: str = params.get("email")
    share_id: str = params.get("shareId")
    limit = _parse_limit(params.get("limit"))
    before = params.get("before")

    share = get_share(share_id)
    if not share:
        raise NotFoundError(
            message=f"Share {share_id} not found",
            handler=HANDLER,
            function="handler",
            resource="share",
        )

    if not viewer_can_see_share(share, viewer_email):
        log.warning(
            f"Viewer {viewer_email} blocked from listing comments on share {share_id}"
        )
        raise NotFoundError(
            message=f"Share {share_id} not found",
            handler=HANDLER,
            function="handler",
            resource="share",
        )

    items, next_before = list_comments(share_id, limit=limit, before=before)

    # Hydrate author profiles in one batched call.
    author_emails = [item.get("email") for item in items if item.get("email")]
    profiles: dict = {}
    if author_emails:
        try:
            profiles = batch_get_users(author_emails)
        except Exception as err:
            log.warning(f"Profile batch hydrate failed: {err}")

    out = []
    for item in items:
        author = item.get("email")
        profile = profiles.get(author) or {}
        out.append({
            "commentId": item.get("commentId"),
            "shareId": item.get("shareId"),
            "email": author,
            "displayName": profile.get("displayName"),
            "avatar": profile.get("avatar"),
            "body": item.get("body"),
            "createdAt": item.get("createdAt"),
        })

    return success_response({
        "comments": out,
        "nextBefore": next_before,
    })
