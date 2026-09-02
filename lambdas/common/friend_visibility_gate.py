"""
The gate every friend-scoped read goes through.

Two checks, in this order, both of which must pass:

  1. An ACCEPTED friendship between caller and subject.
  2. The subject's visibility flag for that artefact.

Order matters. Checking friendship first means a stranger cannot learn whether
someone has Wrapped enabled by watching which error they get -- both failures
return the same 403.

Fails CLOSED. A missing user record, an unreadable flag, or any lookup error
denies the read rather than defaulting to visible. The default-on decision in
`user_visibility` applies to users we can actually read; it is not a licence to
serve data when the check itself failed.
"""

from lambdas.common.dynamo_helpers import get_user_table_data
from lambdas.common.errors import AuthorizationError, ValidationError
from lambdas.common.friendships_dynamo import are_users_friends
from lambdas.common.logger import get_logger
from lambdas.common.user_visibility import is_visible_to_friends

log = get_logger(__file__)


def assert_can_read(caller_email: str, subject_email: str, artefact: str, handler: str) -> dict:
    """
    Authorize `caller_email` to read `subject_email`'s `artefact`.

    Returns the subject's user record, since every caller needs it next and a
    second read would be wasted.

    Reading your OWN data through a friend endpoint is allowed and skips both
    checks -- a client that lands on its own row should not 403.
    """
    if not subject_email:
        raise ValidationError(
            message="email is required",
            handler=handler,
            function="assert_can_read",
        )

    subject = get_user_table_data(subject_email)

    if caller_email == subject_email:
        return subject or {}

    denied = AuthorizationError(
        message="Not available",
        handler=handler,
        function="assert_can_read",
    )

    if not subject:
        log.warning(f"{handler}: no user record for {subject_email}")
        raise denied

    if not are_users_friends(caller_email, subject_email):
        log.warning(f"{handler}: {caller_email} is not an accepted friend of {subject_email}")
        raise denied

    if not is_visible_to_friends(subject, artefact):
        log.info(f"{handler}: {subject_email} has {artefact} set to private")
        raise denied

    return subject
