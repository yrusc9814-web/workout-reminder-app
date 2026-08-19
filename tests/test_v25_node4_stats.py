from datetime import date, datetime, timezone


def test_stats_sum_only_real_durations_and_separate_zero_from_unknown(client, app_modules):
    database, _main = app_modules
    before = client.get("/api/stats/month", params={"month": "2026-11"})
    assert before.status_code == 200
    before_body = before.json()

    db = database.SessionLocal()
    try:
        exercises = db.query(database.Exercise).order_by(database.Exercise.id.asc()).limit(3).all()
        plan = database.WorkoutPlan(
            plan_date=date(2026, 11, 2),
            title="统计时长边界",
            is_training_day=True,
            focus="测试",
        )
        db.add(plan)
        db.flush()
        session = database.WorkoutSession(
            plan_id=plan.id,
            status="completed",
            started_at=datetime.now(timezone.utc),
            completed_at=datetime.now(timezone.utc),
        )
        db.add(session)
        db.flush()
        db.add_all([
            database.SessionRecord(
                session_id=session.id,
                exercise_id=exercises[0].id,
                status="completed",
                duration_seconds=125,
            ),
            database.SessionRecord(
                session_id=session.id,
                exercise_id=exercises[1].id,
                status="completed",
                duration_seconds=0,
            ),
            database.SessionRecord(
                session_id=session.id,
                exercise_id=exercises[2].id,
                status="completed",
                duration_seconds=None,
            ),
        ])
        db.add(database.WorkoutLog(
            plan_id=plan.id,
            session_id=session.id,
            log_date=date(2026, 11, 2),
            action="completed",
            status="completed",
        ))
        db.commit()
    finally:
        db.close()

    after = client.get("/api/stats/month", params={"month": "2026-11"})
    assert after.status_code == 200
    body = after.json()
    assert body["duration_seconds"] == before_body["duration_seconds"] + 125
    assert body["duration_known_records"] == before_body["duration_known_records"] + 2
    assert body["duration_unknown_records"] == before_body["duration_unknown_records"] + 1
    assert body["duration_zero_records"] == before_body["duration_zero_records"] + 1


def test_stats_unknown_duration_does_not_become_zero(client):
    body = client.get("/api/stats").json()
    assert body["duration_seconds"] >= 0
    assert body["duration_unknown_records"] >= 0
    assert body["duration_zero_records"] >= 0
    assert body["duration_zero_records"] <= body["duration_known_records"]


def test_month_completion_rate_counts_completed_training_days_only(client, app_modules):
    database, _main = app_modules
    db = database.SessionLocal()
    try:
        training_plan = (
            db.query(database.WorkoutPlan)
            .filter(
                database.WorkoutPlan.plan_date == date(2026, 6, 1),
                database.WorkoutPlan.is_training_day == True,
            )
            .one()
        )
        rest_plan = (
            db.query(database.WorkoutPlan)
            .filter(
                database.WorkoutPlan.plan_date == date(2026, 6, 2),
                database.WorkoutPlan.is_training_day == False,
            )
            .one()
        )
        db.add_all([
            database.WorkoutLog(
                plan_id=training_plan.id,
                log_date=training_plan.plan_date,
                action="completed",
                status="completed",
            ),
            database.WorkoutLog(
                plan_id=rest_plan.id,
                log_date=rest_plan.plan_date,
                action="completed",
                status="completed",
            ),
        ])
        db.commit()
    finally:
        db.close()

    body = client.get("/api/stats/month", params={"month": "2026-06"}).json()
    detail = client.get("/api/stats/month/detail", params={"month": "2026-06"}).json()
    assert body["training_days"] == 13
    assert body["completed"] == 2
    assert body["completion_rate"] == round(100 / 13, 2)
    assert body["completion_rate"] == detail["completion_rate"]


def test_stats_detail_contract_has_completion_rate_and_sunday_to_saturday(client):
    month = client.get("/api/stats/month/detail", params={"month": "2026-06"})
    assert month.status_code == 200
    month_body = month.json()
    assert month_body["period"] == "month"
    assert month_body["completion_rate"] >= 0
    assert len(month_body["days"]) == 30
    assert month_body["days"][0]["date"] == "2026-06-01"

    week = client.get("/api/stats/week/detail", params={"date": "2026-06-17"})
    assert week.status_code == 200
    body = week.json()
    assert body["period"] == "week"
    assert body["start_date"] == "2026-06-14"  # Sunday
    assert body["end_date"] == "2026-06-20"  # Saturday
    assert len(body["days"]) == 7
    assert [day["day_of_week"] for day in body["days"]] == list(range(7))
    assert [day["date"] for day in body["days"]] == [
        "2026-06-14", "2026-06-15", "2026-06-16", "2026-06-17",
        "2026-06-18", "2026-06-19", "2026-06-20",
    ]


def test_calendar_returns_items_array_for_training_and_rest_days(client):
    response = client.get("/api/calendar", params={"year": 2026, "month": 6})
    assert response.status_code == 200
    days = response.json()["days"]
    assert all(isinstance(day["items"], list) for day in days)
    training_day = next(day for day in days if day["is_training"])
    rest_day = next(day for day in days if not day["is_training"])
    assert training_day["items"]
    assert rest_day["items"] == []
