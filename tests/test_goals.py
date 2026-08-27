"""
Tests for the weekly-goals backend.

Goals were localStorage-only on web, which meant iOS couldn't have them without
creating a second, unsynced copy. This is the shared store.
"""

import json
from unittest.mock import MagicMock, patch


def _authed(body=None):
    event = {"requestContext": {"authorizer": {"email": "u@e.com"}}}
    if body is not None:
        event["body"] = json.dumps(body)
    return event


def _data(response):
    payload = json.loads(response["body"])
    return payload.get("data", payload)


def _goal(goal_id="g1", metric="minutes_listened", target=300):
    return {"goalId": goal_id, "metric": metric, "target": target, "label": "L", "icon": "headphones"}


# ── goals_get ───────────────────────────────────────────────────────────

@patch("lambdas.goals_get.handler.get_history", return_value=[])
@patch("lambdas.goals_get.handler.get_goals", return_value=[])
def test_get_returns_defaults_for_a_new_user(mock_goals, mock_hist, mock_context):
    """A first visit should show something to work toward, not a blank page."""
    from lambdas.goals_get.handler import handler, DEFAULT_GOALS

    data = _data(handler(_authed(), mock_context))
    assert len(data["goals"]) == len(DEFAULT_GOALS)
    assert data["goals"][0]["metric"] == "minutes_listened"


@patch("lambdas.goals_get.handler.get_history", return_value=[])
@patch("lambdas.goals_get.handler.get_goals")
def test_get_prefers_saved_goals_over_defaults(mock_goals, mock_hist, mock_context):
    from lambdas.goals_get.handler import handler

    mock_goals.return_value = [_goal("mine", "unique_tracks", 10)]
    data = _data(handler(_authed(), mock_context))

    assert len(data["goals"]) == 1
    assert data["goals"][0]["goalId"] == "mine"


@patch("lambdas.goals_get.handler.get_goals", return_value=[])
@patch("lambdas.goals_get.handler.get_history")
def test_get_returns_history(mock_hist, mock_goals, mock_context):
    from lambdas.goals_get.handler import handler

    mock_hist.return_value = [{"weekStart": "2026-08-24", "allMet": True, "metCount": 4, "totalCount": 4}]
    data = _data(handler(_authed(), mock_context))
    assert data["history"][0]["weekStart"] == "2026-08-24"


# ── goals_set ───────────────────────────────────────────────────────────

@patch("lambdas.goals_set.handler.replace_goals")
def test_set_saves_a_valid_goal_set(mock_replace, mock_context):
    from lambdas.goals_set.handler import handler

    mock_replace.side_effect = lambda email, goals: goals
    data = _data(handler(_authed({"goals": [_goal()]}), mock_context))

    assert len(data["goals"]) == 1
    assert mock_replace.call_args.args[0] == "u@e.com"


@patch("lambdas.goals_set.handler.replace_goals")
def test_set_rejects_an_unknown_metric(mock_replace, mock_context):
    """A typo'd metric would persist forever and compute nothing."""
    from lambdas.goals_set.handler import handler

    response = handler(_authed({"goals": [_goal(metric="vibes")]}), mock_context)
    assert response["statusCode"] == 400
    mock_replace.assert_not_called()


@patch("lambdas.goals_set.handler.replace_goals")
def test_set_rejects_a_non_positive_target(mock_replace, mock_context):
    from lambdas.goals_set.handler import handler

    assert handler(_authed({"goals": [_goal(target=0)]}), mock_context)["statusCode"] == 400
    assert handler(_authed({"goals": [_goal(target=-5)]}), mock_context)["statusCode"] == 400


@patch("lambdas.goals_set.handler.replace_goals")
def test_set_rejects_a_missing_goal_id(mock_replace, mock_context):
    from lambdas.goals_set.handler import handler

    goal = _goal()
    del goal["goalId"]
    assert handler(_authed({"goals": [goal]}), mock_context)["statusCode"] == 400


@patch("lambdas.goals_set.handler.replace_goals")
def test_set_rejects_more_than_the_cap(mock_replace, mock_context):
    from lambdas.goals_set.handler import handler
    from lambdas.common.goals_dynamo import MAX_GOALS

    goals = [_goal(f"g{i}") for i in range(MAX_GOALS + 1)]
    assert handler(_authed({"goals": goals}), mock_context)["statusCode"] == 400


@patch("lambdas.goals_set.handler.replace_goals")
def test_set_rejects_a_non_list(mock_replace, mock_context):
    from lambdas.goals_set.handler import handler

    assert handler(_authed({"goals": "nope"}), mock_context)["statusCode"] == 400


