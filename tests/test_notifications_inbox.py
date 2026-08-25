"""
Tests for the notifications inbox (B3).

Two behaviours carry most of the risk: paging (an off-by-one in the cursor
either loses items or repeats them forever) and the inbox/push independence
rule — a muted kind must still land in history.
"""

import json
from unittest.mock import MagicMock, patch


# ── Store ───────────────────────────────────────────────────────────────

@patch("lambdas.common.notifications_dynamo._table")
def test_put_notification_writes_the_expected_shape(mock_table_fn):
    from lambdas.common.notifications_dynamo import put_notification

    table = MagicMock()
    mock_table_fn.return_value = table

    assert put_notification(
        email="r@e.com", kind="share_received",
        title="Sam sent you a song", body="Midnight City — M83",
        route="share:abc", actor_email="s@e.com", actor_name="Sam",
    ) is True

    item = table.put_item.call_args.kwargs["Item"]
    assert item["email"] == "r@e.com"
    assert item["read"] is False
    assert item["kind"] == "share_received"
    assert item["route"] == "share:abc"
    assert "ttl" in item
    # SK must be time-ordered so a descending query is newest-first for free.
    assert item["tsId"].startswith(item["createdAt"])


@patch("lambdas.common.notifications_dynamo._table")
def test_put_notification_omits_empty_optional_fields(mock_table_fn):
    """Empty strings persisted as attributes are noise the clients must guard."""
    from lambdas.common.notifications_dynamo import put_notification

    table = MagicMock()
    mock_table_fn.return_value = table
    put_notification(email="r@e.com", kind="digest", title="t", body="b")

    item = table.put_item.call_args.kwargs["Item"]
    for absent in ("route", "actorEmail", "actorName", "imageUrl"):
        assert absent not in item


@patch("lambdas.common.notifications_dynamo._table")
def test_put_notification_is_fail_open(mock_table_fn):
    """A failed inbox write must not stop the push."""
    from lambdas.common.notifications_dynamo import put_notification

    table = MagicMock()
    table.put_item.side_effect = RuntimeError("dynamo down")
    mock_table_fn.return_value = table

    assert put_notification(email="r@e.com", kind="digest", title="t", body="b") is False


@patch("lambdas.common.notifications_dynamo._table")
def test_list_returns_newest_first_and_a_cursor(mock_table_fn):
    from lambdas.common.notifications_dynamo import list_notifications

    table = MagicMock()
    table.query.return_value = {
        "Items": [{"tsId": "2026-08-25T00:00:00+00:00#aaaaaaaa"}],
        "LastEvaluatedKey": {"email": "r@e.com", "tsId": "2026-08-24T00:00:00+00:00#bbbbbbbb"},
    }
    mock_table_fn.return_value = table

    page = list_notifications("r@e.com")

    assert table.query.call_args.kwargs["ScanIndexForward"] is False
    assert len(page["items"]) == 1
    assert page["nextCursor"] == "2026-08-24T00:00:00+00:00#bbbbbbbb"


@patch("lambdas.common.notifications_dynamo._table")
def test_list_last_page_has_no_cursor(mock_table_fn):
    """A non-null cursor on the last page makes clients page forever."""
    from lambdas.common.notifications_dynamo import list_notifications

    table = MagicMock()
    table.query.return_value = {"Items": []}
    mock_table_fn.return_value = table

    assert list_notifications("r@e.com")["nextCursor"] is None


@patch("lambdas.common.notifications_dynamo._table")
def test_list_clamps_the_page_size(mock_table_fn):
    from lambdas.common.notifications_dynamo import list_notifications, MAX_PAGE

    table = MagicMock()
    table.query.return_value = {"Items": []}
    mock_table_fn.return_value = table

    list_notifications("r@e.com", limit=9999)
    assert table.query.call_args.kwargs["Limit"] == MAX_PAGE

    list_notifications("r@e.com", limit=0)
    assert table.query.call_args.kwargs["Limit"] >= 1


@patch("lambdas.common.notifications_dynamo._table")
def test_cursor_becomes_an_exclusive_start_key(mock_table_fn):
    from lambdas.common.notifications_dynamo import list_notifications

    table = MagicMock()
    table.query.return_value = {"Items": []}
    mock_table_fn.return_value = table

    list_notifications("r@e.com", cursor="2026-08-24T00:00:00+00:00#bbbbbbbb")
    assert table.query.call_args.kwargs["ExclusiveStartKey"] == {
        "email": "r@e.com",
        "tsId": "2026-08-24T00:00:00+00:00#bbbbbbbb",
    }


@patch("lambdas.common.notifications_dynamo._table")
def test_count_unread_follows_pagination(mock_table_fn):
    """A single query's Count is only this page — stopping early undercounts."""
    from lambdas.common.notifications_dynamo import count_unread

    table = MagicMock()
    table.query.side_effect = [
        {"Count": 3, "LastEvaluatedKey": {"email": "r@e.com", "tsId": "x"}},
        {"Count": 2},
    ]
    mock_table_fn.return_value = table

    assert count_unread("r@e.com") == 5


@patch("lambdas.common.notifications_dynamo._table")
def test_mark_all_read_is_bounded(mock_table_fn):
    """An unbounded update loop is how a lambda finds its timeout."""
    from lambdas.common.notifications_dynamo import mark_all_read, MAX_MARK_ALL

    table = MagicMock()
    table.query.return_value = {
        "Items": [{"tsId": f"t{i}"} for i in range(MAX_MARK_ALL + 50)],
    }
    mock_table_fn.return_value = table

    assert mark_all_read("r@e.com") == MAX_MARK_ALL


