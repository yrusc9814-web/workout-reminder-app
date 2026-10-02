"""VAN-16 date-range and refresh source-of-truth regressions."""
from __future__ import annotations

def _create_exercise(client, name: str) -> int:
    response = client.post(
        "/api/exercises",
        json={
            "name": name,
            "category": "VAN-16",
            "difficulty": "低",
            "defaultSets": 1,
            "defaultReps": "8次",
        },
    )
    assert response.status_code == 201, response.text
    return response.json()["id"]


def _create_plan(client, plan_date: str, exercise_id: int) -> dict:
    response = client.post(
        "/api/plans/generate",
        json={
            "date": plan_date,
            "title": "VAN-16 日期范围计划",
            "theme": "范围读取",
            "exerciseIds": [exercise_id],
        },
    )
    assert response.status_code == 200, response.text
    return response.json()["plan"]


def test_empty_month_is_real_empty_range(client):
    month = client.get("/api/plans/month", params={"month": "2032-02"})
    calendar = client.get("/api/calendar", params={"month": "2032-02"})
    stats = client.get("/api/stats/month", params={"month": "2032-02"})
    detail = client.get("/api/stats/month/detail", params={"month": "2032-02"})

    assert month.status_code == calendar.status_code == stats.status_code == detail.status_code == 200
    assert len(month.json()["days"]) == 29
    assert len(calendar.json()["days"]) == 29
    assert all(day["id"] is None and not day["is_training"] for day in month.json()["days"])
    assert all(day["plan_id"] is None and not day["is_training"] for day in calendar.json()["days"])
    assert stats.json()["training_days"] == 0
    assert stats.json()["completed"] == 0
    assert detail.json()["completed"] == 0
    assert all(day["status"] == "rest" for day in detail.json()["days"])


def test_cross_year_week_reads_both_month_boundaries(client):
    exercise_id = _create_exercise(client, "VAN-16 跨年动作")
    plan = _create_plan(client, "2026-12-31", exercise_id)

    plans = client.get("/api/plans/week", params={"date": "2027-01-01"})
    stats = client.get("/api/stats/week/detail", params={"date": "2027-01-01"})

    assert plans.status_code == stats.status_code == 200
    # The existing plan-week endpoint keeps its Monday-to-Sunday contract.
    assert plans.json()["start"] == "2026-12-28"
    assert plans.json()["end"] == "2027-01-03"
    visible = {day["date"]: day for day in plans.json()["days"]}
    assert visible["2026-12-31"]["id"] == plan["id"]
    assert visible["2027-01-01"]["id"] is None
    # Statistics keeps its established Sunday-to-Saturday contract.
    assert stats.json()["start_date"] == "2026-12-27"
    assert stats.json()["end_date"] == "2027-01-02"
    assert len(stats.json()["days"]) == 7


def test_completed_session_changes_month_detail_after_backend_commit(client):
    exercise_id = _create_exercise(client, "VAN-16 完成动作")
    plan = _create_plan(client, "2032-02-03", exercise_id)

    started = client.post("/api/session/start", json={"plan_id": plan["id"]})
    assert started.status_code == 200, started.text
    session = started.json()["session"]
    updated = client.post(
        "/api/session/update",
        json={
            "session_id": session["id"],
            "exercise_id": exercise_id,
            "status": "completed",
            "sets_completed": 1,
            "duration_seconds": 42,
        },
    )
    assert updated.status_code == 200, updated.text
    completed = client.post("/api/session/complete", json={"session_id": session["id"]})
    assert completed.status_code == 200, completed.text
    assert completed.json()["status"] == "completed"

    detail = client.get("/api/stats/month/detail", params={"month": "2032-02"})
    stats = client.get("/api/stats/month", params={"month": "2032-02"})
    calendar = client.get("/api/calendar", params={"month": "2032-02"})
    assert detail.json()["completed"] == 1
    assert next(day for day in detail.json()["days"] if day["date"] == "2032-02-03")["status"] == "completed"
    assert stats.json()["duration_seconds"] == 42
    assert stats.json()["action_stats"] == [{"name": "VAN-16 完成动作", "sets": 1}]
    assert next(day for day in calendar.json()["days"] if day["date"] == "2032-02-03")["plan_id"] == plan["id"]


def test_month_queries_do_not_reuse_another_month_plan(client):
    exercise_id = _create_exercise(client, "VAN-16 月份隔离动作")
    plan = _create_plan(client, "2032-02-29", exercise_id)

    january = client.get("/api/plans/month", params={"month": "2032-01"}).json()
    march = client.get("/api/plans/month", params={"month": "2032-03"}).json()
    assert all(day["id"] is None for day in january["days"])
    assert all(day["id"] is None for day in march["days"])
    february = client.get("/api/plans/month", params={"month": "2032-02"}).json()
    assert next(day for day in february["days"] if day["date"] == "2032-02-29")["id"] == plan["id"]
