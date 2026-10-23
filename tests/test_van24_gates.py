"""VAN-24 focused API and SQLite regression gates."""

from __future__ import annotations

from node_test_support import NODE

import hashlib
import json
import os
import sqlite3
import subprocess
from datetime import date
from pathlib import Path

from fastapi.testclient import TestClient
from sqlalchemy import event, text


APP_DIR = Path(__file__).resolve().parents[1]


def _digest(path, tables):
    with sqlite3.connect(path) as connection:
        rows = {
            name: connection.execute(f'SELECT * FROM "{name}" ORDER BY rowid').fetchall()
            for name in tables
        }
    return hashlib.sha256(json.dumps(rows, default=str, sort_keys=True).encode()).hexdigest()


def _exercise(client, name, *, reps="8", sets=1):
    response = client.post(
        "/api/exercises",
        json={"name": name, "category": "VAN-24", "defaultSets": sets, "defaultReps": reps},
    )
    assert response.status_code == 201, response.text
    return response.json()["id"]


def _plan(client, exercise_ids, date_key):
    response = client.post(
        "/api/plans/generate",
        json={"date": date_key, "exerciseIds": exercise_ids},
    )
    assert response.status_code == 200, response.text
    return response.json()["plan"]


def test_van24_g1_history_requires_backup_and_seed_failure_rolls_back(client, app_modules):
    database, main = app_modules
    exercise_id = _exercise(client, "VAN-24 G1 history")
    plan = _plan(client, [exercise_id], "2091-01-01")
    started = client.post("/api/session/start", json={"plan_id": plan["id"]})
    assert started.status_code == 200, started.text
    session_id = started.json()["session"]["id"]
    cancelled = client.post("/api/session/cancel", json={"session_id": session_id})
    assert cancelled.status_code == 200, cancelled.text

    db_path = database.DATABASE_PATH
    tables = ["workout_plans", "workout_sessions", "session_records", "workout_logs", "settings"]
    before = _digest(db_path, tables)
    refused = client.post(
        "/api/data/restore-defaults",
        json={"confirm": True, "backup": False},
    )
    assert refused.status_code == 409, refused.text
    assert refused.json()["detail"]["code"] == "BACKUP_REQUIRED_FOR_HISTORY"
    assert _digest(db_path, tables) == before

    with sqlite3.connect(db_path) as connection:
        connection.execute(
            "CREATE TRIGGER van24_seed_failure BEFORE INSERT ON exercises "
            "WHEN NEW.name='仰卧骨盆时钟' BEGIN SELECT RAISE(ABORT, 'van24 seed failure'); END"
        )
    failing_client = TestClient(main.app, raise_server_exceptions=False)
    before_failure = _digest(db_path, tables)
    failed = failing_client.post(
        "/api/data/restore-defaults",
        json={"confirm": True, "backup": True},
    )
    assert failed.status_code == 500, failed.text
    assert failed.json()["detail"]["code"] == "RESTORE_FAILED"
    assert _digest(db_path, tables) == before_failure
    with sqlite3.connect(db_path) as connection:
        assert connection.execute("PRAGMA foreign_key_check").fetchall() == []


def test_van24_g1_verified_backup_contains_completed_facts(client, app_modules):
    database, _main = app_modules
    exercise_id = _exercise(client, "VAN-24 G1 archived")
    plan = _plan(client, [exercise_id], "2091-01-02")
    started = client.post("/api/session/start", json={"plan_id": plan["id"]}).json()["session"]
    record = started["records"][0]
    assert client.post(
        "/api/session/update",
        json={"session_id": started["id"], "record_id": record["record_id"], "status": "completed", "sets_completed": 1},
    ).status_code == 200
    assert client.post("/api/session/complete", json={"session_id": started["id"]}).status_code == 200
    response = client.post("/api/data/restore-defaults", json={"confirm": True, "backup": True})
    assert response.status_code == 200, response.text
    backup = response.json()["backup"]
    assert backup["integrity"] == "ok"
    with sqlite3.connect(backup["path"]) as archived:
        assert archived.execute("SELECT COUNT(*) FROM workout_sessions WHERE id=?", (started["id"],)).fetchone()[0] == 1
        assert archived.execute("SELECT COUNT(*) FROM session_records WHERE session_id=?", (started["id"],)).fetchone()[0] == 1
        assert archived.execute("SELECT COUNT(*) FROM workout_logs WHERE session_id=?", (started["id"],)).fetchone()[0] == 1
        assert archived.execute("PRAGMA foreign_key_check").fetchall() == []
    with sqlite3.connect(database.DATABASE_PATH) as live:
        assert live.execute("SELECT COUNT(*) FROM workout_sessions").fetchone()[0] == 0
        assert live.execute("PRAGMA foreign_key_check").fetchall() == []


