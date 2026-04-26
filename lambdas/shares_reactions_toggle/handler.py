"""
POST /shares/reactions - Toggle an emoji reaction on a share.

Body schema:
    {
        "shareId":  "<uuid>",
        "reaction": "fire" | "heart" | "laugh" | "mind_blown" | "sad" | "thumbs_up"
    }

Caller (viewer) email is sourced from `requestContext.authorizer.email`
via `get_caller_email`; legacy callers may still send `email` in the
body during the Track 0 -> Track 1 migration window.

Behavior:
- If the (user, share, reaction) row exists -> delete it, return active=false.
- Otherwise -> insert it, return active=true.
- Multiple emoji per user per share is allowed (toggling fire and heart
  independently is fine).

Note: this endpoint is distinct from POST /shares/react, which handles the
Spotify queued/rated/unqueued/unrated reaction system. The two coexist
because they store different data and drive different UI surfaces.

Returns:
    {
        "active":   bool,
        "reaction": "<slug>",
        "counts":   {<reaction>: int},
        "viewerReactions": list[str]
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
    parse_body,
    require_fields,
    get_caller_email,
)
from lambdas.common.shares_dynamo import get_share
from lambdas.common.share_reactions_dynamo import (
    VALID_REACTIONS,
    add_reaction,
    build_reaction_summary,
    get_reaction,
    remove_reaction,
)
from lambdas.common.share_visibility import viewer_can_see_share

log = get_logger(__file__)

HANDLER = "shares_reactions_toggle"


@handle_errors(HANDLER)
def handler(event, context):
    body = parse_body(event)
    require_fields(body, "shareId", "reaction")

    email: str = get_caller_email(event)
    share_id: str = body.get("shareId")
    reaction = body.get("reaction")

    if not isinstance(reaction, str) or reaction not in VALID_REACTIONS:
        raise ValidationError(
            message=(
                f"Invalid reaction '{reaction}'. "
                f"Must be one of: {sorted(VALID_REACTIONS)}"
            ),
            handler=HANDLER,
            function="handler",
            field="reaction",
        )

    share = get_share(share_id)
    if not share:
        raise NotFoundError(
            message=f"Share {share_id} not found",
            handler=HANDLER,
            function="handler",
            resource="share",
        )

    if not viewer_can_see_share(share, email):
        log.warning(
            f"Viewer {email} blocked from reacting on share {share_id}"
        )
        raise NotFoundError(
            message=f"Share {share_id} not found",
            handler=HANDLER,
            function="handler",
            resource="share",
        )

    existing = get_reaction(share_id, email, reaction)
    if existing:
        remove_reaction(share_id, email, reaction)
        active = False
    else:
        add_reaction(share_id, email, reaction)
        active = True

    summary = build_reaction_summary(share_id, email)

    return success_response({
        "active": active,
        "reaction": reaction,
        "counts": summary["counts"],
        "viewerReactions": summary["viewerReactions"],
    })
