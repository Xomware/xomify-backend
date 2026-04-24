"""
Tests for groups_create lambda + create_group helper.

Covers the memberCount seeding fix: create_group must seed 0 so that the
follow-up add_group_member("owner") lands the count at 1, not 2.
"""

import json
from unittest.mock import patch, MagicMock


def _make_event(api_gateway_event, body: dict) -> dict:
    return {
        **api_gateway_event,
        "httpMethod": "POST",
        "path": "/groups/create",
        "body": json.dumps(body)
    }


@patch('lambdas.common.groups_dynamo.dynamodb')
def test_create_group_seeds_member_count_at_zero(mock_dynamodb):
    """Owner is added via add_group_member (+1) right after — so seed must be 0."""
    from lambdas.common.groups_dynamo import create_group

    mock_table = MagicMock()
    mock_dynamodb.Table.return_value = mock_table

    create_group("g1", "Test Group", "owner@example.com")

    mock_table.put_item.assert_called_once()
    item = mock_table.put_item.call_args.kwargs['Item']
    assert item['memberCount'] == 0
    assert item['groupId'] == 'g1'
    assert item['name'] == 'Test Group'
    assert item['createdBy'] == 'owner@example.com'


@patch('lambdas.groups_create.handler.add_group_member')
@patch('lambdas.groups_create.handler.create_group')
def test_groups_create_owner_results_in_member_count_of_one(
    mock_create_group, mock_add_member, mock_context, api_gateway_event
):
    """End-to-end: seed(0) + add_group_member(owner, +1) == 1."""
    from lambdas.groups_create.handler import handler

    event = _make_event(api_gateway_event, {
        "email": "owner@example.com",
        "name": "New Group"
    })

    response = handler(event, mock_context)
    assert response['statusCode'] == 200

    # create_group is called once; add_group_member once for the owner.
    mock_create_group.assert_called_once()
    mock_add_member.assert_called_once()
    args, kwargs = mock_add_member.call_args
    # add_group_member(email, group_id, role="owner")
    assert args[0] == "owner@example.com"
    assert kwargs.get('role') == 'owner'


@patch('lambdas.groups_create.handler.add_group_member')
@patch('lambdas.groups_create.handler.create_group')
def test_groups_create_with_extra_members_counts_correctly(
    mock_create_group, mock_add_member, mock_context, api_gateway_event
):
    """Seed(0) + owner(+1) + N other members(+1 each) == N + 1."""
    from lambdas.groups_create.handler import handler

    event = _make_event(api_gateway_event, {
        "email": "owner@example.com",
        "name": "Squad",
        "memberEmails": ["a@example.com", "b@example.com"]
    })

    response = handler(event, mock_context)
    assert response['statusCode'] == 200

    # 1 owner + 2 members = 3 add_group_member calls.
    assert mock_add_member.call_count == 3