def test_van24_g2_referenced_delete_conflicts_but_template_only_cascades(client, app_modules):
    database, _main = app_modules
    referenced = _exercise(client, "VAN-24 G2 referenced")
    plan = _plan(client, [referenced], "2091-02-01")
    before = _digest(database.DATABASE_PATH, ["exercises", "workout_plans", "workout_exercises"])
    blocked = client.delete(f"/api/exercises/{referenced}")
    assert blocked.status_code == 409, blocked.text
    assert blocked.json()["detail"]["code"] == "EXERCISE_IN_USE"
    assert _digest(database.DATABASE_PATH, ["exercises", "workout_plans", "workout_exercises"]) == before

    free = _exercise(client, "VAN-24 G2 template-only")
    template = client.post("/api/templates", json={"name": "VAN-24 template", "exercise_ids": [free]})
    assert template.status_code == 201, template.text
    deleted = client.delete(f"/api/exercises/{free}")
    assert deleted.status_code == 200, deleted.text
    with sqlite3.connect(database.DATABASE_PATH) as connection:
        assert connection.execute("SELECT COUNT(*) FROM template_exercises WHERE exercise_id=?", (free,)).fetchone()[0] == 0
        assert connection.execute("PRAGMA foreign_key_check").fetchall() == []


def test_van24_g2_multiple_and_historical_references_are_reported(client):
    exercise_id = _exercise(client, "VAN-24 G2 many")
    first = _plan(client, [exercise_id], "2091-02-02")
    _plan(client, [exercise_id], "2091-02-03")
    started = client.post("/api/session/start", json={"plan_id": first["id"]}).json()["session"]
    assert client.post("/api/session/cancel", json={"session_id": started["id"]}).status_code == 200
    response = client.delete(f"/api/exercises/{exercise_id}")
    assert response.status_code == 409, response.text
    detail = response.json()["detail"]
    assert detail["plan_references"] == 2
    assert detail["history_references"] == 1


def test_van24_g3_repeated_occurrences_use_record_identity(client, app_modules):
    database, _main = app_modules
    first = _exercise(client, "VAN-24 G3 E1", sets=2)
    second = _exercise(client, "VAN-24 G3 E2")
    plan = _plan(client, [first, second, first, first], "2091-03-01")
    started = client.post("/api/session/start", json={"plan_id": plan["id"]})
    assert started.status_code == 200, started.text
    session = started.json()["session"]
    records = session["records"]
    assert [row["plan_item_order"] for row in records] == [1, 2, 3, 4]
    assert len({row["record_id"] for row in records}) == 4

    for row in records:
        updated = client.post(
            "/api/session/update",
            json={
                "session_id": session["id"],
                "record_id": row["record_id"],
                "status": "completed",
                "sets_completed": 2 if row["exercise_id"] == first else 1,
                "duration_seconds": row["plan_item_order"] * 10,
            },
        )
        assert updated.status_code == 200, updated.text

    ambiguous = client.post(
        "/api/session/update",
        json={"session_id": session["id"], "exercise_id": first, "status": "completed", "sets_completed": 2},
    )
    assert ambiguous.status_code == 409, ambiguous.text
    completed = client.post("/api/session/complete", json={"session_id": session["id"]})
    assert completed.status_code == 200, completed.text
    with sqlite3.connect(database.DATABASE_PATH) as connection:
        rows = connection.execute(
            "SELECT exercise_id, plan_item_order, sets_completed FROM session_records WHERE session_id=? ORDER BY plan_item_order",
            (session["id"],),
        ).fetchall()
        assert rows == [(first, 1, 2), (second, 2, 1), (first, 3, 2), (first, 4, 2)]
        assert connection.execute("PRAGMA foreign_key_check").fetchall() == []