@patch("lambdas.common.notifications_dynamo._table")
def test_mark_read_will_not_resurrect_a_reaped_row(mock_table_fn):
    from lambdas.common.notifications_dynamo import mark_read

    table = MagicMock()
    mock_table_fn.return_value = table
    mark_read("r@e.com", "t1")

    assert "attribute_exists" in table.update_item.call_args.kwargs["ConditionExpression"]


# ── notify() integration ────────────────────────────────────────────────

@patch("lambdas.common.notify.put_notification")
@patch("lambdas.common.notify._lambda_client")
def test_notify_writes_the_inbox_row(mock_client, mock_put):
    from lambdas.common.notify import notify

    notify("share_received", "r@e.com", actor_email="s@e.com",
           actor_name="Sam", track_name="Midnight City",
           artist_name="M83", share_id="abc")

    kwargs = mock_put.call_args.kwargs
    assert kwargs["email"] == "r@e.com"
    assert kwargs["kind"] == "share_received"
    assert kwargs["title"] == "Sam sent you a song"
    assert kwargs["route"] == "share:abc"
    assert kwargs["actor_name"] == "Sam"


@patch("lambdas.common.notify.put_notification")
@patch("lambdas.common.notify._lambda_client")
def test_inbox_row_is_written_even_when_push_dispatch_is_impossible(mock_client, mock_put):
    """
    Muting a push means 'do not interrupt me', not 'hide this from my history'.
    Web has no APNs token at all and would otherwise have an empty inbox forever.
    """
    import lambdas.common.notify as notify_mod
    from lambdas.common.notify import notify

    original = notify_mod.NOTIFICATIONS_SEND_FUNCTION_NAME
    notify_mod.NOTIFICATIONS_SEND_FUNCTION_NAME = ""
    try:
        notify("friend_request", "r@e.com", actor_email="s@e.com", actor_name="Sam")
    finally:
        notify_mod.NOTIFICATIONS_SEND_FUNCTION_NAME = original

    mock_put.assert_called_once()
    mock_client.invoke.assert_not_called()


@patch("lambdas.common.notify.put_notification")
@patch("lambdas.common.notify._lambda_client")
def test_self_notification_writes_no_inbox_row_either(mock_client, mock_put):
    from lambdas.common.notify import notify

    notify("share_comment", "same@e.com", actor_email="same@e.com")
    mock_put.assert_not_called()


# ── Handlers ────────────────────────────────────────────────────────────

def _authed(body=None, params=None):
    event = {"requestContext": {"authorizer": {"email": "r@e.com"}}}
    if body is not None:
        event["body"] = json.dumps(body)
    if params is not None:
        event["queryStringParameters"] = params
    return event


@patch("lambdas.notifications_feed.handler.list_notifications")
def test_feed_handler_returns_items_and_cursor(mock_list, mock_context):
    from lambdas.notifications_feed.handler import handler

    mock_list.return_value = {"items": [{"tsId": "a"}], "nextCursor": "b"}
    response = handler(_authed(params={"limit": "10", "cursor": "z"}), mock_context)

    assert response["statusCode"] == 200
    payload = json.loads(response["body"])
    data = payload.get("data", payload)
    assert data["nextCursor"] == "b"
    assert mock_list.call_args.kwargs["limit"] == 10
    assert mock_list.call_args.kwargs["cursor"] == "z"


@patch("lambdas.notifications_feed.handler.list_notifications")
def test_feed_handler_tolerates_a_junk_limit(mock_list, mock_context):
    """Not worth a 400 — fall back to the default page."""
    from lambdas.notifications_feed.handler import handler

    mock_list.return_value = {"items": [], "nextCursor": None}
    handler(_authed(params={"limit": "banana"}), mock_context)
    assert mock_list.call_args.kwargs["limit"] == 25


@patch("lambdas.notifications_read.handler.mark_read")
def test_read_handler_marks_one(mock_mark, mock_context):
    from lambdas.notifications_read.handler import handler

    mock_mark.return_value = True
    response = handler(_authed(body={"tsId": "t1"}), mock_context)

    data = json.loads(response["body"])
    assert data.get("data", data)["updated"] == 1
    mock_mark.assert_called_once_with("r@e.com", "t1")


@patch("lambdas.notifications_read.handler.mark_all_read")
def test_read_handler_marks_all(mock_mark_all, mock_context):
    from lambdas.notifications_read.handler import handler

    mock_mark_all.return_value = 7
    response = handler(_authed(body={"all": True}), mock_context)

    data = json.loads(response["body"])
    assert data.get("data", data)["updated"] == 7


def test_read_handler_requires_a_target(mock_context):
    from lambdas.notifications_read.handler import handler

    response = handler(_authed(body={}), mock_context)
    assert response["statusCode"] == 400


@patch("lambdas.notifications_unread_count.handler.count_unread")
def test_unread_count_handler(mock_count, mock_context):
    from lambdas.notifications_unread_count.handler import handler

    mock_count.return_value = 4
    response = handler(_authed(), mock_context)

    data = json.loads(response["body"])
    assert data.get("data", data)["unread"] == 4
