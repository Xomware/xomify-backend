"""
Tests for groups_update lambda — ensures updates use ExpressionAttributeNames
to avoid the DynamoDB reserved keyword collision on `name`.

Caller email is sourced from the authorizer context via `authorized_event`
(post Track 1 migration). `groupId` and the updatable fields stay in body.
"""

import json
from unittest.mock import patch, MagicMock


def _make_event(authorized_event, email: str, body: dict) -> dict:
    return authorized_event(
        email=email,
        httpMethod="PUT",
        path="/groups/update",
        body=json.dumps(body),
    )


@patch('lambdas.groups_update.handler.get_group')
@patch('lambdas.groups_update.handler.boto3')
@patch('lambdas.groups_update.handler.list_members_of_group')
def test_groups_update_uses_expression_attribute_names_for_reserved_keyword(
    mock_list_members, mock_boto3, mock_get_group, mock_context, authorized_event
):
    """`name` is a DynamoDB reserved word — the UpdateExpression must alias it via #name."""
    from lambdas.groups_update.handler import handler

    mock_list_members.return_value = [
        {"email": "owner@example.com", "groupId": "g1", "role": "owner"}
    ]

    mock_table = MagicMock()
    mock_boto3.resource.return_value.Table.return_value = mock_table

    mock_get_group.return_value = {
        "groupId": "g1",
        "name": "New Name",
        "description": "new desc",
        "createdBy": "owner@example.com",
        "memberCount": 3
    }

    event = _make_event(authorized_event, "owner@example.com", {
        "groupId": "g1",
        "name": "New Name",
        "description": "new desc"
    })

    response = handler(event, mock_context)

    assert response['statusCode'] == 200
    mock_table.update_item.assert_called_once()
    kwargs = mock_table.update_item.call_args.kwargs

    # Reserved-keyword safety: attribute names must be aliased.
    assert 'ExpressionAttributeNames' in kwargs
    assert kwargs['ExpressionAttributeNames'] == {
        '#name': 'name',
        '#desc': 'description'
    }
    assert kwargs['ExpressionAttributeValues'] == {
        ':name': 'New Name',
        ':desc': 'new desc'
    }
    # UpdateExpression should reference the aliases, not the raw attribute names.
    expr = kwargs['UpdateExpression']
    assert '#name = :name' in expr
    assert '#desc = :desc' in expr
    # Guard against regression: no raw `name =` in the expression.
    assert ' name =' not in expr


@patch('lambdas.groups_update.handler.get_group')
@patch('lambdas.groups_update.handler.boto3')
@patch('lambdas.groups_update.handler.list_members_of_group')
def test_groups_update_only_name_still_aliases_it(
    mock_list_members, mock_boto3, mock_get_group, mock_context, authorized_event
):
    """When only `name` is updated, we still alias it (the whole point of the fix)."""
    from lambdas.groups_update.handler import handler

    mock_list_members.return_value = [
        {"email": "owner@example.com", "groupId": "g1", "role": "owner"}
    ]

    mock_table = MagicMock()
    mock_boto3.resource.return_value.Table.return_value = mock_table
    mock_get_group.return_value = {"groupId": "g1", "name": "Renamed"}

    event = _make_event(authorized_event, "owner@example.com", {
        "groupId": "g1",
        "name": "Renamed"
    })

    response = handler(event, mock_context)
    assert response['statusCode'] == 200

    kwargs = mock_table.update_item.call_args.kwargs
    assert kwargs['ExpressionAttributeNames'] == {'#name': 'name'}
    assert kwargs['ExpressionAttributeValues'] == {':name': 'Renamed'}
    assert kwargs['UpdateExpression'] == 'SET #name = :name'


@patch('lambdas.groups_update.handler.list_members_of_group')
def test_groups_update_rejects_non_owner(
    mock_list_members, mock_context, authorized_event
):
    from lambdas.groups_update.handler import handler

    mock_list_members.return_value = [
        {"email": "member@example.com", "groupId": "g1", "role": "member"}
    ]

    event = _make_event(authorized_event, "member@example.com", {
        "groupId": "g1",
        "name": "Hostile Rename"
    })

    response = handler(event, mock_context)
    assert response['statusCode'] == 400


@patch('lambdas.groups_update.handler.list_members_of_group')
def test_groups_update_missing_caller_identity_returns_401(
    mock_list_members, mock_context, legacy_event,
):
    """No authorizer context AND no caller email in query/body -> 401, no DDB reads."""
    from lambdas.groups_update.handler import handler

    event = legacy_event()
    event["httpMethod"] = "PUT"
    event["path"] = "/groups/update"
    event["body"] = json.dumps({"groupId": "g1", "name": "Anon Rename"})

    response = handler(event, mock_context)

    assert response['statusCode'] == 401
    mock_list_members.assert_not_called()
