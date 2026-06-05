import importlib
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
    assert "训练计划与打卡联调页" in response.text


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


def test_reminder_mock_endpoints_exist(client):
    wechat = client.post("/api/reminders/wechat/send", json={"title": "x", "message": "y"})
    dingtalk = client.post("/api/reminders/dingtalk/send", json={"title": "x", "message": "y"})

    assert wechat.status_code == 200
    assert dingtalk.status_code == 200
    assert wechat.json()["status"] == "not_sent"
    assert dingtalk.json()["status"] == "not_sent"
