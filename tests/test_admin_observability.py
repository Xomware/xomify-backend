"""
Tests for the admin observability endpoints (Health, Users, Crons,
Notifications, view-as) and the POST /visits/log endpoint.

Admin email is `admin@example.com` (conftest). Non-admin uses the default
`test@example.com` identity.
"""

import json
from unittest.mock import patch

ADMIN = "admin@example.com"
NON_ADMIN = "test@example.com"


# ============================================
# admin_health
# ============================================

@patch("lambdas.admin_health.handler.query_requests_since")
def test_health_aggregates_by_route(mock_q, authorized_event, mock_context):
    from lambdas.admin_health.handler import handler

    mock_q.return_value = [
        {"ts": "2026-07-28T10:00:00+00:00", "path": "/user/data", "method": "GET",
         "status": 200, "email": "a@x.com", "durationMs": 10},
        {"ts": "2026-07-28T10:01:00+00:00", "path": "/user/data", "method": "GET",
         "status": 200, "email": "b@x.com", "durationMs": 30},
        {"ts": "2026-07-28T10:02:00+00:00", "path": "/user/data", "method": "GET",
         "status": 500, "email": "b@x.com", "durationMs": 50, "error": "boom"},
    ]

    event = authorized_event(email=ADMIN, httpMethod="GET",
                             queryStringParameters={"windowHours": "12"})
    response = handler(event, mock_context)

    assert response["statusCode"] == 200
    body = json.loads(response["body"])
    assert body["windowHours"] == 12
    assert body["totalCalls"] == 3
    assert body["errorCount"] == 1
    assert len(body["byRoute"]) == 1
    route = body["byRoute"][0]
    assert route["path"] == "/user/data"
    assert route["count"] == 3
    assert route["errors"] == 1
    assert route["p50ms"] == 30  # median of [10,30,50]
    assert len(body["recentErrors"]) == 1
    assert body["recentErrors"][0]["error"] == "boom"


@patch("lambdas.admin_health.handler.query_requests_since")
def test_health_default_window_and_non_admin(mock_q, authorized_event, mock_context):
    from lambdas.admin_health.handler import handler

    # non-admin -> 403, data function never called
    resp = handler(authorized_event(email=NON_ADMIN, httpMethod="GET"), mock_context)
    assert resp["statusCode"] == 403
    mock_q.assert_not_called()

    mock_q.return_value = []
    resp2 = handler(authorized_event(email=ADMIN, httpMethod="GET"), mock_context)
    assert resp2["statusCode"] == 200
    assert json.loads(resp2["body"])["windowHours"] == 24  # default


# ============================================
# admin_users_list
# ============================================

@patch("lambdas.admin_users_list.handler.full_table_scan")
def test_users_list_maps_optins(mock_scan, authorized_event, mock_context):
    from lambdas.admin_users_list.handler import handler

    mock_scan.return_value = [
        {"email": "a@x.com", "displayName": "A", "active": True,
         "refreshToken": "tok", "activeWrapped": True, "activeReleaseRadar": False,
         "likes_public": False, "lastSeen": "2026-07-28T10:00:00+00:00"},
        {"email": "b@x.com", "active": False},  # legacy/sparse row
    ]

    resp = handler(authorized_event(email=ADMIN, httpMethod="GET"), mock_context)
    assert resp["statusCode"] == 200
    body = json.loads(resp["body"])
    a = next(u for u in body if u["email"] == "a@x.com")
    assert a["optIns"] == {"wrapped": True, "releaseRadar": False,
                           "likesPublic": False, "favoritesReminder": True}
    assert a["spotifyConnected"] is True
    b = next(u for u in body if u["email"] == "b@x.com")
    assert b["optIns"]["likesPublic"] is True  # default when attr absent
    assert b["optIns"]["favoritesReminder"] is False
    assert b["spotifyConnected"] is False


def test_users_list_non_admin_403(authorized_event, mock_context):
    from lambdas.admin_users_list.handler import handler
    resp = handler(authorized_event(email=NON_ADMIN, httpMethod="GET"), mock_context)
    assert resp["statusCode"] == 403


# ============================================
# admin_user_visits
# ============================================

@patch("lambdas.admin_user_visits.handler.list_visits_for_user")
def test_user_visits_happy(mock_list, authorized_event, mock_context):
    from lambdas.admin_user_visits.handler import handler

    mock_list.return_value = [
        {"email": "u@x.com", "ts": "2026-07-28T10:00:00+00:00#ab",
         "visitedAt": "2026-07-28T10:00:00+00:00", "path": "/home"},
    ]
    event = authorized_event(email=ADMIN, httpMethod="GET",
                             queryStringParameters={"email": "u@x.com"})
    resp = handler(event, mock_context)
    assert resp["statusCode"] == 200
    body = json.loads(resp["body"])
    assert body == [{"ts": "2026-07-28T10:00:00+00:00", "path": "/home"}]
    mock_list.assert_called_once_with("u@x.com")


def test_user_visits_missing_email_400(authorized_event, mock_context):
    from lambdas.admin_user_visits.handler import handler
    resp = handler(authorized_event(email=ADMIN, httpMethod="GET",
                                    queryStringParameters={}), mock_context)
    assert resp["statusCode"] == 400


# ============================================
# admin_crons
# ============================================

