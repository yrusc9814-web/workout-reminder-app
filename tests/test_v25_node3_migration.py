import importlib
import sqlite3
import sys
from pathlib import Path

import pytest


@pytest.fixture()
def legacy_database(tmp_path, monkeypatch):
    path = tmp_path / "legacy-v24.db"
    conn = sqlite3.connect(path)
    conn.executescript(
        """
        CREATE TABLE templates (id INTEGER PRIMARY KEY, name VARCHAR(140), description TEXT, difficulty VARCHAR(20) NOT NULL, estimated_minutes INTEGER NOT NULL, created_at DATETIME NOT NULL, updated_at DATETIME);
        CREATE TABLE workout_plans (id INTEGER PRIMARY KEY, plan_date DATE NOT NULL UNIQUE, template_id INTEGER, title VARCHAR(120) NOT NULL, is_training_day BOOLEAN NOT NULL, focus VARCHAR(160) NOT NULL, notes TEXT, created_at DATETIME NOT NULL, updated_at DATETIME);
        CREATE TABLE workout_sessions (id INTEGER PRIMARY KEY, plan_id INTEGER NOT NULL, status VARCHAR(20) NOT NULL, started_at DATETIME NOT NULL, completed_at DATETIME, notes TEXT, rating INTEGER, ai_feedback TEXT, created_at DATETIME NOT NULL, updated_at DATETIME, CONSTRAINT ck_workout_sessions_status CHECK (status IN ('in_progress','completed','cancelled')));
        INSERT INTO workout_plans VALUES (1, '2026-07-13', NULL, 'protected', 1, 'test', 'keep', '2026-07-13 08:00:00', NULL);
        INSERT INTO workout_sessions VALUES (7, 1, 'cancelled', '2026-07-13 08:01:00', '2026-07-13 08:02:00', 'protected', NULL, NULL, '2026-07-13 08:01:00', NULL);
        """
    )
    conn.commit()
    conn.close()

    monkeypatch.setenv("WORKOUT_DB_PATH", str(path))
    monkeypatch.setenv("WORKOUT_DISABLE_SEED", "1")
    sys.modules.pop("database", None)
    database = importlib.import_module("database")
    database.create_tables()
    yield database, path
    database.engine.dispose()


def make_bundle(date_key="2026-09-01", item="仰卧骨盆时钟"):
    return {
        "format": "qingdong-training-backup",
        "version": 1,
        "exportedAt": "2026-08-17T10:00:00.000Z",
        "trainingState": {
            "version": 1,
            "updatedAt": "2026-08-17T10:00:00.000Z",
            "data": {
                "calendarPlans": {
                    date_key: {
                        "title": "历史核心训练",
                        "status": "planned",
                        "time": 10,
                        "intensity": "低强度",
                        "body": "核心",
                        "items": [f"{item} · 1组"],
                    }
                },
                "customTrainingPlans": {},
                "dailySessions": {
                    date_key: {
                        "items": [{"name": item, "spec": "1组", "time": 180}],
                        "source": "历史核心训练",
                        "stepIndex": 0,
                        "started": True,
                        "done": True,
                        "rest": False,
                        "updatedAt": "2026-08-17T10:00:00.000Z",
                    }
                },
            },
        },
    }


def test_legacy_sqlite_rebuild_preserves_protected_cancelled_session(legacy_database):
    database, path = legacy_database
    with sqlite3.connect(path) as conn:
        columns = {row[1]: row[3] for row in conn.execute("PRAGMA table_info(workout_sessions)")}
        protected = conn.execute(
            "SELECT id, status, started_at, completed_at, notes FROM workout_sessions WHERE id=7"
        ).fetchone()
    assert columns["started_at"] == 0
    assert protected == (7, "cancelled", "2026-07-13 08:01:00", "2026-07-13 08:02:00", "protected")

    result = database.migrate_database()
    assert result["integrity"] == "ok"
    with sqlite3.connect(path) as conn:
        assert conn.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
        assert conn.execute("SELECT version FROM schema_version WHERE id=1").fetchone() == (1,)


