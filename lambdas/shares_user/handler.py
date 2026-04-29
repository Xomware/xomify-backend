"""
GET /shares/user - List shares authored by a specific user (no friendship gate in v1).

Profile view only surfaces PUBLIC shares — group-only shares stay scoped to
their group feeds and are not leaked via the author's profile. Legacy rows
(no `public` field) are treated as public so older data keeps flowing.

Caller (requester) email is sourced from `requestContext.authorizer.email`
via `get_caller_email`; legacy callers may still pass `email` in the
query string during the Track 0 -> Track 1 migration window.

`targetEmail` is the AUTHOR being viewed and stays as a query param —
it is NOT the caller.
"""

from lambdas.common.logger import get_logger
from lambdas.common.errors import handle_errors, ValidationError
from lambdas.common.utility_helpers import (
    success_response,
    get_query_params,
    require_fields,
    get_caller_email,
)
from lambdas.common.shares_dynamo import list_shares_for_user
from lambdas.common.interactions_dynamo import build_enrichment

log = get_logger(__file__)

HANDLER = 'shares_user'

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


@handle_errors(HANDLER)
def handler(event, context):
    params = get_query_params(event)
    # targetEmail is the author whose profile is being viewed (NOT the caller).
    require_fields(params, 'targetEmail')

    email = get_caller_email(event)
    target_email = params.get('targetEmail')
    limit = _parse_limit(params.get('limit'))
    before = params.get('before')

    log.info(
        f"Requester {email} listing shares for target {target_email} "
        f"(limit={limit}, before={before})"
    )

    shares, next_before = list_shares_for_user(target_email, limit=limit, before=before)

    # Hide group-only rows from the public profile view. Missing `public`
    # is treated as True so legacy rows keep showing up.
    shares = [s for s in shares if s.get('public', True)]

    enriched = []
    for share in shares:
        share_id = share.get('shareId')
        if share_id:
            try:
                share.update(build_enrichment(
                    share_id,
                    email,
                    track_id=share.get('trackId'),
                    sharer_email=share.get('email') or share.get('sharedBy'),
                ))
            except Exception as err:
                log.warning(f"Profile enrichment failed for share {share_id}: {err}")
                share.setdefault('queuedCount', 0)
                share.setdefault('ratedCount', 0)
                share.setdefault('viewerHasQueued', False)
                share.setdefault('viewerRating', None)
                share.setdefault('sharerRating', None)
                share.setdefault('viewerHasListened', False)
                share.setdefault('listenerCount', 0)
        enriched.append(share)

    log.info(f"Returning {len(enriched)} shares for target {target_email}")
    return success_response({'shares': enriched, 'nextBefore': next_before})