@patch("lambdas.admin_crons.handler.list_all_runs")
def test_crons_grouped_lastrun(mock_runs, authorized_event, mock_context):
    from lambdas.admin_crons.handler import handler

    mock_runs.return_value = [
        {"cronName": "wrapped", "startedAt": "2026-07-01T00:00:00+00:00",
         "finishedAt": "2026-07-01T00:01:00+00:00", "status": "ok",
         "itemsProcessed": 3},
        {"cronName": "wrapped", "startedAt": "2026-08-01T00:00:00+00:00",
         "finishedAt": "2026-08-01T00:01:00+00:00", "status": "error",
         "error": "kaboom"},
    ]
    resp = handler(authorized_event(email=ADMIN, httpMethod="GET"), mock_context)
    assert resp["statusCode"] == 200
    body = json.loads(resp["body"])
    assert len(body) == 1
    cron = body[0]
    assert cron["cronName"] == "wrapped"
    # newest first -> lastRun is the August error run
    assert cron["lastRun"]["status"] == "error"
    assert cron["lastRun"]["error"] == "kaboom"
    assert len(cron["recentRuns"]) == 2


def test_crons_non_admin_403(authorized_event, mock_context):
    from lambdas.admin_crons.handler import handler
    resp = handler(authorized_event(email=NON_ADMIN, httpMethod="GET"), mock_context)
    assert resp["statusCode"] == 403


# ============================================
# admin_notifications
# ============================================

@patch("lambdas.admin_notifications.handler.list_recent_notifications")
def test_notifications_happy_and_limit(mock_list, authorized_event, mock_context):
    from lambdas.admin_notifications.handler import handler

    mock_list.return_value = [
        {"ts": "2026-07-28T10:00:00+00:00", "channel": "email",
         "toEmail": "u@x.com", "subject": "Hi", "bodyPreview": "body",
         "status": "sent"},
    ]
    event = authorized_event(email=ADMIN, httpMethod="GET",
                             queryStringParameters={"limit": "5"})
    resp = handler(event, mock_context)
    assert resp["statusCode"] == 200
    body = json.loads(resp["body"])
    assert body[0]["channel"] == "email"
    assert body[0]["status"] == "sent"
    mock_list.assert_called_once_with(5)


# ============================================
# admin_view_as
# ============================================

@patch("lambdas.admin_view_as.handler.get_active_broadcasts")
@patch("lambdas.admin_view_as.handler.list_visits_for_user")
@patch("lambdas.admin_view_as.handler.get_lists_for_year")
@patch("lambdas.admin_view_as.handler.get_user_table_data")
def test_view_as_projection(mock_user, mock_favs, mock_visits, mock_bcast,
                            authorized_event, mock_context):
    from lambdas.admin_view_as.handler import handler

    mock_user.return_value = {
        "email": "u@x.com", "displayName": "U", "userId": "sp1", "avatar": "a",
        "active": True, "refreshToken": "tok", "activeWrapped": True,
        "activeReleaseRadar": True, "lastSeen": "2026-07-28T10:00:00+00:00",
    }
    mock_favs.return_value = [{"listId": "overall", "items": []}]
    mock_visits.return_value = [
        {"visitedAt": "2026-07-28T10:00:00+00:00", "path": "/home", "ts": "x"}]
    mock_bcast.return_value = [
        {"broadcastId": "b1", "title": "t", "body": "b",
         "activeUntil": None, "createdAt": "2026-07-01T00:00:00+00:00"}]

    event = authorized_event(email=ADMIN, httpMethod="GET",
                             queryStringParameters={"email": "u@x.com"})
    resp = handler(event, mock_context)
    assert resp["statusCode"] == 200
    body = json.loads(resp["body"])
    assert body["email"] == "u@x.com"
    assert body["profile"]["spotifyConnected"] is True
    assert body["optIns"]["wrapped"] is True
    assert body["recentVisits"] == [{"ts": "2026-07-28T10:00:00+00:00", "path": "/home"}]
    assert body["favorites"] == [{"listId": "overall", "items": []}]
    assert body["activeBroadcasts"][0]["id"] == "b1"
    assert "note" in body


def test_view_as_missing_email_400(authorized_event, mock_context):
    from lambdas.admin_view_as.handler import handler
    resp = handler(authorized_event(email=ADMIN, httpMethod="GET",
                                    queryStringParameters={}), mock_context)
    assert resp["statusCode"] == 400


# ============================================
# visits_log (POST /visits/log — any authed user)
# ============================================

@patch("lambdas.visits_log.handler.put_visit")
def test_visits_log_happy(mock_put, authorized_event, mock_context):
    from lambdas.visits_log.handler import handler

    event = authorized_event(httpMethod="POST", body=json.dumps({"path": "/home"}))
    resp = handler(event, mock_context)
    assert resp["statusCode"] == 200
    body = json.loads(resp["body"])
    assert body == {"logged": True, "path": "/home"}
    mock_put.assert_called_once_with("test@example.com", "/home")


@patch("lambdas.visits_log.handler.put_visit")
def test_visits_log_missing_path_400(mock_put, authorized_event, mock_context):
    from lambdas.visits_log.handler import handler

    event = authorized_event(httpMethod="POST", body=json.dumps({}))
    resp = handler(event, mock_context)
    assert resp["statusCode"] == 400
    mock_put.assert_not_called()


def test_visits_log_missing_identity_401(legacy_event, mock_context):
    from lambdas.visits_log.handler import handler

    event = legacy_event()
    event["httpMethod"] = "POST"
    event["body"] = json.dumps({"path": "/home"})
    resp = handler(event, mock_context)
    assert resp["statusCode"] == 401
