"""VAN-14 API and SQLite transaction behavior on an isolated database."""
from __future__ import annotations

import json
import os
from pathlib import Path

from fastapi.testclient import TestClient


EVIDENCE_DIR = Path(os.environ.get("VAN14_EVIDENCE_DIR", "/private/tmp/van14-evidence"))


class CommitFailSession:
    """Test-only DB wrapper that makes a request fail at its commit boundary."""

    def __init__(self, real_session):
        self._real_session = real_session

    def __getattr__(self, name):
        return getattr(self._real_session, name)

    def commit(self):
        raise RuntimeError("forced isolated commit failure")


def _create_training_session(client, database, date_token: str):
    exercise = client.post(
        "/api/exercises",
        json={
            "name": f"VAN-14 动作 {date_token}",
            "category": "测试",
            "difficulty": "低",
            "defaultSets": 1,
            "defaultReps": "5次",
        },
    )
    assert exercise.status_code == 201, exercise.text
    exercise_id = exercise.json()["id"]
    plan = client.post(
        "/api/plans/generate",
        json={
            "date": date_token,
            "title": f"VAN-14 {date_token}",
            "theme": "隔离失败路径",
            "exerciseIds": [exercise_id],
        },
    )
    assert plan.status_code == 200, plan.text
    started = client.post("/api/session/start", json={"plan_id": plan.json()["plan"]["id"]})
    assert started.status_code == 200, started.text
    session = started.json()["session"]
    assert session["status"] == "in_progress"
    assert session["records"]
    return plan.json()["plan"]["id"], session["id"], exercise_id


def _db_snapshot(database, session_id: int, exercise_id: int):
    db = database.SessionLocal()
    try:
        session = db.query(database.WorkoutSession).filter(database.WorkoutSession.id == session_id).one()
        record = db.query(database.SessionRecord).filter(
            database.SessionRecord.session_id == session_id,
            database.SessionRecord.exercise_id == exercise_id,
        ).one()
        logs = db.query(database.WorkoutLog).filter(database.WorkoutLog.session_id == session_id).all()
        return {
            "session_status": session.status,
            "record_status": record.status,
            "logs": [{"action": row.action, "status": row.status} for row in logs],
        }
    finally:
        db.close()


