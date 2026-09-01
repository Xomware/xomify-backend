"""
Per-user visibility for the artefacts friends can see.

Wrapped, Release Radar and top items had no visibility control before this --
nothing had ever shown them to another person. The friend views on those
screens are what makes the question real.

Default is `friends`, INCLUDING for users who predate this module (a missing
attribute reads as `friends`, not `private`). That was a deliberate call: the
feature works the day it ships rather than waiting for opt-in, on the reasoning
that a handful of users who all know each other is a different setting from a
public app. The cost is that the first anyone hears of it may be seeing their
stats already visible, which is why the toggle ships with it.

See docs/features/friend-feed/PLAN.md.
"""

import boto3

from lambdas.common.constants import AWS_DEFAULT_REGION, USERS_TABLE_NAME
from lambdas.common.errors import DynamoDBError, ValidationError
from lambdas.common.logger import get_logger

dynamodb = boto3.resource("dynamodb", region_name=AWS_DEFAULT_REGION)

log = get_logger(__file__)

FRIENDS = "friends"
PRIVATE = "private"
VALID = {FRIENDS, PRIVATE}

# Request key -> stored attribute. The stored names are snake_case to match
# `likes_public`, the only visibility flag that predates this.
FIELDS = {
    "wrapped": "wrapped_visibility",
    "releaseRadar": "release_radar_visibility",
    "topItems": "top_items_visibility",
}


def read_visibility(user: dict | None) -> dict:
    """
    Visibility map for a user record, defaulting anything unset to `friends`.

    Takes the already-fetched record rather than the email, so a caller that
    has the user in hand does not pay for a second read.
    """
    user = user or {}
    return {
        key: user.get(attr) if user.get(attr) in VALID else FRIENDS
        for key, attr in FIELDS.items()
    }


def is_visible_to_friends(user: dict | None, key: str) -> bool:
    """Whether one artefact is friend-visible. Unknown key -> not visible."""
    if key not in FIELDS:
        return False
    return read_visibility(user)[key] == FRIENDS


def set_visibility(email: str, updates: dict) -> dict:
    """
    Apply a PARTIAL visibility update and return the full resulting map.

    Partial on purpose: sending only `wrapped` must not reset the other two.
    Getting this wrong is how the enrollment flags used to clobber each other.
    """
    if not email:
        raise DynamoDBError(
            message="email is required",
            function="set_visibility",
            table=USERS_TABLE_NAME,
        )

    unknown = set(updates) - set(FIELDS)
    if unknown:
        raise ValidationError(
            message=f"Unknown visibility field(s): {sorted(unknown)}. "
                    f"Valid: {sorted(FIELDS)}",
            function="set_visibility",
        )

    bad = {k: v for k, v in updates.items() if v not in VALID}
    if bad:
        raise ValidationError(
            message=f"Visibility must be one of {sorted(VALID)}; got {bad}",
            function="set_visibility",
        )

    if not updates:
        raise ValidationError(
            message=f"No visibility fields given. Valid: {sorted(FIELDS)}",
            function="set_visibility",
        )

    names = {f"#f{i}": FIELDS[key] for i, key in enumerate(updates)}
    values = {f":v{i}": updates[key] for i, key in enumerate(updates)}
    expression = "SET " + ", ".join(
        f"#f{i} = :v{i}" for i in range(len(updates))
    )

    try:
        table = dynamodb.Table(USERS_TABLE_NAME)
        result = table.update_item(
            Key={"email": email},
            UpdateExpression=expression,
            ExpressionAttributeNames=names,
            ExpressionAttributeValues=values,
            ReturnValues="ALL_NEW",
        )
    except Exception as err:
        log.error(f"set_visibility failed for {email}: {err}")
        raise DynamoDBError(
            message=str(err),
            function="set_visibility",
            table=USERS_TABLE_NAME,
        )

    log.info(f"Set visibility {updates} for {email}")
    return read_visibility(result.get("Attributes"))
