"""
POST /shares/listened - Mark one or more shares as listened by the caller.

Body schema:
    {
        "shareIds": ["<uuid>", "<uuid>", ...],   // required, capped at 25
        "source":   "queue" | "play"             // optional, defaults to "queue"
    }

Caller (viewer) email is sourced from `requestContext.authorizer.email`
via `get_caller_email`.

Behavior:
    1. Validate body shape + source enum + cap at 25 shareIds.
    2. For each shareId, look up the share row. Missing shares are skipped
       (logged, not 404'd) so a stale client cache doesn't abort the whole
       batch.
    3. For each existing share, idempotently mark the caller as a listener
       via mark_listened(...).
    4. Return {ok: True, listened: [...written], skipped: [...missing]}.

This endpoint backs Bug 2: when a viewer hits Queue or Play Now on a share
card, the share should flip from "never listened" to "listened". The iOS
QueueActionController used to only talk to Spotify; now it also fires a
POST here so the listener row lands in DDB.
"""

from __future__ import annotations

from lambdas.common.logger import get_logger
from lambdas.common.errors import handle_errors, ValidationError
from lambdas.common.utility_helpers import (
    success_response,
    parse_body,
    require_fields,
    get_caller_email,
)
from lambdas.common.shares_dynamo import get_share
from lambdas.common.share_listeners_dynamo import mark_listened

log = get_logger(__file__)

HANDLER = "shares_listened"

VALID_SOURCES = {"queue", "play"}
MAX_BATCH = 25


@handle_errors(HANDLER)
def handler(event, context):
    body = parse_body(event)
    require_fields(body, "shareIds")

    email = get_caller_email(event)
    raw_share_ids = body.get("shareIds")
    raw_source = body.get("source", "queue")

    if not isinstance(raw_share_ids, list):
        raise ValidationError(
            message="shareIds must be a list of share id strings",
            handler=HANDLER,
            function="handler",
            field="shareIds",
        )

    if len(raw_share_ids) == 0:
        raise ValidationError(
            message="shareIds must contain at least one entry",
            handler=HANDLER,
            function="handler",
            field="shareIds",
        )

    if len(raw_share_ids) > MAX_BATCH:
        raise ValidationError(
            message=f"shareIds capped at {MAX_BATCH} entries per call",
            handler=HANDLER,
            function="handler",
            field="shareIds",
        )

    # Normalize / dedupe while preserving order.
    seen: set[str] = set()
    share_ids: list[str] = []
    for sid in raw_share_ids:
        if not isinstance(sid, str) or not sid.strip():
            raise ValidationError(
                message="shareIds entries must be non-empty strings",
                handler=HANDLER,
                function="handler",
                field="shareIds",
            )
        sid = sid.strip()
        if sid in seen:
            continue
        seen.add(sid)
        share_ids.append(sid)

    # Validate source enum (handler-level only — the helper accepts a wider
    # set including "author_create" used by shares_create).
    if not isinstance(raw_source, str) or raw_source not in VALID_SOURCES:
        raise ValidationError(
            message=f"source must be one of: {sorted(VALID_SOURCES)}",
            handler=HANDLER,
            function="handler",
            field="source",
        )

    listened: list[str] = []
    skipped: list[str] = []

    for share_id in share_ids:
        share = get_share(share_id)
        if not share:
            log.warning(
                f"shares_listened: skipping unknown share_id={share_id} for {email}"
            )
            skipped.append(share_id)
            continue
        try:
            mark_listened(share_id, email, source=raw_source)
            listened.append(share_id)
        except Exception as err:
            # Don't 500 the whole batch on a single row's DDB hiccup.
            log.error(
                f"shares_listened: mark_listened failed for share={share_id}, "
                f"email={email}: {err}"
            )
            skipped.append(share_id)

    log.info(
        f"shares_listened: email={email} source={raw_source} "
        f"listened={len(listened)} skipped={len(skipped)}"
    )
    return success_response({
        "ok": True,
        "listened": listened,
        "skipped": skipped,
    })
