"""
GET /shares/feed - Merged feed of shares from the requester + accepted friends
                   (optionally filtered to a specific group).
"""

from lambdas.common.logger import get_logger
from lambdas.common.errors import handle_errors, ValidationError
from lambdas.common.utility_helpers import success_response, get_query_params, require_fields
from lambdas.common.friendships_dynamo import list_all_friends_for_user
from lambdas.common.group_members_dynamo import list_members_of_group
from lambdas.common.shares_dynamo import query_feed_for_emails
from lambdas.common.interactions_dynamo import build_enrichment

log = get_logger(__file__)

HANDLER = 'shares_feed'

DEFAULT_LIMIT = 50
MAX_LIMIT = 100


def _parse_limit(raw: str | None) -> int:
    if raw is None:
        return DEFAULT_LIMIT
    try:
        limit = int(raw)
    except (TypeError, ValueError):
        raise ValidationError(
            message="limit must be an integer",
            handler=HANDLER,
            function='handler',
            field='limit',
        )
    if limit <= 0:
        raise ValidationError(
            message="limit must be > 0",
            handler=HANDLER,
            function='handler',
            field='limit',
        )
    if limit > MAX_LIMIT:
        raise ValidationError(
            message=f"limit cannot exceed {MAX_LIMIT}",
            handler=HANDLER,
            function='handler',
            field='limit',
        )
    return limit


def _enrich(share: dict, viewer_email: str) -> dict:
    """Populate queuedCount / ratedCount / viewerHasQueued / viewerRating / sharerRating
    from the share-interactions table for a single share. One Query per share — fine at
    v1 feed sizes (limit <= 100)."""
    share_id = share.get('shareId')
    if not share_id:
        share.setdefault('queuedCount', 0)
        share.setdefault('ratedCount', 0)
        share.setdefault('viewerHasQueued', False)
        share.setdefault('viewerRating', None)
        share.setdefault('sharerRating', None)
        return share
    try:
        enrichment = build_enrichment(share_id, viewer_email)
        share.update(enrichment)
    except Exception as err:
        # Never let an enrichment miss break the feed.
        log.warning(f"Feed enrichment failed for share {share_id}: {err}")
        share.setdefault('queuedCount', 0)
        share.setdefault('ratedCount', 0)
        share.setdefault('viewerHasQueued', False)
        share.setdefault('viewerRating', None)
        share.setdefault('sharerRating', None)
    return share


@handle_errors(HANDLER)
def handler(event, context):
    params = get_query_params(event)
    require_fields(params, 'email')

    email = params.get('email')
    group_id = params.get('groupId')
    limit = _parse_limit(params.get('limit'))
    before = params.get('before')

    log.info(f"Building feed for {email} (groupId={group_id}, limit={limit}, before={before})")

    # Friends list — filter to accepted only, include requester themselves
    friends = list_all_friends_for_user(email)
    feed_emails: set[str] = {
        f.get('friendEmail')
        for f in friends
        if f.get('status') == 'accepted' and f.get('friendEmail')
    }
    feed_emails.add(email)

    # Optional group filter — intersect with members of the group
    if group_id:
        members = list_members_of_group(group_id)
        member_emails = {m.get('email') for m in members if m.get('email')}
        feed_emails = feed_emails & member_emails
        log.info(f"After group filter: {len(feed_emails)} authors in set")

    if not feed_emails:
        return success_response({'shares': [], 'nextBefore': None})

    shares = query_feed_for_emails(sorted(feed_emails), limit=limit, before=before)
    shares = [_enrich(s, email) for s in shares]

    # Cursor for next page: createdAt of the oldest returned share if we hit the limit
    next_before = shares[-1].get('createdAt') if len(shares) == limit and shares else None

    log.info(f"Returning {len(shares)} shares for {email}'s feed (nextBefore={next_before})")
    return success_response({'shares': shares, 'nextBefore': next_before})