def test_van24_g3_legacy_gapped_sort_migrates_and_hydrates(client, app_modules):
    database, _main = app_modules
    db_path = database.DATABASE_PATH
    with sqlite3.connect(db_path) as connection:
        plan_id = connection.execute("SELECT COALESCE(MAX(id),0)+1 FROM workout_plans").fetchone()[0]
        session_id = connection.execute("SELECT COALESCE(MAX(id),0)+1 FROM workout_sessions").fetchone()[0]
        exercise_id = connection.execute("SELECT id FROM exercises ORDER BY id LIMIT 1").fetchone()[0]
        connection.execute(
            "INSERT INTO workout_plans(id,plan_date,title,is_training_day,focus,notes,created_at) VALUES(?,?,?,?,?,?,?)",
            (plan_id, "2091-03-02", "legacy", 1, "legacy", "", "2020-01-01 00:00:00"),
        )
        connection.execute(
            "INSERT INTO workout_exercises(plan_id,exercise_id,sort_order,name,description,sets,reps,created_at) "
            "VALUES(?,?,?,?,?,?,?,?)",
            (plan_id, exercise_id, 10, "legacy", "", 1, 8, "2020-01-01 00:00:00"),
        )
        connection.execute(
            "INSERT INTO workout_sessions(id,plan_id,status,created_at) VALUES(?,?,?,?)",
            (session_id, plan_id, "completed", "2020-01-01 00:00:00"),
        )
        connection.execute("DROP TABLE session_records")
        connection.execute(
            """CREATE TABLE session_records(
                id INTEGER PRIMARY KEY, session_id INTEGER NOT NULL, exercise_id INTEGER,
                status VARCHAR(20) NOT NULL, sets_completed INTEGER, reps_completed VARCHAR(40),
                duration_seconds INTEGER, notes TEXT, completed_at DATETIME,
                created_at DATETIME NOT NULL, updated_at DATETIME,
                CONSTRAINT uq_session_records_session_exercise UNIQUE(session_id, exercise_id),
                CONSTRAINT ck_session_records_status CHECK(status IN ('pending','completed','skipped')),
                FOREIGN KEY(session_id) REFERENCES workout_sessions(id),
                FOREIGN KEY(exercise_id) REFERENCES exercises(id))"""
        )
        connection.execute(
            "INSERT INTO session_records VALUES(?,?,?,?,?,?,?,?,?,?,?)",
            (session_id, session_id, exercise_id, "completed", 1, None, 12, "", "2020-01-01 00:00:00", "2020-01-01 00:00:00", None),
        )
        connection.commit()
    database.create_tables()
    with sqlite3.connect(db_path) as connection:
        assert connection.execute("SELECT id,plan_item_order FROM session_records WHERE session_id=?", (session_id,)).fetchone() == (session_id, 10)
        assert connection.execute("PRAGMA foreign_key_check").fetchall() == []
    with database.SessionLocal() as db:
        assert db.execute(text("PRAGMA foreign_keys")).scalar() == 1
    current = client.get(f"/api/session/current?plan_id={plan_id}&include_completed=true")
    assert current.status_code == 200, current.text
    assert current.json()["session"]["records"][0]["plan_item_order"] == 10


