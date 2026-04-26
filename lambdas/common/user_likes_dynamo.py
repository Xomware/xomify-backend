"""
XOMIFY User Likes DynamoDB Helpers
==================================
Database operations for the xomify-user-likes table + the likes-related
attributes mirrored on the existing users table.

Two storage surfaces are managed here:

1. **users table** (existing, PK=email) — adds three likes-related attrs:
   - ``likes_count`` (Number) — cached total of saved tracks for the user.
   - ``likes_updated_at`` (String, ISO8601) — when the cache was last refreshed.
   - ``likes_public`` (Bool, default True) — opt-out toggle for friend visibility.

2. **user_likes table** (new) — one item per (user, track) pair so the
   friend-scoped Likes page can paginate without dragging the entire
   blob over the wire.

   - PK: ``email`` (String)
   - SK: ``addedAt#trackId`` (String) — composite so items sort newest-first
         when queried with ``ScanIndexForward=False`` and we still get a
         deterministic tie-break for items added in the same second.
   - GSI: ``email-addedAt-index`` (PK=email, SK=addedAt) for direct
          time-ordered pagination without parsing the composite SK.

Helpers exposed:

- :func:`set_user_likes_count` — write back ``likes_count`` + ``likes_updated_at``
  on the user record.
- :func:`upsert_user_likes` — batch-write a page of items into the
  ``user_likes`` table.
- :func:`query_user_likes` — paginated read of a user's saved tracks,
  newest first.
- :func:`get_likes_settings` — read ``(likes_count, likes_updated_at,
  likes_public)`` for a single user. Defaults are returned when the
  attributes are missing so legacy rows never 500 callers.
- :func:`set_likes_public` — flip the ``likes_public`` toggle.

The helpers degrade gracefully when ``USER_LIKES_TABLE_NAME`` is not yet
provisioned (returns no-op / empty results) so the rest of the codebase
can ship before the infra repo wires the table up.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Optional

import boto3
from boto3.dynamodb.conditions import Key
from botocore.exceptions import ClientError

from lambdas.common.constants import (
    AWS_DEFAULT_REGION,
    USERS_TABLE_NAME,
    USER_LIKES_TABLE_NAME,
)
from lambdas.common.errors import DynamoDBError
from lambdas.common.logger import get_logger

log = get_logger(__file__)

dynamodb = boto3.resource("dynamodb", region_name=AWS_DEFAULT_REGION)

# Defense-in-depth caps. The push handler also enforces these but we keep
# them here so any direct caller (cron, backfill) gets the same protection.
MAX_LIKES_PAGE = 200
DEFAULT_LIKES_PUBLIC = True


def _iso_now() -> str:
    """Return the current UTC timestamp in ISO8601 format."""
    return datetime.now(timezone.utc).isoformat()


def _build_sort_key(added_at: str, track_id: str) -> str:
    """Build the composite sort key used in the user_likes base table.

    Format: ``<addedAt>#<trackId>``. Sorting on this key descending gives
    us newest-first ordering with a deterministic tie-break.
    """
    safe_added = (added_at or "").replace("#", "_")
    safe_track = (track_id or "").replace("#", "_")
    return f"{safe_added}#{safe_track}"


def _coerce_bool(value: Any, default: bool) -> bool:
    """Coerce DDB-stored bools (which may come back as strings on legacy rows)."""
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        if value.strip().lower() == "true":
            return True
        if value.strip().lower() == "false":
            return False
    if value is None:
        return default
    return bool(value)


# ============================================
# users table — likes counters / settings
# ============================================
def set_user_likes_count(email: str, count: int, updated_at: Optional[str] = None) -> str:
    """Update ``likes_count`` + ``likes_updated_at`` on the user record.

    Returns the ``updated_at`` value that was persisted so callers can
    echo it back without computing it twice.
    """
    if not email:
        raise DynamoDBError(
            message="email is required",
            function="set_user_likes_count",
            table=USERS_TABLE_NAME,
        )

    ts = updated_at or _iso_now()
    try:
        table = dynamodb.Table(USERS_TABLE_NAME)
        table.update_item(
            Key={"email": email},
            UpdateExpression="SET likes_count = :c, likes_updated_at = :ts",
            ExpressionAttributeValues={":c": int(count), ":ts": ts},
        )
        log.info(f"Set likes_count={count} for {email} at {ts}")
        return ts
    except Exception as err:
        log.error(f"set_user_likes_count failed for {email}: {err}")
        raise DynamoDBError(
            message=str(err),
            function="set_user_likes_count",
            table=USERS_TABLE_NAME,
        )


def get_likes_settings(email: str) -> dict[str, Any]:
    """Return the likes-related fields for a user.

    Output shape: ``{"likes_count": int, "likes_updated_at": str|None,
    "likes_public": bool}``. Missing attrs default to safe values so this
    helper never throws on legacy rows or first-time users.
    """
    if not email:
        raise DynamoDBError(
            message="email is required",
            function="get_likes_settings",
            table=USERS_TABLE_NAME,
        )

    try:
        table = dynamodb.Table(USERS_TABLE_NAME)
        response = table.get_item(Key={"email": email})
        item = response.get("Item") or {}

        raw_count = item.get("likes_count", 0)
        try:
            count = int(raw_count) if raw_count is not None else 0
        except (TypeError, ValueError):
            count = 0

        return {
            "likes_count": count,
            "likes_updated_at": item.get("likes_updated_at"),
            "likes_public": _coerce_bool(item.get("likes_public"), DEFAULT_LIKES_PUBLIC),
        }
    except DynamoDBError:
        raise
    except Exception as err:
        log.error(f"get_likes_settings failed for {email}: {err}")
        raise DynamoDBError(
            message=str(err),
            function="get_likes_settings",
            table=USERS_TABLE_NAME,
        )


def set_likes_public(email: str, value: bool) -> bool:
    """Flip the ``likes_public`` toggle for a user. Returns the persisted value."""
    if not email:
        raise DynamoDBError(
            message="email is required",
            function="set_likes_public",
            table=USERS_TABLE_NAME,
        )

    coerced = bool(value)
    try:
        table = dynamodb.Table(USERS_TABLE_NAME)
        table.update_item(
            Key={"email": email},
            UpdateExpression="SET likes_public = :v",
            ExpressionAttributeValues={":v": coerced},
        )
        log.info(f"Set likes_public={coerced} for {email}")
        return coerced
    except Exception as err:
        log.error(f"set_likes_public failed for {email}: {err}")
        raise DynamoDBError(
            message=str(err),
            function="set_likes_public",
            table=USERS_TABLE_NAME,
        )


# ============================================
# user_likes table — items
# ============================================
def upsert_user_likes(email: str, tracks: list[dict[str, Any]]) -> int:
    """Batch-write a list of saved-track items into the user_likes table.

    Each track dict is expected to provide ``trackId`` and ``addedAt`` at
    minimum; ``trackName``, ``artistName`` and ``albumArt`` are optional
    denormalized metadata.

    Returns the number of items actually written. The cap (``MAX_LIKES_PAGE``)
    is enforced server-side as defense in depth — callers should already be
    capping but we never want a runaway payload to nuke our write budget.

    Silently no-ops when ``USER_LIKES_TABLE_NAME`` is not configured so the
    rest of the system can ship before infra provisions the table.
    """
    if not email:
        raise DynamoDBError(
            message="email is required",
            function="upsert_user_likes",
            table=USER_LIKES_TABLE_NAME or "user_likes",
        )

    if not USER_LIKES_TABLE_NAME:
        log.warning(
            "upsert_user_likes called but USER_LIKES_TABLE_NAME env var is unset; "
            "skipping write"
        )
        return 0

    if not tracks:
        return 0

    capped = tracks[:MAX_LIKES_PAGE]
    written = 0

    try:
        table = dynamodb.Table(USER_LIKES_TABLE_NAME)
        with table.batch_writer() as batch:
            for track in capped:
                track_id = track.get("trackId")
                added_at = track.get("addedAt")
                if not track_id or not added_at:
                    log.warning(
                        f"Skipping like row missing trackId/addedAt for {email}: {track}"
                    )
                    continue

                item: dict[str, Any] = {
                    "email": email,
                    "addedAtTrackId": _build_sort_key(added_at, track_id),
                    "trackId": track_id,
                    "addedAt": added_at,
                }

                # Optional denormalized metadata — only persist when present
                # so we don't store empty strings for missing fields.
                for src_key, dst_key in (
                    ("trackName", "trackName"),
                    ("artistName", "artistName"),
                    ("albumArt", "albumArt"),
                    ("name", "trackName"),
                    ("artist", "artistName"),
                ):
                    value = track.get(src_key)
                    if value:
                        item[dst_key] = value

                batch.put_item(Item=item)
                written += 1

        log.info(f"Upserted {written} likes for {email}")
        return written

    except ClientError as err:
        log.error(f"upsert_user_likes ClientError for {email}: {err}")
        raise DynamoDBError(
            message=str(err),
            function="upsert_user_likes",
            table=USER_LIKES_TABLE_NAME,
        )
    except Exception as err:
        log.error(f"upsert_user_likes failed for {email}: {err}")
        raise DynamoDBError(
            message=str(err),
            function="upsert_user_likes",
            table=USER_LIKES_TABLE_NAME,
        )


def query_user_likes(
    email: str,
    limit: int = 50,
    offset: int = 0,
) -> dict[str, Any]:
    """Return a paginated slice of a user's saved tracks, newest first.

    Output shape: ``{"tracks": [...], "total": int, "hasMore": bool}``.

    ``offset`` is implemented client-side (Query + slice) so the API stays
    a simple ``limit/offset`` shape consistent with the iOS infinite-scroll
    pattern. For users with up to ``MAX_LIKES_PAGE`` saved tracks this is
    free; the cap is enforced upstream so we never page through more.

    Returns an empty result when ``USER_LIKES_TABLE_NAME`` is not configured.
    """
    if not email:
        raise DynamoDBError(
            message="email is required",
            function="query_user_likes",
            table=USER_LIKES_TABLE_NAME or "user_likes",
        )

    if not USER_LIKES_TABLE_NAME:
        log.warning(
            "query_user_likes called but USER_LIKES_TABLE_NAME env var is unset; "
            "returning empty page"
        )
        return {"tracks": [], "total": 0, "hasMore": False}

    safe_limit = max(1, min(int(limit), MAX_LIKES_PAGE))
    safe_offset = max(0, int(offset))

    try:
        table = dynamodb.Table(USER_LIKES_TABLE_NAME)
        items: list[dict[str, Any]] = []
        kwargs: dict[str, Any] = {
            "KeyConditionExpression": Key("email").eq(email),
            "ScanIndexForward": False,
        }

        # Drain up to MAX_LIKES_PAGE items so total + hasMore are accurate.
        while True:
            response = table.query(**kwargs)
            items.extend(response.get("Items", []))
            last_key = response.get("LastEvaluatedKey")
            if not last_key or len(items) >= MAX_LIKES_PAGE:
                break
            kwargs["ExclusiveStartKey"] = last_key

        items = items[:MAX_LIKES_PAGE]
        total = len(items)
        page = items[safe_offset : safe_offset + safe_limit]
        has_more = (safe_offset + safe_limit) < total

        # Strip the internal composite sort key before returning to callers.
        cleaned: list[dict[str, Any]] = []
        for item in page:
            row = {k: v for k, v in item.items() if k != "addedAtTrackId"}
            cleaned.append(row)

        return {
            "tracks": cleaned,
            "total": total,
            "hasMore": has_more,
        }

    except DynamoDBError:
        raise
    except Exception as err:
        log.error(f"query_user_likes failed for {email}: {err}")
        raise DynamoDBError(
            message=str(err),
            function="query_user_likes",
            table=USER_LIKES_TABLE_NAME,
        )
