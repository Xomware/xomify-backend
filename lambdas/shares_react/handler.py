"""
POST /shares/react - React to a share.

Body schema:
    {
        "shareId": "<uuid>",
        "action":  "queued" | "rated" | "unqueued" | "unrated",
        "rating":  1.0-5.0 (required when action == "rated")
    }

Caller (viewer) email is sourced from `requestContext.authorizer.email`
via `get_caller_email`; legacy callers may still send `email` in the
body during the Track 0 -> Track 1 migration window.

Flow:
    1. Validate body + look up parent share
    2. If action == rated, upsert the canonical track rating
    3. Write the interaction row (queued/rated/unqueued/unrated)
    4. When a new queue reaction takes the share past threshold=3
       distinct reactors AND the reactor is not the author, grab the
       share-row threshold latch and async-invoke notifications_send.
    5. Return the fresh enrichment counts for the share.
"""

from __future__ import annotations

import json
from typing import Any, Optional

import boto3

from lambdas.common.logger import get_logger
from lambdas.common.errors import handle_errors, NotFoundError, ValidationError
from lambdas.common.utility_helpers import (
    success_response,
    parse_body,
    require_fields,
    get_caller_email,
)
from lambdas.common.constants import NOTIFICATIONS_SEND_FUNCTION_NAME
from lambdas.common.interactions_dynamo import (
    VALID_ACTIONS,
    build_enrichment,
    clear_reaction,
    count_distinct_reactors,
    set_reaction,
)
from lambdas.common.shares_dynamo import get_share, mark_threshold_notified
from lambdas.common.track_ratings_dynamo import upsert_track_rating

log = get_logger(__file__)

HANDLER = "shares_react"
QUEUE_THRESHOLD = 3

_lambda_client = boto3.client("lambda", region_name="us-east-1")


def _coerce_rating(raw: Any) -> float:
    try:
        rating = float(raw)
    except (TypeError, ValueError):
        raise ValidationError(
            message="rating must be a number between 1 and 5",
            handler=HANDLER,
            function="handler",
            field="rating",
        )
    if rating < 1.0 or rating > 5.0:
        raise ValidationError(
            message="rating must be between 1 and 5",
            handler=HANDLER,
            function="handler",
            field="rating",
        )
    return rating


def _invoke_threshold_push(
    *,
    recipient_email: str,
    share: dict[str, Any],
    reactor_count: int,
) -> None:
    """Fire-and-forget async invoke of the notifications_send lambda."""
    if not NOTIFICATIONS_SEND_FUNCTION_NAME:
        log.warning(
            "NOTIFICATIONS_SEND_FUNCTION_NAME not set — skipping threshold push"
        )
        return
    event = {
        "kind": "queue_threshold",
        "email": recipient_email,
        "title": "Your share is heating up",
        "body": f"{reactor_count} friends have queued {share.get('trackName') or 'your track'}",
        "customData": {
            "shareId": share.get("shareId"),
            "trackId": share.get("trackId"),
            "trackName": share.get("trackName"),
            "artistName": share.get("artistName"),
            "reactorCount": reactor_count,
        },
    }
    try:
        _lambda_client.invoke(
            FunctionName=NOTIFICATIONS_SEND_FUNCTION_NAME,
            InvocationType="Event",  # async — we don't want to block /shares/react
            Payload=json.dumps(event).encode("utf-8"),
        )
        log.info(
            f"Threshold push dispatched to {recipient_email} for share "
            f"{share.get('shareId')} (reactorCount={reactor_count})"
        )
    except Exception as err:
        # Don't let notification dispatch failures break the interaction write.
        log.error(f"Failed to invoke notifications_send: {err}")


@handle_errors(HANDLER)
def handler(event, context):
    body = parse_body(event)
    require_fields(body, "shareId", "action")

    email = get_caller_email(event)
    share_id = body.get("shareId")
    action = body.get("action")
    raw_rating = body.get("rating")

    if action not in VALID_ACTIONS:
        raise ValidationError(
            message=f"Invalid action '{action}'. Must be one of: {sorted(VALID_ACTIONS)}",
            handler=HANDLER,
            function="handler",
            field="action",
        )

    # Parent share lookup — we need sharedBy for threshold + denormalize for interactions.
    share = get_share(share_id)
    if not share:
        raise NotFoundError(
            message=f"Share {share_id} not found",
            handler=HANDLER,
            function="handler",
            resource="share",
        )

    shared_by = share.get("email")  # author email, from shares table
    if not shared_by:
        raise ValidationError(
            message="Share record is missing author email",
            handler=HANDLER,
            function="handler",
            field="email",
        )

    # Canonical rating write (must happen before interaction row so a
    # viewer refresh never shows rated=True without a ratings row behind it).
    if action == "rated":
        rating = _coerce_rating(raw_rating)
        try:
            upsert_track_rating(
                email=email,
                track_id=share.get("trackId"),
                rating=rating,
                track_name=share.get("trackName") or "",
                artist_name=share.get("artistName") or "",
                album_art=share.get("albumArtUrl") or "",
                album_name=share.get("albumName"),
                context="share",
            )
        except Exception as err:
            # Don't hard-fail the reaction write if the canonical upsert misbehaves —
            # the share row will still reflect the user's rating intent.
            log.warning(f"upsert_track_rating warning: {err}")

    # Interaction row write.
    if action.startswith("un"):
        clear_reaction(share_id, email, action)
    else:
        rating: Optional[float] = None
        if action == "rated":
            rating = _coerce_rating(raw_rating)
        set_reaction(share_id, email, shared_by=shared_by, action=action, rating=rating)

    # Threshold push — only on `queued`, only when not self-react, only at or above 3.
    if action == "queued" and email != shared_by:
        reactor_count = count_distinct_reactors(share_id)
        log.info(
            f"share={share_id} reactorCount={reactor_count} threshold={QUEUE_THRESHOLD}"
        )
        if reactor_count >= QUEUE_THRESHOLD:
            if mark_threshold_notified(share_id, QUEUE_THRESHOLD):
                _invoke_threshold_push(
                    recipient_email=shared_by,
                    share=share,
                    reactor_count=reactor_count,
                )

    enrichment = build_enrichment(share_id, email)
    return success_response(enrichment)