def test_van24_g3_v24_session_only_import_uses_existing_gapped_order(client, app_modules):
    database, _main = app_modules
    with database.SessionLocal() as db:
        exercises = db.query(database.Exercise).order_by(database.Exercise.id).limit(2).all()
        plan = database.WorkoutPlan(
            plan_date=date(2091, 3, 3), title="existing gap", is_training_day=True,
            focus="gap", notes="",
        )
        db.add(plan)
        db.flush()
        for exercise, order in zip(exercises, (10, 20)):
            db.add(database.WorkoutExercise(
                plan_id=plan.id, exercise_id=exercise.id, sort_order=order,
                name=exercise.name, description=exercise.notes or "", sets=1, reps=8,
            ))
        db.commit()
        plan_id = plan.id
        names = [exercise.name for exercise in exercises]
    bundle = {
        "format": "qingdong-training-backup",
        "version": 1,
        "trainingState": {
            "version": 1,
            "data": {
                "calendarPlans": {},
                "customTrainingPlans": {},
                "dailySessions": {
                    "2091-03-03": {
                        "items": [{"name": names[0], "spec": "1 组"}, {"name": names[1], "spec": "1 组"}],
                        "started": True,
                        "done": True,
                        "stepIndex": 1,
                    }
                },
            },
        },
    }
    preview = client.post("/api/migration/v24/preview", json=bundle)
    assert preview.status_code == 200 and preview.json()["status"] == "ready", preview.text
    controls = preview.json()
    committed = client.post(
        "/api/migration/v24/commit",
        json={**bundle, "source_sha256": controls["source_sha256"], "preview_hash": controls["preview_hash"], "affected_fingerprint": controls["affected_fingerprint"]},
    )
    assert committed.status_code == 200, committed.text
    current = client.get(f"/api/session/current?plan_id={plan_id}&include_completed=true")
    assert current.status_code == 200, current.text
    assert [row["plan_item_order"] for row in current.json()["session"]["records"]] == [10, 20]


def test_van24_g3_migration_sql_failure_rolls_back_schema_and_retries(app_modules):
    database, _main = app_modules
    db_path = database.DATABASE_PATH
    with sqlite3.connect(db_path) as connection:
        plan_id = connection.execute("SELECT id FROM workout_plans ORDER BY id LIMIT 1").fetchone()[0]
        session_id = connection.execute("SELECT COALESCE(MAX(id),0)+1 FROM workout_sessions").fetchone()[0]
        exercise_id = connection.execute("SELECT id FROM exercises ORDER BY id LIMIT 1").fetchone()[0]
        connection.execute(
            "INSERT INTO workout_sessions(id,plan_id,status,created_at) VALUES(?,?,?,?)",
            (session_id, plan_id, "completed", "2020-01-01 00:00:00"),
        )
        connection.execute("DROP TABLE session_records")
        connection.execute(
            """CREATE TABLE session_records(
                id INTEGER PRIMARY KEY, session_id INTEGER NOT NULL, exercise_id INTEGER,
                status VARCHAR(20) NOT NULL, sets_completed INTEGER, reps_completed VARCHAR(40),
                duration_seconds INTEGER, notes TEXT, completed_at DATETIME,
                created_at DATETIME NOT NULL, updated_at DATETIME,
                CONSTRAINT uq_session_records_session_exercise UNIQUE(session_id, exercise_id),
                FOREIGN KEY(session_id) REFERENCES workout_sessions(id),
                FOREIGN KEY(exercise_id) REFERENCES exercises(id))"""
        )
        connection.execute(
            "INSERT INTO session_records VALUES(?,?,?,?,?,?,?,?,?,?,?)",
            (99, session_id, exercise_id, "corrupt", 1, None, 1, "keep", None, "2020-01-01 00:00:00", None),
        )
        connection.commit()
    try:
        database.create_tables()
    except Exception:
        pass
    else:
        raise AssertionError("corrupt legacy status unexpectedly migrated")
    with sqlite3.connect(db_path) as connection:
        columns = {row[1] for row in connection.execute("PRAGMA table_info(session_records)")}
        assert "plan_item_order" not in columns
        assert connection.execute("SELECT status FROM session_records WHERE id=99").fetchone() == ("corrupt",)
        assert connection.execute("PRAGMA foreign_key_check").fetchall() == []
    with database.SessionLocal() as db:
        assert db.execute(text("PRAGMA foreign_keys")).scalar() == 1
    with sqlite3.connect(db_path) as connection:
        connection.execute("UPDATE session_records SET status='completed' WHERE id=99")
        connection.commit()
    database.create_tables()
    with sqlite3.connect(db_path) as connection:
        assert connection.execute("SELECT status,plan_item_order FROM session_records WHERE id=99").fetchone()[0] == "completed"
        assert connection.execute("PRAGMA foreign_key_check").fetchall() == []


