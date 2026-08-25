"""
Tests for per-type notification preferences (B2).

The invariant worth defending hardest: registration must write ONLY the flags
the client actually sent. A blanket write of all sixteen booleans would freeze
today's defaults onto every device row and permanently destroy the
absent-means-default migration path.
"""

from unittest.mock import MagicMock, patch

from lambdas.common.notification_kinds import (
    ALL_KINDS,
    effective_preferences,
    sanitize_preferences,
)


# ── Registry helpers ────────────────────────────────────────────────────

def test_effective_preferences_fills_every_kind_from_an_empty_row():
    prefs = effective_preferences({})
    assert len(prefs) == len(ALL_KINDS)
    assert prefs["shareReceivedEnabled"] is True
    assert prefs["digestEnabled"] is False


def test_effective_preferences_lets_a_stored_flag_win():
    prefs = effective_preferences({"shareReceivedEnabled": False, "digestEnabled": True})
    assert prefs["shareReceivedEnabled"] is False
    assert prefs["digestEnabled"] is True
    # Untouched kinds still resolve to their defaults.
    assert prefs["shareCommentEnabled"] is True


def test_sanitize_drops_unknown_flags():
    """A client typo must not persist forever as a meaningless attribute."""
    out = sanitize_preferences({"digestEnabled": True, "notARealFlag": True})
    assert out == {"digestEnabled": True}


def test_sanitize_coerces_string_booleans():
    out = sanitize_preferences({"digestEnabled": "true", "shareRatedEnabled": "false"})
    assert out == {"digestEnabled": True, "shareRatedEnabled": False}


# ── Sparse upsert ───────────────────────────────────────────────────────

def _captured_update(mock_table):
    return mock_table.update_item.call_args.kwargs


@patch("lambdas.common.device_tokens_dynamo.dynamodb")
def test_upsert_writes_only_the_supplied_flags(mock_dynamo):
    from lambdas.common.device_tokens_dynamo import upsert_token

    table = MagicMock()
    table.update_item.return_value = {"Attributes": {}}
    mock_dynamo.Table.return_value = table

    upsert_token("e@x.com", "tok", preferences={"shareRatedEnabled": False})

    names = _captured_update(table)["ExpressionAttributeNames"]
    written = [v for v in names.values() if v.endswith("Enabled")]
    assert written == ["shareRatedEnabled"]


@patch("lambdas.common.device_tokens_dynamo.dynamodb")
def test_upsert_with_no_preferences_touches_no_flags(mock_dynamo):
    """A plain token refresh must not silently rewrite the user's choices."""
    from lambdas.common.device_tokens_dynamo import upsert_token

    table = MagicMock()
    table.update_item.return_value = {"Attributes": {}}
    mock_dynamo.Table.return_value = table

    upsert_token("e@x.com", "tok")

    names = _captured_update(table)["ExpressionAttributeNames"]
    assert not [v for v in names.values() if v.endswith("Enabled")]


@patch("lambdas.common.device_tokens_dynamo.dynamodb")
def test_legacy_kwargs_still_write_their_flags(mock_dynamo):
    """Older client builds send exactly these two and must keep working."""
    from lambdas.common.device_tokens_dynamo import upsert_token

    table = MagicMock()
    table.update_item.return_value = {"Attributes": {}}
    mock_dynamo.Table.return_value = table

    upsert_token("e@x.com", "tok", digest_enabled=True, queue_notifications_enabled=False)

    kwargs = _captured_update(table)
    written = {v for v in kwargs["ExpressionAttributeNames"].values() if v.endswith("Enabled")}
    assert written == {"digestEnabled", "queueNotificationsEnabled"}


@patch("lambdas.common.device_tokens_dynamo.dynamodb")
def test_flag_placeholders_are_unique(mock_dynamo):
    """
    Several flags share a prefix; deriving placeholders from the name would
    collide and DynamoDB would reject the expression.
    """
    from lambdas.common.device_tokens_dynamo import upsert_token

    table = MagicMock()
    table.update_item.return_value = {"Attributes": {}}
    mock_dynamo.Table.return_value = table

    upsert_token("e@x.com", "tok", preferences={
        "shareReceivedEnabled": True,
        "shareRatedEnabled": False,
        "shareReactionEnabled": True,
    })

    kwargs = _captured_update(table)
    names = kwargs["ExpressionAttributeNames"]
    assert len(set(names.keys())) == len(names)
    assert len(set(kwargs["ExpressionAttributeValues"].keys())) == len(kwargs["ExpressionAttributeValues"])


# ── Register handler ────────────────────────────────────────────────────

@patch("lambdas.notifications_register.handler.upsert_token")
def test_register_returns_the_full_effective_map(mock_upsert, mock_context):
    """One response should be enough to render all sixteen Settings toggles."""
    import json
    from lambdas.notifications_register.handler import handler

    mock_upsert.return_value = {"digestEnabled": True, "shareRatedEnabled": False}

    event = {
        "body": json.dumps({"deviceToken": "a" * 16, "preferences": {"shareRatedEnabled": False}}),
        "requestContext": {"authorizer": {"email": "e@x.com"}},
    }
    response = handler(event, mock_context)
    payload = json.loads(response["body"])
    prefs = payload.get("data", payload).get("preferences")

    assert len(prefs) == len(ALL_KINDS)
    assert prefs["shareRatedEnabled"] is False
    assert prefs["digestEnabled"] is True
    assert prefs["shareCommentEnabled"] is True   # untouched -> default


@patch("lambdas.notifications_register.handler.upsert_token")
def test_register_passes_only_explicit_flags_through(mock_upsert, mock_context):
    import json
    from lambdas.notifications_register.handler import handler

    mock_upsert.return_value = {}
    event = {
        "body": json.dumps({"deviceToken": "a" * 16}),
        "requestContext": {"authorizer": {"email": "e@x.com"}},
    }
    handler(event, mock_context)

    kwargs = mock_upsert.call_args.kwargs
    assert kwargs["preferences"] == {}
    # None, not True — "client did not mention it" is not "client said yes".
    assert kwargs["digest_enabled"] is None
    assert kwargs["queue_notifications_enabled"] is None
