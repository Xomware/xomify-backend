"""
Regression test for `list_shares_for_user` cursor handling.

Bug: previously the function set `ExclusiveStartKey={email, createdAt}` when a
`before` cursor was supplied. That key shape is invalid for a GSI query
(missing the base table's PK `shareId`) and DynamoDB returned a
ValidationException, which got swallowed upstream and surfaced as an empty
feed page on iteration 2+ of the group-feed pagination loop.

Fix: express the cursor as `KeyConditionExpression` -> `Key("createdAt").lt(before)`
so the query is valid without needing a real LastEvaluatedKey.
"""

from unittest.mock import patch, MagicMock

from lambdas.common.shares_dynamo import list_shares_for_user


@patch('lambdas.common.shares_dynamo.dynamodb')
def test_list_shares_for_user_no_cursor_uses_simple_keycond(mock_ddb):
    table = MagicMock()
    table.query.return_value = {"Items": [], "LastEvaluatedKey": None}
    mock_ddb.Table.return_value = table

    list_shares_for_user("a@b.com", limit=25)

    kwargs = table.query.call_args.kwargs
    assert "ExclusiveStartKey" not in kwargs
    # KeyConditionExpression is a boto3.dynamodb.conditions.Equals when no cursor
    assert "KeyConditionExpression" in kwargs


@patch('lambdas.common.shares_dynamo.dynamodb')
def test_list_shares_for_user_with_before_uses_keycond_not_startkey(mock_ddb):
    table = MagicMock()
    table.query.return_value = {"Items": [], "LastEvaluatedKey": None}
    mock_ddb.Table.return_value = table

    list_shares_for_user(
        "a@b.com",
        limit=25,
        before="2026-04-28T12:00:00+00:00",
    )

    kwargs = table.query.call_args.kwargs
    # Critical: never pass ExclusiveStartKey when we don't have the base PK.
    assert "ExclusiveStartKey" not in kwargs, (
        "ExclusiveStartKey with only GSI keys is invalid for a GSI query — "
        "use KeyConditionExpression to express the cursor instead."
    )
    assert "KeyConditionExpression" in kwargs
