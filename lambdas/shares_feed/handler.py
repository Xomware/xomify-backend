"""
GET /shares/feed - Get merged feed of shares from user + accepted friends
"""

from lambdas.common.logger import get_logger
from lambdas.common.errors import handle_errors
from lambdas.common.utility_helpers import success_response, get_query_params, require_fields
from lambdas.common.friendships_dynamo import list_all_friends_for_user
from lambdas.common.shares_dynamo import list_shares_for_user
from lambdas.common.interactions_dynamo import count_interactions_for_share

log = get_logger(__file__)

HANDLER = 'shares_feed'

PER_USER_LIMIT = 20
FEED_CAP = 50


@handle_errors(HANDLER)
def handler(event, context):
    params = get_query_params(event)
    require_fields(params, 'email')

    email = params.get('email')

    log.info(f"Building feed for user {email}")

    # Friends list — only accepted
    friends = list_all_friends_for_user(email)
    accepted_emails = [
        f.get('friendEmail')
        for f in friends
        if f.get('status') == 'accepted' and f.get('friendEmail')
    ]

    # Include the user themselves
    feed_emails = set(accepted_emails)
    feed_emails.add(email)

    log.info(f"Fetching shares for {len(feed_emails)} users (self + {len(accepted_emails)} accepted friends)")

    # Collect shares from each user
    all_shares = []
    for user_email in feed_emails:
        try:
            user_shares = list_shares_for_user(user_email, limit=PER_USER_LIMIT)
            all_shares.extend(user_shares)
        except Exception as err:
            log.warning(f"Failed to fetch shares for {user_email}: {err}")
            continue

    # Sort newest first by createdAt
    all_shares.sort(key=lambda s: s.get('createdAt', ''), reverse=True)

    # Cap
    all_shares = all_shares[:FEED_CAP]

    # Attach interaction counts per share
    for share in all_shares:
        share_id = share.get('shareId')
        if share_id:
            try:
                share['interactionCounts'] = count_interactions_for_share(share_id)
            except Exception as err:
                log.warning(f"Failed to count interactions for share {share_id}: {err}")
                share['interactionCounts'] = {}

    log.info(f"Returning {len(all_shares)} shares for {email}'s feed")

    return success_response({
        'email': email,
        'shares': all_shares,
        'totalCount': len(all_shares)
    })