def test_van24_g4_only_matching_standalone_replay_is_idempotent(client, app_modules):
    database, _main = app_modules
    exercise_id = _exercise(client, "VAN-24 G4")
    plan = _plan(client, [exercise_id], "2091-04-01")
    payload = {"date": "2091-04-01", "status": "done", "completed": ["VAN-24 G4"], "notes": "g4"}
    first = client.post("/api/training/complete", json=payload)
    replay = client.post("/api/training/complete", json=payload)
    assert first.status_code == 200 and first.json()["status"] == "recorded"
    assert replay.status_code == 200 and replay.json()["status"] == "already_recorded"

    with sqlite3.connect(database.DATABASE_PATH) as connection:
        connection.execute(
            "UPDATE workout_logs SET plan_action_fingerprint='obsolete' WHERE id=?",
            (first.json()["log_id"],),
        )
    stale = client.post("/api/training/complete", json=payload)
    assert stale.status_code == 409, stale.text
    with sqlite3.connect(database.DATABASE_PATH) as connection:
        assert connection.execute("SELECT COUNT(*) FROM workout_logs WHERE plan_id=?", (plan["id"],)).fetchone()[0] == 1


def test_van24_g4_inconsistent_status_fact_is_not_completion(client, app_modules):
    database, main = app_modules
    exercise_id = _exercise(client, "VAN-24 G4 status")
    plan = _plan(client, [exercise_id], "2091-04-03")
    with database.SessionLocal() as db:
        fingerprint = main._plan_action_fingerprint(db.get(database.WorkoutPlan, plan["id"]))
        db.add(database.WorkoutLog(
            plan_id=plan["id"],
            plan_action_fingerprint=fingerprint,
            log_date=date(2091, 4, 3),
            action="completed",
            status="skipped",
            notes="inconsistent",
        ))
        db.commit()
    before = _digest(database.DATABASE_PATH, ["workout_logs", "workout_sessions", "session_records"])
    response = client.post(
        "/api/training/complete",
        json={"date": "2091-04-03", "status": "done", "completed": ["VAN-24 G4 status"]},
    )
    assert response.status_code == 409, response.text
    assert _digest(database.DATABASE_PATH, ["workout_logs", "workout_sessions", "session_records"]) == before


def test_van24_g4_real_race_rejects_stale_and_nonmatching_unique(client, app_modules):
    database, main = app_modules
    exercise_id = _exercise(client, "VAN-24 G4 race")
    plan = _plan(client, [exercise_id], "2091-04-02")
    payload = {"date": "2091-04-02", "status": "done", "completed": ["VAN-24 G4 race"], "notes": "race"}
    with database.SessionLocal() as db:
        fingerprint = main._plan_action_fingerprint(db.get(database.WorkoutPlan, plan["id"]))

    with sqlite3.connect(database.DATABASE_PATH) as connection:
        connection.execute("CREATE UNIQUE INDEX van24_unrelated_notes ON workout_logs(notes)")

    def peer_writer(_connection, _cursor, statement, _parameters, _context, _executemany):
        if statement.startswith("INSERT INTO workout_logs"):
            with sqlite3.connect(database.DATABASE_PATH) as peer:
                peer.execute(
                    "INSERT INTO workout_logs(plan_id,session_id,plan_action_fingerprint,log_date,action,status,notes) "
                    "VALUES (?,NULL,?,'2091-04-02','completed','completed','race')",
                    (plan["id"], fingerprint),
                )

    event.listen(database.engine, "before_cursor_execute", peer_writer)
    try:
        response = TestClient(main.app, raise_server_exceptions=False).post("/api/training/complete", json=payload)
    finally:
        try:
            event.remove(database.engine, "before_cursor_execute", peer_writer)
        except Exception:
            pass
    assert response.status_code == 500, response.text
    with sqlite3.connect(database.DATABASE_PATH) as connection:
        assert connection.execute("SELECT COUNT(*) FROM workout_logs WHERE notes='race'").fetchone()[0] == 1


