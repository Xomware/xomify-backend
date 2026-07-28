"""
Admin gate.

Admin routes are authenticated by the custom authorizer like any other route,
then additionally gated in-code against a single configured admin email
(`ADMIN_EMAIL`). Non-admins receive HTTP 403; unauthenticated callers receive
HTTP 401 (raised by `get_caller_email`).
"""

from lambdas.common import constants
from lambdas.common.errors import ForbiddenError
from lambdas.common.logger import get_logger
from lambdas.common.utility_helpers import get_caller_email

log = get_logger(__file__)


def is_admin(email: str) -> bool:
    """Case-insensitive comparison of `email` against the configured admin."""
    if not email or not constants.ADMIN_EMAIL:
        return False
    return email.strip().lower() == constants.ADMIN_EMAIL.strip().lower()


def require_admin(event: dict) -> str:
    """
    Resolve the caller email (raises 401 if absent) and enforce that it matches
    the configured admin. Returns the admin email on success; raises
    `ForbiddenError` (403) otherwise.
    """
    email = get_caller_email(event)
    if not is_admin(email):
        log.warning(f"admin gate denied email={email}")
        raise ForbiddenError(
            message="Admin privileges required",
            handler="admin",
            function="require_admin",
        )
    return email
