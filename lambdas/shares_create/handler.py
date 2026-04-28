"""
POST /shares/create - Create a new share (track share with denormalized metadata).

Multi-target semantics (v2):
- Callers may set `groupIds` (list of group ids) and/or `public` (bool) to
  target the public friends feed, one-or-more groups, or both.
- Defaults: `groupIds=[]`, `public=True` -> legacy public share on the
  friends feed only.
- `public=False` with an empty `groupIds` is invalid (no target) -> 400.
- Every entry in `groupIds` must reference a group the caller is a member
  of; non-members get a 403.

Rate-on-share (v3):
- Callers may include an optional `rating` field (int, 1-5) in the request
  body. When present and in range, the rating is written to the track
  ratings table after the share row is created. The rating write is
  best-effort: failures are logged at WARN and do NOT fail the share.
  Values outside 1-5 are silently ignored (no error).
"""

from lambdas.common.logger import get_logger
from lambdas.common.errors import handle_errors, ValidationError, AuthorizationError
from lambdas.common.utility_helpers import (
    success_response,
    parse_body,
    require_fields,
    get_caller_email,
)
from lambdas.common.shares_dynamo import create_share
from lambdas.common.group_members_dynamo import is_member_of_group
from lambdas.common.track_ratings_dynamo import upsert_track_rating

log = get_logger(__file__)

HANDLER = 'shares_create'

ALLOWED_MOODS = {"hype", "chill", "sad", "party", "focus", "discovery"}
CAPTION_MAX_LEN = 140
GENRE_TAGS_MAX = 3


def _coerce_public(raw) -> bool:
    """Accept bool or the common stringy forms ('true'/'false') iOS may send."""
    if isinstance(raw, bool):
        return raw
    if isinstance(raw, str):
        return raw.strip().lower() != 'false'
    # Anything truthy-but-unexpected -> treat as True (default-open, matches spec).
    return bool(raw)


def _validate_group_ids(raw, email: str) -> list[str]:
    """Normalize + validate `groupIds`. Returns the deduped list of ids.

    Raises ValidationError for malformed inputs; AuthorizationError when the
    caller is not a member of every requested group (403 per spec)."""
    if raw is None:
        return []
    if not isinstance(raw, list):
        raise ValidationError(
            message="groupIds must be a list of group ids",
            handler=HANDLER,
            function='handler',
            field='groupIds',
        )

    # Preserve order but drop duplicates / blanks.
    seen: set[str] = set()
    cleaned: list[str] = []
    for gid in raw:
        if not isinstance(gid, str) or not gid.strip():
            raise ValidationError(
                message="groupIds entries must be non-empty strings",
                handler=HANDLER,
                function='handler',
                field='groupIds',
            )
        gid = gid.strip()
        if gid in seen:
            continue
        seen.add(gid)
        cleaned.append(gid)

    # Membership gate — caller must belong to every group they're targeting.
    for gid in cleaned:
        if not is_member_of_group(email, gid):
            log.warning(
                f"shares_create membership check failed: {email} is not a member of {gid}"
            )
            raise AuthorizationError(
                message=f"Not a member of group {gid}",
                handler=HANDLER,
                function='handler',
            )

    return cleaned


@handle_errors(HANDLER)
def handler(event, context):
    body = parse_body(event)
    require_fields(
        body,
        'trackId',
        'trackUri',
        'trackName',
        'artistName',
        'albumName',
        'albumArtUrl',
    )

    email = get_caller_email(event)
    track_id = body.get('trackId')
    track_uri = body.get('trackUri')
    track_name = body.get('trackName')
    artist_name = body.get('artistName')
    album_name = body.get('albumName')
    album_art_url = body.get('albumArtUrl')
    caption = body.get('caption')
    mood_tag = body.get('moodTag')
    genre_tags = body.get('genreTags')
    raw_rating = body.get('rating')

    # Multi-target fields — default to legacy "public only" share.
    public = _coerce_public(body.get('public', True))
    group_ids = _validate_group_ids(body.get('groupIds'), email=email)

    if not public and not group_ids:
        raise ValidationError(
            message="Specify at least one target.",
            handler=HANDLER,
            function='handler',
            field='groupIds',
        )

    # Caption length
    if caption is not None and len(caption) > CAPTION_MAX_LEN:
        raise ValidationError(
            message=f"caption exceeds {CAPTION_MAX_LEN} characters",
            handler=HANDLER,
            function='handler',
            field='caption',
        )

    # Mood tag enum
    if mood_tag is not None and mood_tag not in ALLOWED_MOODS:
        raise ValidationError(
            message=f"Invalid moodTag '{mood_tag}'. Must be one of: {sorted(ALLOWED_MOODS)}",
            handler=HANDLER,
            function='handler',
            field='moodTag',
        )

    # Genre tags cap
    if genre_tags is not None:
        if not isinstance(genre_tags, list):
            raise ValidationError(
                message="genreTags must be a list",
                handler=HANDLER,
                function='handler',
                field='genreTags',
            )
        if len(genre_tags) > GENRE_TAGS_MAX:
            raise ValidationError(
                message=f"genreTags exceeds {GENRE_TAGS_MAX} entries",
                handler=HANDLER,
                function='handler',
                field='genreTags',
            )

    log.info(
        f"User {email} creating share for track {track_id} "
        f"(public={public}, groupIds={group_ids})"
    )
    result = create_share(
        email=email,
        track_id=track_id,
        track_uri=track_uri,
        track_name=track_name,
        artist_name=artist_name,
        album_name=album_name,
        album_art_url=album_art_url,
        caption=caption,
        mood_tag=mood_tag,
        genre_tags=genre_tags,
        group_ids=group_ids,
        public=public,
    )

    log.info(f"Share {result['shareId']} created successfully")

    # Best-effort rating write. Only attempted when rating is a valid int 1-5.
    # Values outside that range are silently ignored. Failures are logged at
    # WARN but do NOT fail the share response.
    if isinstance(raw_rating, int) and 1 <= raw_rating <= 5:
        try:
            upsert_track_rating(
                email=email,
                track_id=track_id,
                rating=raw_rating,
                track_name=track_name,
                artist_name=artist_name,
                album_art=album_art_url or "",
                album_name=album_name,
                rating_context="share",
            )
            log.info(
                f"Rate-on-share: wrote rating {raw_rating} for track {track_id} "
                f"(share {result['shareId']})"
            )
        except Exception as exc:
            log.warning(
                f"Rate-on-share: failed to write rating for share {result['shareId']}: {exc}"
            )

    return success_response(result)