def test_van24_g4_active_legacy_check_failure_rolls_back_terminal_claim(client, app_modules):
    database, main = app_modules
    exercise_id = _exercise(client, "VAN-24 G4 active")
    plan = _plan(client, [exercise_id], "2091-04-04")
    started = client.post("/api/session/start", json={"plan_id": plan["id"]}).json()["session"]
    record_id = started["records"][0]["record_id"]
    assert client.post(
        "/api/session/update",
        json={"session_id": started["id"], "record_id": record_id, "status": "completed", "sets_completed": 1},
    ).status_code == 200
    with database.SessionLocal() as db:
        session = db.get(database.WorkoutSession, started["id"])
        db.add(database.WorkoutLog(
            plan_id=plan["id"],
            session_id=started["id"],
            plan_action_fingerprint=session.plan_action_fingerprint,
            log_date=date(2091, 4, 4),
            action="completed",
            status="completed",
            notes="peer existing fact",
        ))
        db.commit()
    with sqlite3.connect(database.DATABASE_PATH) as connection:
        connection.execute(
            "CREATE TRIGGER van24_active_check BEFORE INSERT ON workout_logs "
            "WHEN NEW.session_id IS NOT NULL BEGIN "
            "INSERT INTO workout_logs(plan_id,log_date,action,status) VALUES(NEW.plan_id,NEW.log_date,'bad','bad'); END"
        )
    safe_client = TestClient(main.app, raise_server_exceptions=False)
    before = _digest(database.DATABASE_PATH, ["workout_sessions", "workout_logs", "session_records"])
    response = safe_client.post(
        "/api/training/complete",
        json={"date": "2091-04-04", "status": "done", "completed": ["VAN-24 G4 active"]},
    )
    assert response.status_code == 500, response.text
    assert _digest(database.DATABASE_PATH, ["workout_sessions", "workout_logs", "session_records"]) == before
    with database.SessionLocal() as db:
        assert db.get(database.WorkoutSession, started["id"]).status == "in_progress"


