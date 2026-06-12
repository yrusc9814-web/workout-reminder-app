from datetime import date
import importlib
import json
import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient


APP_DIR = Path(__file__).resolve().parents[1]


@pytest.fixture()
def app_modules(tmp_path, monkeypatch):
    db_path = tmp_path / "workout-test.db"
    monkeypatch.setenv("WORKOUT_DB_PATH", str(db_path))
    monkeypatch.syspath_prepend(str(APP_DIR))

    for name in ["main", "seed", "database"]:
        sys.modules.pop(name, None)

    database = importlib.import_module("database")
    main = importlib.import_module("main")
    database.Base.metadata.create_all(bind=database.engine)
    database.seed_database()
    return database, main


@pytest.fixture()
def client(app_modules):
    _database, main = app_modules
    return TestClient(main.app)


def test_health_endpoint_exists(client):
    response = client.get("/api/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_root_returns_html(client):
    response = client.get("/")

    assert response.status_code == 200
    assert "text/html" in response.headers["content-type"]
    assert "本地个人运动提醒仪表盘" in response.text


def test_today_endpoint_exists_and_returns_shape(client):
    response = client.get("/api/today")

    assert response.status_code == 200
    body = response.json()
    assert set(body) == {"date", "id", "title", "theme", "notes", "type", "is_training", "items"}


def test_month_accepts_legacy_year_month_parameters(client):
    response = client.get("/api/plans/month", params={"year": 2026, "month": 5})

    assert response.status_code == 200
    body = response.json()
    assert body["year"] == 2026
    assert body["month"] == 5
    assert len(body["days"]) == 31


def test_month_accepts_yyyy_mm_query_token_on_same_url(client):
    response = client.get("/api/plans/month", params={"month": "2026-05"})

    assert response.status_code == 200
    body = response.json()
    assert body["year"] == 2026
    assert body["month"] == 5
    assert len(body["days"]) == 31


def test_month_summary_accepts_yyyy_mm_token(client):
    response = client.get("/api/plans/month/summary", params={"month": "2026-05"})

    assert response.status_code == 200
    body = response.json()
    assert body["year"] == 2026
    assert body["month"] == 5
    assert len(body["days"]) == 31


def test_month_rejects_missing_year(client):
    response = client.get("/api/plans/month", params={"month": 5})

    assert response.status_code == 422


def test_month_rejects_invalid_yyyy_mm_token(client):
    response = client.get("/api/plans/month", params={"month": "2026/05"})

    assert response.status_code == 422


def test_week_returns_range(client):
    response = client.get("/api/plans/week", params={"date": "2026-05-11"})

    assert response.status_code == 200
    body = response.json()
    assert body["start"] == "2026-05-11"
    assert body["end"] == "2026-05-17"
    assert len(body["days"]) == 7


def test_week_rejects_invalid_date(client):
    response = client.get("/api/plans/week", params={"date": "not-a-date"})

    assert response.status_code == 422


def test_stats_endpoint_exists(client):
    response = client.get("/api/stats")

    assert response.status_code == 200
    body = response.json()
    assert {"plans", "training_days", "rest_days", "completed", "skipped", "postponed"} <= set(body)


def test_stats_month_accepts_yyyy_mm_token(client):
    response = client.get("/api/stats/month", params={"month": "2026-05"})

    assert response.status_code == 200
    body = response.json()
    assert body["month"] == "2026-05"
    assert {"plans", "training_days", "rest_days", "completed", "skipped", "postponed"} <= set(body)


def test_calendar_accepts_legacy_year_month_parameters(client):
    response = client.get("/api/calendar", params={"year": 2026, "month": 5})

    assert response.status_code == 200
    body = response.json()
    assert body["year"] == 2026
    assert body["month"] == 5
    assert len(body["days"]) == 31


def test_calendar_accepts_yyyy_mm_query_token_on_same_url(client):
    response = client.get("/api/calendar", params={"month": "2026-05"})

    assert response.status_code == 200
    body = response.json()
    assert body["year"] == 2026
    assert body["month"] == 5
    assert len(body["days"]) == 31


def test_calendar_month_accepts_yyyy_mm_token(client):
    response = client.get("/api/calendar/month", params={"month": "2026-05"})

    assert response.status_code == 200
    body = response.json()
    assert body["year"] == 2026
    assert body["month"] == 5
    assert len(body["days"]) == 31


def test_calendar_rejects_invalid_yyyy_mm_token(client):
    response = client.get("/api/calendar", params={"month": "2026/05"})

    assert response.status_code == 422


def test_settings_roundtrip(client):
    save = client.post("/api/settings", json={"key": "reminder_time", "value": "07:30"})

    assert save.status_code == 200
    assert save.json() == {"key": "reminder_time", "value": "07:30"}

    fetch = client.get("/api/settings")
    assert fetch.status_code == 200
    assert fetch.json()["settings"]["reminder_time"] == "07:30"


@pytest.mark.parametrize(
    ("endpoint", "expected_status"),
    [
        ("/api/logs/complete", "completed"),
        ("/api/logs/skip", "skipped"),
        ("/api/logs/postpone", "postponed"),
    ],
)
def test_log_endpoints_share_shape(client, endpoint, expected_status):
    plan = client.get("/api/plans/month", params={"year": 2026, "month": 5}).json()["days"][0]

    response = client.post(endpoint, json={"plan_id": plan["id"], "notes": "test"})

    assert response.status_code == 200
    body = response.json()
    assert body["plan_id"] == plan["id"]
    assert body["action"] == expected_status
    assert body["status"] == expected_status
    assert body["notes"] == "test"


def test_log_returns_404_for_missing_plan(client):
    response = client.post("/api/logs/complete", json={"plan_id": 999999, "notes": "missing"})

    assert response.status_code == 404


def test_seed_database_is_idempotent(app_modules):
    database, _main = app_modules

    db = database.SessionLocal()
    try:
        before = (
            db.query(database.WorkoutPlan).count(),
            db.query(database.WorkoutExercise).count(),
            db.query(database.Setting).count(),
        )
    finally:
        db.close()

    database.seed_database()

    db = database.SessionLocal()
    try:
        after = (
            db.query(database.WorkoutPlan).count(),
            db.query(database.WorkoutExercise).count(),
            db.query(database.Setting).count(),
        )
    finally:
        db.close()

    assert after == before


def test_seed_includes_future_months_without_changing_may(app_modules):
    database, _main = app_modules

    db = database.SessionLocal()
    try:
        may_training_dates = {
            row.plan_date
            for row in db.query(database.WorkoutPlan)
            .filter(
                database.WorkoutPlan.plan_date >= date(2026, 5, 1),
                database.WorkoutPlan.plan_date <= date(2026, 5, 31),
                database.WorkoutPlan.is_training_day == True,
            )
            .all()
        }
        assert may_training_dates == {
            date(2026, 5, 1),
            date(2026, 5, 4),
            date(2026, 5, 6),
            date(2026, 5, 8),
            date(2026, 5, 11),
            date(2026, 5, 13),
            date(2026, 5, 15),
            date(2026, 5, 18),
            date(2026, 5, 20),
            date(2026, 5, 22),
            date(2026, 5, 25),
            date(2026, 5, 27),
            date(2026, 5, 29),
        }

        assert db.query(database.WorkoutPlan).count() == 123
        assert (
            db.query(database.WorkoutPlan)
            .filter(database.WorkoutPlan.is_training_day == True)
            .count()
            == 53
        )
        assert db.query(database.WorkoutExercise).count() == 265

        expected_training_days = {6: 13, 7: 14, 8: 13}
        for month, expected_count in expected_training_days.items():
            month_start = date(2026, month, 1)
            month_end = date(2026, month, 30 if month in {6} else 31)
            training_days = (
                db.query(database.WorkoutPlan)
                .filter(
                    database.WorkoutPlan.plan_date >= month_start,
                    database.WorkoutPlan.plan_date <= month_end,
                    database.WorkoutPlan.is_training_day == True,
                )
                .all()
            )
            assert len(training_days) == expected_count
            assert {row.plan_date.weekday() for row in training_days} <= {0, 2, 4}
    finally:
        db.close()


def test_future_month_api_returns_seeded_june_plan(client):
    response = client.get("/api/plans/month", params={"month": "2026-06"})

    assert response.status_code == 200
    body = response.json()
    assert body["year"] == 2026
    assert body["month"] == 6
    assert len(body["days"]) == 30
    training_days = [day for day in body["days"] if day["is_training"]]
    assert len(training_days) == 13
    assert training_days[0]["date"] == "2026-06-01"
    assert training_days[0]["type"] == "training"
    assert len(training_days[0]["items"]) == 5


def test_today_returns_plan_on_mocked_future_training_day(app_modules, monkeypatch):
    _database, main = app_modules

    class MockDate(date):
        @classmethod
        def today(cls):
            return cls(2026, 6, 1)

    monkeypatch.setattr(main, "date", MockDate)

    with TestClient(main.app) as test_client:
        response = test_client.get("/api/today")

    assert response.status_code == 200
    body = response.json()
    assert body["date"] == "2026-06-01"
    assert body["is_training"] is True
    assert body["type"] == "training"
    assert body["id"] is not None
    assert len(body["items"]) == 5


def test_reminder_mock_endpoints_exist(client):
    wechat = client.post("/api/reminders/wechat/send", json={"title": "x", "message": "y"})
    dingtalk = client.post("/api/reminders/dingtalk/send", json={"title": "x", "message": "y"})

    assert wechat.status_code == 200
    assert dingtalk.status_code == 200
    assert wechat.json()["status"] == "not_sent"
    assert dingtalk.json()["status"] == "not_sent"


def june_training_plan(client):
    month = client.get("/api/plans/month", params={"month": "2026-06"})
    assert month.status_code == 200
    return next(day for day in month.json()["days"] if day["is_training"])


def test_training_items_include_video_links(client):
    plan = june_training_plan(client)

    assert plan["items"]
    assert all(item["video_url"].startswith("https://") for item in plan["items"])


def test_dingtalk_reminder_not_configured_returns_payload_with_video_links(client, monkeypatch):
    monkeypatch.delenv("DINGTALK_WEBHOOK_URL", raising=False)
    plan = june_training_plan(client)

    response = client.post("/api/reminders/dingtalk/send", json={"plan_id": plan["id"]})

    assert response.status_code == 200
    body = response.json()
    assert body["channel"] == "dingtalk"
    assert body["status"] == "not_configured"
    assert body["mock"] is False
    assert body["sent"] is False
    assert body["payload"]["title"] == f"【待办】{plan['title']}"
    assert f"【待办】{plan['title']}" in body["payload"]["text"]
    assert f"训练日期：{plan['date']}" in body["payload"]["text"]
    assert "训练动作：" in body["payload"]["text"]
    assert "完成后在群里回复“已完成”" in body["payload"]["text"]
    for item in plan["items"]:
        assert item["video_url"] in body["payload"]["text"]


def test_dingtalk_todo_not_configured_returns_payload_with_video_links(client, monkeypatch):
    monkeypatch.delenv("DINGTALK_TODO_CREATE_URL", raising=False)
    monkeypatch.delenv("DINGTALK_ACCESS_TOKEN", raising=False)
    plan = june_training_plan(client)

    response = client.post("/api/todos/dingtalk/create", json={"plan_id": plan["id"]})

    assert response.status_code == 200
    body = response.json()
    assert body["channel"] == "dingtalk_todo"
    assert body["status"] == "not_configured"
    assert body["created"] is False
    assert body["payload"]["subject"] == f"训练计划：{plan['title']}"
    assert plan["title"] in body["payload"]["description"]
    for item in plan["items"]:
        assert item["video_url"] in body["payload"]["description"]


def test_dingtalk_todo_uses_dingtalk_access_token_header(client, monkeypatch):
    captured = {}

    def fake_post_json(url, payload, headers=None):
        captured["url"] = url
        captured["payload"] = payload
        captured["headers"] = headers
        return 200, "{}"

    monkeypatch.setenv("DINGTALK_TODO_CREATE_URL", "https://api.dingtalk.example/todos")
    monkeypatch.setenv("DINGTALK_ACCESS_TOKEN", "test-token")
    monkeypatch.setattr("main.post_json", fake_post_json)
    plan = june_training_plan(client)

    response = client.post("/api/todos/dingtalk/create", json={"plan_id": plan["id"]})

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "created"
    assert captured["url"] == "https://api.dingtalk.example/todos"
    assert captured["headers"] == {"x-acs-dingtalk-access-token": "test-token"}
    assert captured["payload"]["subject"] == f"训练计划：{plan['title']}"
    assert "Authorization" not in captured["headers"]


def test_dingtalk_todo_permission_denied_returns_clear_status(client, monkeypatch):
    def fake_post_json(url, payload, headers=None):
        return 403, json.dumps(
            {
                "code": "Forbidden.AccessDenied.AccessTokenPermissionDenied",
                "message": "应用尚未开通所需的权限：[Todo.PersonalTodo.Write]",
            }
        )

    monkeypatch.setenv("DINGTALK_TODO_CREATE_URL", "https://api.dingtalk.example/todos")
    monkeypatch.setenv("DINGTALK_ACCESS_TOKEN", "test-token")
    monkeypatch.setattr("main.post_json", fake_post_json)
    plan = june_training_plan(client)

    response = client.post("/api/todos/dingtalk/create", json={"plan_id": plan["id"]})

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "todo_unavailable_due_to_permission"
    assert body["created"] is False
    assert body["enabled"] is True
    assert body["permission"] == "Todo.PersonalTodo.Write"
