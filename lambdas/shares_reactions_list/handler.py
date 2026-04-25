"""
GET /shares/reactions - Per-emoji reaction counts + the viewer's own taps.

Query params:
    email    (required) - viewer email
    shareId  (required) - parent share

Response:
    {
        "counts": { "fire": 3, "heart": 1, ... },   # only emoji with > 0
        "viewerReactions": ["fire"]                  # what the viewer tapped
    }
"""

from __future__ import annotations

from lambdas.common.logger import get_logger
from lambdas.common.errors import handle_errors, NotFoundError
from lambdas.common.utility_helpers import (
    success_response,
    get_query_params,
    require_fields,
)
from lambdas.common.shares_dynamo import get_share
from lambdas.common.share_reactions_dynamo import build_reaction_summary
from lambdas.common.share_visibility import viewer_can_see_share

log = get_logger(__file__)

HANDLER = "shares_reactions_list"


@handle_errors(HANDLER)
def handler(event, context):
    params = get_query_params(event)
    require_fields(params, "email", "shareId")

    viewer_email: str = params.get("email")
    share_id: str = params.get("shareId")

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
            f"Viewer {viewer_email} blocked from reading reactions on share {share_id}"
        )
        raise NotFoundError(
            message=f"Share {share_id} not found",
            handler=HANDLER,
            function="handler",
            resource="share",
        )

    summary = build_reaction_summary(share_id, viewer_email)
    return success_response(summary)
