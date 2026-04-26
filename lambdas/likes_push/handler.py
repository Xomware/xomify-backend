"""
POST /likes/push - Persist the caller's most-recent saved tracks.

Body schema:
    {
        "email":  "<caller email>",
        "total":  <int — caller-reported total saved-tracks count>,
        "tracks": [
            {
                "trackId":   "<spotify track id>",
                "addedAt":   "<ISO8601 timestamp>",
                "name":      "<track name, optional>",
                "artist":    "<artist name, optional>",
                "albumArt":  "<image url, optional>"
            },
            ...
        ]
    }

Behavior:
- Caller identity (``email``) is resolved from the trusted authorizer
  context with the standard body/query fallback. The ``email`` field in
  the body MUST equal the resolved caller email — cross-user pushes are
  rejected with 403.
- ``tracks`` is capped server-side at ``MAX_LIKES_PAGE`` (200). This
  matches the iOS-side cap; we enforce here as defense in depth so a
  buggy / malicious client can't blow our write budget.
- Throttle: if ``total`` matches the cached ``likes_count`` AND the
  first track's ``addedAt`` matches the cached ``likes_updated_at``,
  we assume nothing changed and skip the items write entirely (we still
  refresh ``likes_updated_at`` so "I'm alive" is observable).
- Otherwise: upsert the items, then write back the new
  ``likes_count`` + ``likes_updated_at`` on the user record.

Returns:
    {
        "throttled":  bool,
        "written":    int,
        "likesCount": int,
        "likesUpdatedAt": str
    }
"""

from __future__ import annotations

from lambdas.common.errors import (
    AuthorizationError,
    ValidationError,
    handle_errors,
)
from lambdas.common.logger import get_logger
from lambdas.common.user_likes_dynamo import (
    MAX_LIKES_PAGE,
    get_likes_settings,
    set_user_likes_count,
    upsert_user_likes,
)
from lambdas.common.utility_helpers import (
    get_caller_email,
    parse_body,
    require_fields,
    success_response,
)

log = get_logger(__file__)

HANDLER = "likes_push"


def _coerce_int(raw, field: str) -> int:
    """Coerce ``raw`` to ``int``, raising ValidationError on failure."""
    if isinstance(raw, bool):
        # bool is a subclass of int in Python — reject explicitly so
        # `True` / `False` don't silently become 1 / 0.
        raise ValidationError(
            message=f"{field} must be an integer",
            handler=HANDLER,
            function="handler",
            field=field,
        )
    try:
        return int(raw)
    except (TypeError, ValueError):
        raise ValidationError(
            message=f"{field} must be an integer",
            handler=HANDLER,
            function="handler",
            field=field,
        )


def _validate_tracks(raw) -> list[dict]:
    """Normalize + validate the ``tracks`` payload.

    Drops trailing entries past ``MAX_LIKES_PAGE`` and rejects malformed
    rows. Returns the cleaned list (possibly empty — empty is allowed
    so the client can push a "0 saved tracks" state).
    """
    if raw is None:
        return []
    if not isinstance(raw, list):
        raise ValidationError(
            message="tracks must be a list",
            handler=HANDLER,
            function="handler",
            field="tracks",
        )

    cleaned: list[dict] = []
    for idx, entry in enumerate(raw[:MAX_LIKES_PAGE]):
        if not isinstance(entry, dict):
            raise ValidationError(
                message=f"tracks[{idx}] must be an object",
                handler=HANDLER,
                function="handler",
                field="tracks",
            )
        track_id = entry.get("trackId")
        added_at = entry.get("addedAt")
        if not isinstance(track_id, str) or not track_id.strip():
            raise ValidationError(
                message=f"tracks[{idx}].trackId is required",
                handler=HANDLER,
                function="handler",
                field="tracks",
            )
        if not isinstance(added_at, str) or not added_at.strip():
            raise ValidationError(
                message=f"tracks[{idx}].addedAt is required",
                handler=HANDLER,
                function="handler",
                field="tracks",
            )
        cleaned.append(entry)

    return cleaned


@handle_errors(HANDLER)
def handler(event, context):
    body = parse_body(event)
    require_fields(body, "email", "total", "tracks")

    body_email = body.get("email")
    caller_email = get_caller_email(event)

    # Cross-user push is never allowed — caller can only push their own likes.
    if not isinstance(body_email, str) or body_email != caller_email:
        log.warning(
            f"Cross-user push rejected: caller={caller_email} bodyEmail={body_email}"
        )
        raise AuthorizationError(
            message="Not authorized to push likes for another user",
            handler=HANDLER,
            function="handler",
        )

    total = _coerce_int(body.get("total"), "total")
    if total < 0:
        raise ValidationError(
            message="total must be >= 0",
            handler=HANDLER,
            function="handler",
            field="total",
        )

    tracks = _validate_tracks(body.get("tracks"))

    log.info(
        f"likes_push: email={caller_email} total={total} trackCount={len(tracks)}"
    )

    # Throttle path — if the count matches AND the most-recent addedAt is
    # the same as our cached updated_at, nothing has changed since the
    # last sync. Skip the items write but still refresh the timestamp so
    # we can observe "user opened the app today" downstream.
    settings = get_likes_settings(caller_email)
    cached_count = settings.get("likes_count", 0)
    cached_updated_at = settings.get("likes_updated_at")

    first_added_at = tracks[0].get("addedAt") if tracks else None
    throttled = bool(
        tracks
        and total == cached_count
        and cached_updated_at is not None
        and first_added_at == cached_updated_at
    )

    written = 0
    if throttled:
        log.info(
            f"likes_push throttled for {caller_email} "
            f"(count={cached_count}, addedAt={cached_updated_at})"
        )
        new_updated_at = set_user_likes_count(
            caller_email, total, updated_at=cached_updated_at
        )
    else:
        if tracks:
            written = upsert_user_likes(caller_email, tracks)
        new_updated_at = set_user_likes_count(
            caller_email, total, updated_at=first_added_at
        )

    return success_response(
        {
            "throttled": throttled,
            "written": written,
            "likesCount": total,
            "likesUpdatedAt": new_updated_at,
        }
    )
