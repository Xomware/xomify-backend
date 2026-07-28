"""
Tests for the admin broadcasts handlers + the require_admin gate.

The test admin email is `admin@example.com` (set in conftest _TEST_ENV_VARS).
Non-admin callers use the default `test@example.com` authorizer identity.
"""

import json
from unittest.mock import patch

from lambdas.common.admin import is_admin

ADMIN = "admin@example.com"
NON_ADMIN = "test@example.com"


# ============================================
# is_admin gate unit
# ============================================

def test_is_admin_case_insensitive():
    assert is_admin("ADMIN@Example.com") is True
    assert is_admin(NON_ADMIN) is False
    assert is_admin("") is False


# ============================================
# admin_broadcasts_create
# ============================================

@patch("lambdas.admin_broadcasts_create.handler.put_broadcast")
def test_create_happy_path(mock_put, authorized_event, mock_context):
    from lambdas.admin_broadcasts_create.handler import handler

    future = "2030-01-01T00:00:00+00:00"
    event = authorized_event(
        email=ADMIN,
        httpMethod="POST",
        body=json.dumps({"title": "Hi", "body": "Msg", "activeUntil": future}),
    )
    response = handler(event, mock_context)

    assert response["statusCode"] == 200
    body = json.loads(response["body"])
    assert body["title"] == "Hi"
    assert body["createdBy"] == ADMIN
    assert body["activeUntil"] == future
    assert body["id"]

    written = mock_put.call_args.args[0]
    assert written["createdBy"] == ADMIN
    # activeUntil present -> ttl epoch stamped.
    assert "ttl" in written and isinstance(written["ttl"], int)


@patch("lambdas.admin_broadcasts_create.handler.put_broadcast")
def test_create_no_active_until_omits_ttl(mock_put, authorized_event, mock_context):
    from lambdas.admin_broadcasts_create.handler import handler

    event = authorized_event(
        email=ADMIN, httpMethod="POST",
        body=json.dumps({"title": "Hi", "body": "Msg"}),
    )
    response = handler(event, mock_context)

    assert response["statusCode"] == 200
    written = mock_put.call_args.args[0]
    assert "ttl" not in written
    assert written["activeUntil"] is None


@patch("lambdas.admin_broadcasts_create.handler.put_broadcast")
def test_create_non_admin_is_403(mock_put, authorized_event, mock_context):
    from lambdas.admin_broadcasts_create.handler import handler

    event = authorized_event(
        email=NON_ADMIN, httpMethod="POST",
        body=json.dumps({"title": "Hi", "body": "Msg"}),
    )
    response = handler(event, mock_context)

    assert response["statusCode"] == 403
    mock_put.assert_not_called()


@patch("lambdas.admin_broadcasts_create.handler.put_broadcast")
def test_create_missing_identity_is_401(mock_put, legacy_event, mock_context):
    from lambdas.admin_broadcasts_create.handler import handler

    event = legacy_event()
    event["httpMethod"] = "POST"
    event["body"] = json.dumps({"title": "Hi", "body": "Msg"})
    response = handler(event, mock_context)

    assert response["statusCode"] == 401
    mock_put.assert_not_called()


@patch("lambdas.admin_broadcasts_create.handler.put_broadcast")
def test_create_missing_title_is_400(mock_put, authorized_event, mock_context):
    from lambdas.admin_broadcasts_create.handler import handler

    event = authorized_event(email=ADMIN, httpMethod="POST", body=json.dumps({"body": "Msg"}))
    response = handler(event, mock_context)

    assert response["statusCode"] == 400
    mock_put.assert_not_called()


# ============================================
# admin_broadcasts_list
# ============================================

@patch("lambdas.admin_broadcasts_list.handler.get_all_broadcasts")
def test_list_happy_path_includes_created_by(mock_all, authorized_event, mock_context):
    from lambdas.admin_broadcasts_list.handler import handler

    mock_all.return_value = [
        {
            "broadcastId": "b1", "title": "t", "body": "b",
            "activeUntil": None, "createdAt": "2026-01-01T00:00:00+00:00",
            "createdBy": ADMIN,
        }
    ]
    response = handler(authorized_event(email=ADMIN, httpMethod="GET"), mock_context)

    assert response["statusCode"] == 200
    body = json.loads(response["body"])
    b = body["broadcasts"][0]
    assert set(b.keys()) == {"id", "title", "body", "activeUntil", "createdAt", "createdBy"}
    assert b["createdBy"] == ADMIN


@patch("lambdas.admin_broadcasts_list.handler.get_all_broadcasts")
def test_list_non_admin_is_403(mock_all, authorized_event, mock_context):
    from lambdas.admin_broadcasts_list.handler import handler

    response = handler(authorized_event(email=NON_ADMIN, httpMethod="GET"), mock_context)
    assert response["statusCode"] == 403
    mock_all.assert_not_called()


# ============================================
# admin_broadcasts_delete
# ============================================

@patch("lambdas.admin_broadcasts_delete.handler.delete_broadcast")
def test_delete_happy_path(mock_delete, authorized_event, mock_context):
    from lambdas.admin_broadcasts_delete.handler import handler

    event = authorized_event(email=ADMIN, httpMethod="DELETE", queryStringParameters={"id": "b1"})
    response = handler(event, mock_context)

    assert response["statusCode"] == 200
    body = json.loads(response["body"])
    assert body == {"deleted": True, "id": "b1"}
    mock_delete.assert_called_once_with("b1")


@patch("lambdas.admin_broadcasts_delete.handler.delete_broadcast")
def test_delete_missing_id_is_400(mock_delete, authorized_event, mock_context):
    from lambdas.admin_broadcasts_delete.handler import handler

    event = authorized_event(email=ADMIN, httpMethod="DELETE", queryStringParameters={})
    response = handler(event, mock_context)

    assert response["statusCode"] == 400
    mock_delete.assert_not_called()


@patch("lambdas.admin_broadcasts_delete.handler.delete_broadcast")
def test_delete_non_admin_is_403(mock_delete, authorized_event, mock_context):
    from lambdas.admin_broadcasts_delete.handler import handler

    event = authorized_event(email=NON_ADMIN, httpMethod="DELETE", queryStringParameters={"id": "b1"})
    response = handler(event, mock_context)

    assert response["statusCode"] == 403
    mock_delete.assert_not_called()
