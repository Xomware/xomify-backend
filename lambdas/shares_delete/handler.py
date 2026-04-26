"""
/shares/delete - Delete a share by id (owner only).

iOS posts a JSON body `{shareId, sharedAt}` even though the API Gateway
route is wired as DELETE; we accept `shareId` from either the body or
the query string so the lambda is robust to whichever shape API Gateway
forwards. `sharedAt` is accepted for forward compat but unused — the
shares table is keyed on shareId alone.

Caller identity is sourced from `requestContext.authorizer.email` via
`get_caller_email`; legacy callers may still send `email` in the body
or query during the Track 0 -> Track 1 migration window.
"""

from lambdas.common.logger import get_logger
from lambdas.common.errors import (
    handle_errors,
    NotFoundError,
    AuthorizationError,
)
from lambdas.common.utility_helpers import (
    success_response,
    get_query_params,
    parse_body,
    require_fields,
    get_caller_email,
)
from lambdas.common.shares_dynamo import get_share, delete_share

log = get_logger(__file__)

HANDLER = 'shares_delete'


def _extract_share_id(event: dict) -> dict:
    """Pull shareId from body, falling back to queryStringParameters.

    The previous version read from query params only. iOS sends shareId
    in the JSON body — so the lambda silently 400'd or ran with empty
    params, which is what was reported as "delete returns OK but doesn't
    delete".
    """
    body = parse_body(event) or {}
    params = get_query_params(event) or {}

    return {
        'shareId': body.get('shareId') or params.get('shareId'),
    }


@handle_errors(HANDLER)
def handler(event, context):
    identifiers = _extract_share_id(event)
    require_fields(identifiers, 'shareId')

    email = get_caller_email(event)
    share_id = identifiers['shareId']

    log.info(f"User {email} requesting delete of share {share_id}")

    share = get_share(share_id)
    if not share:
        raise NotFoundError(
            message=f"Share {share_id} not found",
            handler=HANDLER,
            function='handler',
            resource='share',
        )

    owner = share.get('email')
    if owner != email:
        log.warning(
            f"Delete share {share_id} blocked: requester {email} is not owner ({owner})"
        )
        raise AuthorizationError(
            message="You can only delete your own shares",
            handler=HANDLER,
            function='handler',
        )

    delete_share(share_id)
    log.info(f"Share {share_id} deleted by owner {email}")
    return success_response({}, status_code=204)
