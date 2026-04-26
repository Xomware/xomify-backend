"""
GET /user/all - Get all users

When the caller's identity is known (per-user JWT context, or query/body
fallback during the Track-1 migration window), the caller's own row is
filtered out so discovery UIs never show "add yourself" as an option.

If caller identity is unknown (anonymous discovery — neither context nor
fallback present), the unfiltered list is returned. This preserves the
pre-migration behavior for callers that omit `?email=`.
"""

from lambdas.common.constants import USERS_TABLE_NAME
from lambdas.common.dynamo_helpers import full_table_scan
from lambdas.common.errors import MissingCallerIdentityError, handle_errors
from lambdas.common.logger import get_logger
from lambdas.common.utility_helpers import (
    get_caller_email,
    success_response,
)

log = get_logger(__file__)

HANDLER = 'user_all'


def _resolve_caller_email(event: dict) -> str:
    """
    Resolve the caller email if available. Returns an empty string when no
    identity is present in context or fallback — anonymous callers are
    intentionally tolerated for this endpoint (unfiltered list).
    """
    try:
        return get_caller_email(event).strip().lower()
    except MissingCallerIdentityError:
        return ''


@handle_errors(HANDLER)
def handler(event, context):
    caller_email = _resolve_caller_email(event)

    users = full_table_scan(USERS_TABLE_NAME)

    clean_users = []
    for user in users:
        user.pop('refreshToken', None)
        if caller_email and (user.get('email') or '').strip().lower() == caller_email:
            continue
        clean_users.append(user)

    log.info(
        f"Retrieved {len(clean_users)} users from user table "
        f"(caller={'<anon>' if not caller_email else caller_email})"
    )

    return success_response(clean_users)
