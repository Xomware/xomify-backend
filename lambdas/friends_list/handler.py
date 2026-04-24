"""
GET /friends/list - Get user's friends list with counts
"""

from lambdas.common.logger import get_logger
from lambdas.common.errors import handle_errors
from lambdas.common.utility_helpers import success_response, get_query_params, require_fields
from lambdas.common.friendships_dynamo import list_all_friends_for_user

log = get_logger(__file__)

HANDLER = 'friends_list'


@handle_errors(HANDLER)
def handler(event, context):
    params = get_query_params(event)
    require_fields(params, 'email')

    email = params.get('email')

    log.info(f"Listing all friends for user {email}")
    friends = list_all_friends_for_user(email)

    # Categorize friends
    accepted = []
    blocked = []
    requested = []
    pending = []

    for friend in friends:
        status = friend.get('status')
        if status == 'accepted':
            accepted.append(friend)
        elif status == 'pending':
            # Legacy rows may be missing `direction`; treat unknown as
            # incoming so a single bad row can't 500 the whole response.
            if friend.get('direction') == 'outgoing':
                requested.append(friend)
            else:
                pending.append(friend)
        elif status == 'blocked':
            blocked.append(friend)
        else:
            log.warning(
                f"Skipping friend row with unexpected status={status!r} "
                f"for {email}: {friend.get('friendEmail') or friend.get('email')}"
            )

    log.info(f"Found {len(friends)} friends for user {email}")

    return success_response({
        'email': email,
        'totalCount': len(friends),
        'accepted': accepted,
        'requested': requested,
        'pending': pending,
        'blocked': blocked,
        'acceptedCount': len(accepted),
        'requestedCount': len(requested),
        'pendingCount': len(pending),
        'blockedCount': len(blocked)
    })
