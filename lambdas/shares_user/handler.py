"""
GET /shares/user - List shares authored by a specific user (no friendship gate in v1).
"""

from lambdas.common.logger import get_logger
from lambdas.common.errors import handle_errors, ValidationError
from lambdas.common.utility_helpers import (
    success_response,
    get_query_params,
    require_fields,
)
from lambdas.common.shares_dynamo import list_shares_for_user

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
    # email is the requester (kept for future friendship gating); targetEmail is the author
    require_fields(params, 'email', 'targetEmail')

    email = params.get('email')
    target_email = params.get('targetEmail')
    limit = _parse_limit(params.get('limit'))
    before = params.get('before')

    log.info(
        f"Requester {email} listing shares for target {target_email} "
        f"(limit={limit}, before={before})"
    )

    shares, next_before = list_shares_for_user(target_email, limit=limit, before=before)

    log.info(f"Returning {len(shares)} shares for target {target_email}")
    return success_response({'shares': shares, 'nextBefore': next_before})
