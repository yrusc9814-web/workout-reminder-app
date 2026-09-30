from pathlib import Path


V25_SOURCE = Path(__file__).resolve().parents[1] / "static" / "index.html"


def test_v25_uses_unified_session_completion_contract():
    source = V25_SOURCE.read_text(encoding="utf-8")
    assert "/api/session/start" in source
    assert "/api/session/update" in source
    assert "/api/session/complete" in source
    assert "/api/logs/complete" not in source


def test_session_lifecycle_keeps_records_and_one_completion_log(client, app_modules):
    database, _main = app_modules
    exercise_ids = []
    for name in ("v25闭环动作一", "v25闭环动作二"):
        created = client.post("/api/exercises", json={
            "name": name,
            "category": "v25 rehearsal",
            "difficulty": "低",
            "defaultSets": 1,
            "defaultReps": "5次",
        })
        assert created.status_code == 201
        exercise_ids.append(created.json()["id"])

    generated = client.post("/api/plans/generate", json={
        "date": "2026-12-08",
        "title": "v25 session 闭环",
        "theme": "rehearsal",
        "exerciseIds": exercise_ids,
    })
    assert generated.status_code == 200
    plan_id = generated.json()["plan"]["id"]

    started = client.post("/api/session/start", json={"plan_id": plan_id})
    assert started.status_code == 200
    session = started.json()["session"]
    assert session["status"] == "in_progress"
    assert [record["status"] for record in session["records"]] == ["pending", "pending"]
    session_id = session["id"]

    for record in session["records"]:
        updated = client.post("/api/session/update", json={
            "session_id": session_id,
            "exercise_id": record["exercise_id"],
            "status": "completed",
            "sets_completed": 1,
        })
        assert updated.status_code == 200
        assert updated.json()["record"]["status"] == "completed"

    completed = client.post("/api/session/complete", json={"session_id": session_id})
    assert completed.status_code == 200
    assert completed.json()["status"] == "completed"
    assert completed.json()["session"]["status"] == "completed"
    assert completed.json()["summary"]["completed_records"] == 2
    assert all(record["status"] == "completed" for record in completed.json()["session"]["records"])

    repeated = client.post("/api/session/complete", json={"session_id": session_id})
    assert repeated.status_code == 200
    assert repeated.json()["status"] == "already_completed"

    db = database.SessionLocal()
    try:
        session_rows = db.query(database.WorkoutSession).filter_by(id=session_id).all()
        record_rows = db.query(database.SessionRecord).filter_by(session_id=session_id).all()
        log_rows = db.query(database.WorkoutLog).filter_by(
            plan_id=plan_id,
            action="completed",
        ).all()
        assert len(session_rows) == 1
        assert session_rows[0].status == "completed"
        assert len(record_rows) == 2
        assert {record.status for record in record_rows} == {"completed"}
        assert len(log_rows) == 1
        assert log_rows[0].session_id == session_id
    finally:
        db.close()