def test_van24_g5_scalar_reps_and_display_ranges(client, app_modules):
    database, _main = app_modules
    for index, value in enumerate(("8", "12", "8次", "6次/侧"), 1):
        exercise_id = _exercise(client, f"VAN-24 G5 valid {index}", reps=value)
        plan = _plan(client, [exercise_id], f"2091-05-{index:02d}")
        expected = {"8": 8, "12": 12, "8次": 8, "6次/侧": 6}[value]
        assert plan["items"][0]["reps"] == expected

    for index, value in enumerate(("8-12", "8 - 12", "8–12", "8—12", "0", "-8", "12-8", "abc", "10001"), 1):
        exercise_id = _exercise(client, f"VAN-24 G5 invalid {index}", reps=value)
        response = client.post("/api/plans/generate", json={"date": f"2091-06-{index:02d}", "exerciseIds": [exercise_id]})
        assert response.status_code == 422, (value, response.text)

    display = _exercise(client, "VAN-24 G5 display")
    implicit = client.put(
        "/api/plans/by-date/2091-07-01",
        json={"date": "2091-07-01", "items": [{"exercise_id": display, "spec": "2 组 · 8-12 次"}]},
    )
    assert implicit.status_code == 422, implicit.text
    saved = client.put(
        "/api/plans/by-date/2091-07-01",
        json={"date": "2091-07-01", "items": [{"exercise_id": display, "reps": 8, "spec": "2 组 · 8-12 次"}]},
    )
    assert saved.status_code == 200, saved.text
    item = saved.json()["plan"]["items"][0]
    assert item["spec"] == "2 组 · 8-12 次"
    assert item["reps"] == 8
    dated = client.put(
        "/api/plans/by-date/2091-07-02",
        json={"date": "2091-07-02", "items": [{"exercise_id": display, "spec": "记录 2036-12-29 · 8 次"}]},
    )
    assert dated.status_code == 200, dated.text
    assert dated.json()["plan"]["items"][0]["reps"] == 8
    adjacent = client.put(
        "/api/plans/by-date/2091-07-12",
        json={"date": "2091-07-12", "items": [{"exercise_id": display, "spec": "3组12次"}]},
    )
    assert adjacent.status_code == 200, adjacent.text
    assert adjacent.json()["plan"]["items"][0]["reps"] == 12
    for index, spec in enumerate(("2组8-12次", "做-8次"), 13):
        invalid = client.put(
            f"/api/plans/by-date/2091-07-{index:02d}",
            json={"date": f"2091-07-{index:02d}", "items": [{"exercise_id": display, "spec": spec}]},
        )
        assert invalid.status_code == 422, (spec, invalid.text)
    for index, spec in enumerate(("-8 次", "0 次", "100000000000000000000 次"), 3):
        invalid = client.put(
            f"/api/plans/by-date/2091-07-{index:02d}",
            json={"date": f"2091-07-{index:02d}", "items": [{"exercise_id": display, "spec": spec}]},
        )
        assert invalid.status_code == 422, (spec, invalid.text)
    with sqlite3.connect(database.DATABASE_PATH) as connection:
        assert connection.execute("PRAGMA foreign_key_check").fetchall() == []


def test_van24_formal_production_dom_occurrence_and_range(tmp_path):
    env = {
        **os.environ,
        "WORKOUT_DB_PATH": str(tmp_path / "van24-dom.sqlite"),
        "WORKOUT_DISABLE_SEED": "1",
    }
    result = subprocess.run(
        [NODE, "tests/van24_real_dom_behavior.js"],
        cwd=APP_DIR,
        env=env,
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert result.returncode == 0, result.stderr + result.stdout
    assert '"PASS":true' in result.stdout.replace(" ", "")


def test_van24_formal_saved_scheme_rejects_invalid_implicit_reps():
    env = {
        **os.environ,
    }
    result = subprocess.run(
        [NODE, "tests/van24_saved_scheme_dom_behavior.js"],
        cwd=APP_DIR,
        env=env,
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert result.returncode == 0, result.stderr + result.stdout
    assert '"PASS":true' in result.stdout.replace(" ", "")


def test_van24_v24_migration_blocks_implicit_range_before_commit(client, app_modules):
    database, _main = app_modules
    _exercise(client, "VAN-24 migration range", reps="8")
    bundle = {
        "format": "qingdong-training-backup",
        "version": 1,
        "trainingState": {
            "version": 1,
            "data": {
                "calendarPlans": {
                    "2091-08-01": {
                        "title": "range",
                        "status": "planned",
                        "items": [{"name": "VAN-24 migration range", "spec": "2 组 · 8-12 次"}],
                    }
                },
                "customTrainingPlans": {},
                "dailySessions": {},
            },
        },
    }
    before = _digest(database.DATABASE_PATH, ["workout_plans", "workout_exercises", "workout_sessions", "session_records", "workout_logs"])
    preview = client.post("/api/migration/v24/preview", json=bundle)
    assert preview.status_code == 200
    assert preview.json()["status"] == "blocked"
    assert any(item["code"] == "invalid_reps" for item in preview.json()["blockers"])
    assert _digest(database.DATABASE_PATH, ["workout_plans", "workout_exercises", "workout_sessions", "session_records", "workout_logs"]) == before