@patch("lambdas.goals_set.handler.replace_goals")
def test_set_backfills_a_missing_label(mock_replace, mock_context):
    from lambdas.goals_set.handler import handler

    mock_replace.side_effect = lambda email, goals: goals
    goal = _goal()
    goal["label"] = "   "
    data = _data(handler(_authed({"goals": [goal]}), mock_context))

    assert data["goals"][0]["label"].strip() != ""


@patch("lambdas.goals_set.handler.replace_goals")
def test_set_does_not_accept_progress(mock_replace, mock_context):
    """
    `current` and `completed` are derived from listening history. Storing them
    would freeze a number that keeps moving for the rest of the week.
    """
    from lambdas.goals_set.handler import handler

    mock_replace.side_effect = lambda email, goals: goals
    goal = {**_goal(), "current": 999, "completed": True}
    handler(_authed({"goals": [goal]}), mock_context)

    saved = mock_replace.call_args.args[1][0]
    assert "current" not in saved
    assert "completed" not in saved


# ── goals_history_set ───────────────────────────────────────────────────

@patch("lambdas.goals_history_set.handler.upsert_week")
def test_history_set_records_a_week(mock_upsert, mock_context):
    from lambdas.goals_history_set.handler import handler

    mock_upsert.side_effect = lambda email, entry: entry
    data = _data(handler(_authed({
        "weekStart": "2026-08-24", "allMet": True, "metCount": 4, "totalCount": 4
    }), mock_context))

    assert data["weekStart"] == "2026-08-24"
    assert data["allMet"] is True


@patch("lambdas.goals_history_set.handler.upsert_week")
def test_history_set_rejects_a_malformed_week(mock_upsert, mock_context):
    from lambdas.goals_history_set.handler import handler

    for bad in ["2026-8-24", "last monday", "", "2026/08/24"]:
        assert handler(_authed({"weekStart": bad}), mock_context)["statusCode"] == 400
    mock_upsert.assert_not_called()


@patch("lambdas.goals_history_set.handler.upsert_week")
def test_history_set_clamps_negative_counts(mock_upsert, mock_context):
    from lambdas.goals_history_set.handler import handler

    mock_upsert.side_effect = lambda email, entry: entry
    data = _data(handler(_authed({
        "weekStart": "2026-08-24", "metCount": -3, "totalCount": -1
    }), mock_context))

    assert data["metCount"] == 0
    assert data["totalCount"] == 0


# ── Store ───────────────────────────────────────────────────────────────

@patch("lambdas.common.goals_dynamo._table")
def test_replace_goals_deletes_what_the_client_dropped(mock_table_fn):
    """Whole-set replace: a goal the client stopped sending is a deletion."""
    from lambdas.common.goals_dynamo import replace_goals

    table = MagicMock()
    table.query.return_value = {"Items": [{"sk": "GOAL#keep"}, {"sk": "GOAL#drop"}]}
    batch = MagicMock()
    table.batch_writer.return_value.__enter__.return_value = batch
    mock_table_fn.return_value = table

    replace_goals("u@e.com", [_goal("keep")])

    deleted = [c.kwargs["Key"]["sk"] for c in batch.delete_item.call_args_list]
    assert deleted == ["GOAL#drop"]


@patch("lambdas.common.goals_dynamo._table")
def test_history_is_newest_first(mock_table_fn):
    from lambdas.common.goals_dynamo import get_history

    table = MagicMock()
    table.query.return_value = {"Items": []}
    mock_table_fn.return_value = table

    get_history("u@e.com")
    assert table.query.call_args.kwargs["ScanIndexForward"] is False


@patch("lambdas.common.goals_dynamo._table")
def test_upsert_week_keys_on_the_week(mock_table_fn):
    """One row per week, not one per page visit."""
    from lambdas.common.goals_dynamo import upsert_week

    table = MagicMock()
    mock_table_fn.return_value = table

    upsert_week("u@e.com", {"weekStart": "2026-08-24", "allMet": False, "metCount": 1, "totalCount": 4})
    assert table.put_item.call_args.kwargs["Item"]["sk"] == "HIST#2026-08-24"


@patch("lambdas.common.goals_dynamo._table")
def test_stored_rows_do_not_leak_table_keys(mock_table_fn):
    from lambdas.common.goals_dynamo import upsert_week

    table = MagicMock()
    mock_table_fn.return_value = table

    result = upsert_week("u@e.com", {"weekStart": "2026-08-24"})
    assert "email" not in result and "sk" not in result
