"""
DELETE /shares/comments - Hard-delete a comment.

Body schema:
    {
        "email":     "viewer@...",
        "shareId":   "<uuid>",
        "commentId": "<uuid>"
    }

Authorization:
- Comment author OR share author may delete.
- Anyone else gets 403.

Returns: { "deleted": true, "commentId": "<uuid>" }
"""

from __future__ import annotations

from lambdas.common.logger import get_logger
from lambdas.common.errors import (
    handle_errors,
    NotFoundError,
    AuthorizationError,
)
from lambdas.common.utility_helpers import (
    success_response,
    parse_body,
    require_fields,
)
from lambdas.common.shares_dynamo import get_share
from lambdas.common.share_comments_dynamo import get_comment, delete_comment

log = get_logger(__file__)

HANDLER = "shares_comments_delete"


@handle_errors(HANDLER)
def handler(event, context):
    body = parse_body(event)
    require_fields(body, "email", "shareId", "commentId")

    email: str = body.get("email")
    share_id: str = body.get("shareId")
    comment_id: str = body.get("commentId")

    share = get_share(share_id)
    if not share:
        raise NotFoundError(
            message=f"Share {share_id} not found",
            handler=HANDLER,
            function="handler",
            resource="share",
        )

    comment = get_comment(share_id, comment_id)
    if not comment:
        raise NotFoundError(
            message=f"Comment {comment_id} not found",
            handler=HANDLER,
            function="handler",
            resource="comment",
        )

    comment_author = comment.get("email")
    share_author = share.get("email")

    if email != comment_author and email != share_author:
        log.warning(
            f"Forbidden delete: viewer={email} comment={comment_id} "
            f"commentAuthor={comment_author} shareAuthor={share_author}"
        )
        raise AuthorizationError(
            message="Not authorized to delete this comment",
            handler=HANDLER,
            function="handler",
        )

    delete_comment(share_id, comment.get("createdAtId"))

    return success_response({
        "deleted": True,
        "commentId": comment_id,
    })
