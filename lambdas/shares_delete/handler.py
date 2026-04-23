"""
DELETE /shares/delete - Delete a share by id (owner only).
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
    require_fields,
)
from lambdas.common.shares_dynamo import get_share, delete_share

log = get_logger(__file__)

HANDLER = 'shares_delete'


@handle_errors(HANDLER)
def handler(event, context):
    params = get_query_params(event)
    require_fields(params, 'email', 'shareId')

    email = params.get('email')
    share_id = params.get('shareId')

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
