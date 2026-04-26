"""
GET /shares/detail - Full detail view for a single share.

Query params:
    shareId  (required) - the share to load
    sharedAt (optional) - accepted for forward compat; unused, since the
                           shares table is keyed on shareId alone in v1
    sharedBy (optional) - accepted for forward compat; unused, since the
                           share row itself carries the author email

Caller (viewer) email is sourced from `requestContext.authorizer.email`
via `get_caller_email`; legacy callers may still pass `email` in the
query string during the Track 0 -> Track 1 migration window.

Response:
    {
        "share": { ...full share + viewer enrichment (queuedCount, ratedCount,
                   viewerHasQueued, viewerRating, sharerRating)... },
        "interactions": [
            {email, displayName, avatar, action, createdAt}
            ...deduped by (email, action), derived from the share-interactions table
        ],
        "friendRatings": [
            {email, displayName, avatar, rating, review, ratedAt}
            ...the viewer's accepted friends (plus the share's author) who
               have rated this track in the track-ratings table
        ]
    }

Notes:
- `review` is included in the friendRatings contract even though the track
  ratings table doesn't currently persist a review field — it's kept as a
  nullable slot for when the feature lands client-side.
- Interactions with both queued=True and rated=True produce two rows (one
  per action); that matches the iOS client's expected shape.
"""

from __future__ import annotations

from typing import Any, Optional

from lambdas.common.logger import get_logger
from lambdas.common.errors import handle_errors, NotFoundError
from lambdas.common.utility_helpers import (
    success_response,
    get_query_params,
    require_fields,
    get_caller_email,
)
from lambdas.common.shares_dynamo import get_share
from lambdas.common.interactions_dynamo import (
    build_enrichment,
    list_reactions_for_share,
)
from lambdas.common.friendships_dynamo import list_all_friends_for_user
from lambdas.common.track_ratings_dynamo import list_all_track_ratings_for_user
from lambdas.common.dynamo_helpers import batch_get_users
from lambdas.common.group_members_dynamo import is_member_of_group
from lambdas.common.share_comments_dynamo import count_comments
from lambdas.common.share_reactions_dynamo import build_reaction_summary

log = get_logger(__file__)

HANDLER = 'shares_detail'


def _user_profile(users: dict, email: str) -> tuple[Optional[str], Optional[str]]:
    """Return (displayName, avatar) for `email`, falling back to (None, None)."""
    user = users.get(email) or {}
    return user.get('displayName'), user.get('avatar')


def _build_interactions(
    reactions: list[dict[str, Any]],
    users: dict[str, dict[str, Any]],
) -> list[dict[str, Any]]:
    """
    Collapse the share-interactions rows (one row per viewer, with
    queued/rated boolean attributes) into a flat, deduped list of
    (email, action) events. Output is stable-sorted by createdAt desc.
    """
    seen: set[tuple[str, str]] = set()
    out: list[dict[str, Any]] = []

    for item in reactions:
        email = item.get('email')
        if not email:
            continue

        display_name, avatar = _user_profile(users, email)
        ts = item.get('updatedAt') or item.get('createdAt')

        if item.get('queued'):
            key = (email, 'queued')
            if key not in seen:
                seen.add(key)
                out.append({
                    'email': email,
                    'displayName': display_name,
                    'avatar': avatar,
                    'action': 'queued',
                    'createdAt': item.get('queuedAt') or ts,
                })

        if item.get('rated'):
            key = (email, 'rated')
            if key not in seen:
                seen.add(key)
                out.append({
                    'email': email,
                    'displayName': display_name,
                    'avatar': avatar,
                    'action': 'rated',
                    'createdAt': item.get('ratedAt') or ts,
                })

    out.sort(key=lambda r: r.get('createdAt') or '', reverse=True)
    return out


def _accepted_friend_emails(viewer_email: str) -> list[str]:
    """Return the viewer's accepted-friend emails."""
    friends = list_all_friends_for_user(viewer_email)
    return [
        f.get('friendEmail')
        for f in friends
        if f.get('status') == 'accepted' and f.get('friendEmail')
    ]


def _build_friend_ratings(
    viewer_email: str,
    author_email: Optional[str],
    track_id: str,
    users: dict[str, dict[str, Any]],
) -> tuple[list[dict[str, Any]], list[str]]:
    """
    Load the viewer's accepted-friend ratings for this track, plus the
    share's author rating (even if not a friend).

    Returns (ratings, emails_lookup_list) — the second element lets the
    caller ensure every rater's profile was fetched.
    """
    friend_emails = _accepted_friend_emails(viewer_email)
    candidates = list(friend_emails)
    if author_email and author_email not in candidates and author_email != viewer_email:
        candidates.append(author_email)

    ratings: list[dict[str, Any]] = []
    for candidate in candidates:
        try:
            rows = list_all_track_ratings_for_user(candidate)
        except Exception as err:
            log.warning(f"Failed to load ratings for {candidate}: {err}")
            continue
        for row in rows or []:
            if row.get('trackId') != track_id:
                continue
            display_name, avatar = _user_profile(users, candidate)
            ratings.append({
                'email': candidate,
                'displayName': display_name,
                'avatar': avatar,
                'rating': row.get('rating'),
                'review': row.get('review'),  # slot for future content
                'ratedAt': row.get('ratedAt'),
            })

    ratings.sort(key=lambda r: r.get('ratedAt') or '', reverse=True)
    return ratings, candidates