def test_van14_api_sqlite_success_and_failure_paths(app_modules, client):
    database, main = app_modules
    assert Path(database.DATABASE_PATH).parent != Path(__file__).resolve().parents[1]

    evidence = {"db_path": database.DATABASE_PATH, "scenarios": {}}

    plan_id, session_id, exercise_id = _create_training_session(client, database, "2030-01-01")
    bad_update = client.post(
        "/api/session/update",
        json={"session_id": session_id, "exercise_id": exercise_id + 99999, "status": "completed"},
    )
    assert bad_update.status_code == 422
    after_422 = _db_snapshot(database, session_id, exercise_id)
    assert after_422 == {"session_status": "in_progress", "record_status": "pending", "logs": []}
    evidence["scenarios"]["update_422"] = {"http": bad_update.status_code, "db": after_422}

    good_update = client.post(
        "/api/session/update",
        json={"session_id": session_id, "exercise_id": exercise_id, "status": "completed", "sets_completed": 1},
    )
    assert good_update.status_code == 200
    after_update = _db_snapshot(database, session_id, exercise_id)
    assert after_update["record_status"] == "completed"

    complete = client.post("/api/session/complete", json={"session_id": session_id})
    assert complete.status_code == 200
    assert complete.json()["status"] == "completed"
    after_complete = _db_snapshot(database, session_id, exercise_id)
    assert after_complete["session_status"] == "completed"
    assert after_complete["logs"] == [{"action": "completed", "status": "completed"}]
    assert client.get(f"/api/session/current?plan_id={plan_id}").json()["session"] is None
    retry_complete = client.post("/api/session/complete", json={"session_id": session_id})
    assert retry_complete.status_code == 200
    assert retry_complete.json()["status"] == "already_completed"
    assert _db_snapshot(database, session_id, exercise_id)["logs"] == after_complete["logs"]
    evidence["scenarios"]["success_and_retry"] = {
        "update": good_update.json(),
        "complete": complete.json(),
        "retry_complete": retry_complete.json(),
        "db": after_complete,
        "current_session": None,
    }

    lost_plan, lost_session, lost_exercise = _create_training_session(client, database, "2030-01-04")
    lost_update = client.post(
        "/api/session/update",
        json={"session_id": lost_session, "exercise_id": lost_exercise, "status": "completed", "sets_completed": 1},
    )
    assert lost_update.status_code == 200
    committed_before_response_loss = client.post("/api/session/complete", json={"session_id": lost_session})
    assert committed_before_response_loss.status_code == 200
    # Simulate the client losing the first response after the backend commit.
    retry_after_lost_response = client.post("/api/session/complete", json={"session_id": lost_session})
    assert retry_after_lost_response.status_code == 200
    assert retry_after_lost_response.json()["status"] == "already_completed"
    lost_snapshot = _db_snapshot(database, lost_session, lost_exercise)
    assert lost_snapshot["logs"] == [{"action": "completed", "status": "completed"}]
    evidence["scenarios"]["complete_commit_then_response_loss"] = {
        "plan_id": lost_plan,
        "first_response_discarded": committed_before_response_loss.json(),
        "retry_response": retry_after_lost_response.json(),
        "db": lost_snapshot,
    }

    plan_500_update, session_500_update, exercise_500_update = _create_training_session(client, database, "2030-01-02")

    def failing_db():
        real = database.SessionLocal()
        try:
            yield CommitFailSession(real)
        finally:
            real.rollback()
            real.close()

    main.app.dependency_overrides[main.get_db] = failing_db
    try:
        failing_client = TestClient(main.app, raise_server_exceptions=False)
        failed_update = failing_client.post(
            "/api/session/update",
            json={"session_id": session_500_update, "exercise_id": exercise_500_update, "status": "completed"},
        )
        assert failed_update.status_code == 500
    finally:
        main.app.dependency_overrides.pop(main.get_db, None)
    after_update_500 = _db_snapshot(database, session_500_update, exercise_500_update)
    assert after_update_500 == {"session_status": "in_progress", "record_status": "pending", "logs": []}
    evidence["scenarios"]["update_500"] = {"http": failed_update.status_code, "db": after_update_500}

    plan_500_complete, session_500_complete, exercise_500_complete = _create_training_session(client, database, "2030-01-03")
    final_update = client.post(
        "/api/session/update",
        json={"session_id": session_500_complete, "exercise_id": exercise_500_complete, "status": "completed", "sets_completed": 1},
    )
    assert final_update.status_code == 200
    main.app.dependency_overrides[main.get_db] = failing_db
    try:
        failing_client = TestClient(main.app, raise_server_exceptions=False)
        failed_complete = failing_client.post("/api/session/complete", json={"session_id": session_500_complete})
        assert failed_complete.status_code == 500
    finally:
        main.app.dependency_overrides.pop(main.get_db, None)
    after_complete_500 = _db_snapshot(database, session_500_complete, exercise_500_complete)
    assert after_complete_500 == {"session_status": "in_progress", "record_status": "completed", "logs": []}
    retry_after_complete_500 = client.post("/api/session/complete", json={"session_id": session_500_complete})
    assert retry_after_complete_500.status_code == 200
    assert retry_after_complete_500.json()["status"] == "completed"
    after_complete_500_retry = _db_snapshot(database, session_500_complete, exercise_500_complete)
    assert after_complete_500_retry == {"session_status": "completed", "record_status": "completed", "logs": [{"action": "completed", "status": "completed"}]}
    evidence["scenarios"]["complete_500"] = {
        "final_update": final_update.json(),
        "http": failed_complete.status_code,
        "db_after_failure": after_complete_500,
        "retry": retry_after_complete_500.json(),
        "db_after_retry": after_complete_500_retry,
    }

    EVIDENCE_DIR.mkdir(parents=True, exist_ok=True)
    (EVIDENCE_DIR / "backend-sqlite-output.json").write_text(
        json.dumps(evidence, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