def test_preview_is_read_only_and_commit_preserves_unknown_history_as_null(client, app_modules):
    database, _main = app_modules
    bundle = make_bundle()
    before = tuple(
        db_count(database, model)
        for model in (database.WorkoutPlan, database.WorkoutExercise, database.WorkoutSession, database.SessionRecord, database.WorkoutLog)
    )

    preview_response = client.post("/api/migration/v24/preview", json=bundle)
    assert preview_response.status_code == 200
    preview = preview_response.json()
    assert preview["status"] == "ready"
    assert preview["summary"]["duration_unknown_sessions"] == 1

    after_preview = tuple(
        db_count(database, model)
        for model in (database.WorkoutPlan, database.WorkoutExercise, database.WorkoutSession, database.SessionRecord, database.WorkoutLog)
    )
    assert after_preview == before

    commit_payload = {
        **bundle,
        "source_sha256": preview["source_sha256"],
        "preview_hash": preview["preview_hash"],
        "affected_fingerprint": preview["affected_fingerprint"],
    }
    committed = client.post("/api/migration/v24/commit", json=commit_payload)
    assert committed.status_code == 200, committed.text
    assert committed.json()["status"] == "committed"

    db = database.SessionLocal()
    try:
        plan = db.query(database.WorkoutPlan).filter_by(plan_date="2026-09-01").one()
        session = db.query(database.WorkoutSession).filter_by(plan_id=plan.id).one()
        record = db.query(database.SessionRecord).filter_by(session_id=session.id).one()
        log = db.query(database.WorkoutLog).filter_by(session_id=session.id).one()
        assert session.status == "completed"
        assert session.started_at is None
        assert session.completed_at is None
        assert record.status == "completed"
        assert record.duration_seconds is None
        assert log.status == "completed"
        assert db.query(database.WorkoutExercise).filter_by(plan_id=plan.id, exercise_id=record.exercise_id).count() == 1
    finally:
        db.close()

    replay = client.post("/api/migration/v24/commit", json=commit_payload)
    assert replay.status_code == 200
    assert replay.json()["status"] == "already_committed"


def test_preview_blocks_unresolved_and_unfinished_source_without_writes(client, app_modules):
    database, _main = app_modules
    unknown = make_bundle(date_key="2026-09-02", item="不存在的历史动作")
    unknown_preview = client.post("/api/migration/v24/preview", json=unknown)
    assert unknown_preview.status_code == 200
    assert unknown_preview.json()["status"] == "blocked"
    assert any(item["code"] == "unresolved_exercise" for item in unknown_preview.json()["blockers"])

    unfinished = make_bundle(date_key="2026-09-03")
    unfinished["trainingState"]["data"]["dailySessions"]["2026-09-03"]["done"] = False
    unfinished_preview = client.post("/api/migration/v24/preview", json=unfinished)
    assert unfinished_preview.status_code == 200
    assert unfinished_preview.json()["status"] == "blocked"
    assert any(item["code"] == "unfinished_session" for item in unfinished_preview.json()["blockers"])

    assert db_count(database, database.WorkoutPlan) == 123


def test_commit_rejects_stale_preview(client):
    bundle = make_bundle(date_key="2026-09-04")
    preview = client.post("/api/migration/v24/preview", json=bundle).json()
    changed = client.post("/api/exercises", json={"name": "fingerprint change"})
    assert changed.status_code == 201
    payload = {
        **bundle,
        "source_sha256": preview["source_sha256"],
        "preview_hash": preview["preview_hash"],
        "affected_fingerprint": preview["affected_fingerprint"],
    }
    response = client.post("/api/migration/v24/commit", json=payload)
    assert response.status_code == 409
    assert response.json()["detail"]["status"] == "stale_preview"


def db_count(database, model):
    db = database.SessionLocal()
    try:
        return db.query(model).count()
    finally:
        db.close()