def _enrich_share(share: dict[str, Any], viewer_email: str) -> dict[str, Any]:
    """Mirror shares_feed's _enrich — never let enrichment drop the share."""
    share_id = share.get('shareId')
    if not share_id:
        share.setdefault('queuedCount', 0)
        share.setdefault('ratedCount', 0)
        share.setdefault('viewerHasQueued', False)
        share.setdefault('viewerRating', None)
        share.setdefault('sharerRating', None)
        return share
    try:
        share.update(build_enrichment(share_id, viewer_email))
    except Exception as err:
        log.warning(f"Detail enrichment failed for share {share_id}: {err}")
        share.setdefault('queuedCount', 0)
        share.setdefault('ratedCount', 0)
        share.setdefault('viewerHasQueued', False)
        share.setdefault('viewerRating', None)
        share.setdefault('sharerRating', None)
    return share


@handle_errors(HANDLER)
def handler(event, context):
    params = get_query_params(event)
    require_fields(params, 'shareId')

    viewer_email = get_caller_email(event)
    share_id = params.get('shareId')
    # Accepted for forward compat with iOS payloads; not required because
    # the shares table is keyed on shareId alone and the row carries the
    # author email. Keep them out of validation so the client can evolve
    # without breaking this endpoint.
    _ = params.get('sharedAt')
    _ = params.get('sharedBy')

    log.info(f"Loading share detail {share_id} for viewer {viewer_email}")

    share = get_share(share_id)
    if not share:
        raise NotFoundError(
            message=f"Share {share_id} not found",
            handler=HANDLER,
            function='handler',
            resource='share',
        )

    author_email: Optional[str] = share.get('email')
    track_id: Optional[str] = share.get('trackId')

    # Visibility gate — group-only shares (public == False) must only be
    # reachable by the author or by a member of at least one of the share's
    # target groups. Return 404 for non-members so we don't leak existence.
    is_public = share.get('public', True)
    if not is_public and viewer_email != author_email:
        target_group_ids = share.get('groupIds') or []
        is_allowed = any(
            isinstance(gid, str) and gid and is_member_of_group(viewer_email, gid)
            for gid in target_group_ids
        )
        if not is_allowed:
            log.warning(
                f"Viewer {viewer_email} blocked from group-only share {share_id}"
            )
            raise NotFoundError(
                message=f"Share {share_id} not found",
                handler=HANDLER,
                function='handler',
                resource='share',
            )

    reactions = list_reactions_for_share(share_id)

    # Resolve user profiles (displayName, avatar) for every email we'll
    # surface. Collect the full set up front so we make ONE batch-get call.
    reactor_emails = [r.get('email') for r in reactions if r.get('email')]
    friend_emails = _accepted_friend_emails(viewer_email)

    profile_emails: set[str] = set()
    profile_emails.update(reactor_emails)
    profile_emails.update(friend_emails)
    if author_email:
        profile_emails.add(author_email)
    profile_emails.add(viewer_email)

    try:
        users = batch_get_users(list(profile_emails))
    except Exception as err:
        log.warning(f"Batch user lookup failed, degrading to empty map: {err}")
        users = {}

    interactions_payload = _build_interactions(reactions, users)

    friend_ratings_payload: list[dict[str, Any]] = []
    if track_id:
        friend_ratings_payload, _ = _build_friend_ratings(
            viewer_email=viewer_email,
            author_email=author_email,
            track_id=track_id,
            users=users,
        )
    else:
        log.warning(f"Share {share_id} has no trackId; skipping friendRatings")

    enriched_share = _enrich_share(dict(share), viewer_email)

    # Comments + emoji reactions enrichment — degrade to safe defaults so a
    # storage hiccup never drops the share payload itself.
    try:
        comment_count = count_comments(share_id)
    except Exception as err:
        log.warning(f"comment count failed for share {share_id}: {err}")
        comment_count = 0

    try:
        reaction_summary = build_reaction_summary(share_id, viewer_email)
    except Exception as err:
        log.warning(f"reaction summary failed for share {share_id}: {err}")
        reaction_summary = {"counts": {}, "viewerReactions": []}

    enriched_share['commentCount'] = comment_count
    enriched_share['reactionCounts'] = reaction_summary.get('counts', {})
    enriched_share['viewerReactions'] = reaction_summary.get('viewerReactions', [])

    log.info(
        f"Returning detail for share {share_id}: "
        f"{len(interactions_payload)} interactions, "
        f"{len(friend_ratings_payload)} friendRatings, "
        f"{comment_count} comments, "
        f"{len(reaction_summary.get('counts', {}))} reaction kinds"
    )

    return success_response({
        'share': enriched_share,
        'interactions': interactions_payload,
        'friendRatings': friend_ratings_payload,
    })
