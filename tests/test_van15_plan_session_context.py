"""VAN-15 plan/session context protection checks.

Every API case uses the isolated ``app_modules`` database fixture.  The
frontend case evaluates the tracked v25 session binding function directly so
the browser cannot accept a session response for another plan.
"""
from __future__ import annotations

import subprocess
import os
import sys
from pathlib import Path


APP_DIR = Path(__file__).resolve().parents[1]


def _create_exercise(client, name: str, sets: int = 1) -> int:
    response = client.post(
        "/api/exercises",
        json={
            "name": name,
            "category": "VAN-15",
            "difficulty": "低",
            "defaultSets": sets,
            "defaultReps": "8次",
        },
    )
    assert response.status_code == 201, response.text
    return response.json()["id"]


def _create_plan(client, date_token: str, exercise_id: int) -> dict:
    response = client.post(
        "/api/plans/generate",
        json={
            "date": date_token,
            "title": "VAN-15 上下文计划",
            "theme": "上下文一致性",
            "exerciseIds": [exercise_id],
        },
    )
    assert response.status_code == 200, response.text
    return response.json()["plan"]


def test_active_session_locks_action_snapshot_across_plan_write_routes(client, app_modules):
    database, _main = app_modules
    first_id = _create_exercise(client, "VAN-15 原动作")
    second_id = _create_exercise(client, "VAN-15 新动作")
    plan = _create_plan(client, "2031-01-15", first_id)

    started = client.post("/api/session/start", json={"plan_id": plan["id"]})
    assert started.status_code == 200, started.text
    session_id = started.json()["session"]["id"]
    record = started.json()["session"]["records"][0]
    progressed = client.post(
        "/api/session/update",
        json={
            "session_id": session_id,
            "exercise_id": first_id,
            "status": "completed",
            "sets_completed": 1,
        },
    )
    assert progressed.status_code == 200, progressed.text

    replacement = {
        "date": "2031-01-15",
        "title": "VAN-15 新计划",
        "is_training_day": True,
        "focus": "切换",
        "items": [{"exercise_id": second_id, "sets": 1, "reps": 8}],
    }
    for response in (
        client.put(f"/api/plans/{plan['id']}", json={"exercise_ids": [second_id]}),
        client.put(f"/api/plans/by-date/{replacement['date']}", json=replacement),
        client.post(
            "/api/plans/generate",
            json={
                "date": replacement["date"],
                "title": replacement["title"],
                "theme": replacement["focus"],
                "exerciseIds": [second_id],
            },
        ),
        client.post(
            "/api/plans/import",
            json={"plans": [replacement], "replace_months": True},
        ),
    ):
        assert response.status_code == 409, response.text
        assert "活跃训练会话" in str(response.json()["detail"])

    # Metadata does not alter the action context and remains editable.
    renamed = client.put(
        f"/api/plans/{plan['id']}",
        json={"title": "训练中保留上下文"},
    )
    assert renamed.status_code == 200, renamed.text
    assert renamed.json()["title"] == "训练中保留上下文"

    # The browser's canonical save includes the unchanged action snapshot; it
    # must remain a safe metadata round-trip while the session is active.
    stable = client.get(f"/api/plans?date={replacement['date']}").json()["plans"][0]
    canonical_roundtrip = client.put(
        f"/api/plans/by-date/{replacement['date']}",
        json={
            "date": replacement["date"],
            "title": "训练中 canonical 回读",
            "is_training_day": True,
            "focus": stable["theme"],
            "notes": stable["notes"],
            "template_id": stable["template_id"],
            "items": stable["items"],
        },
    )
    assert canonical_roundtrip.status_code == 200, canonical_roundtrip.text

    current = client.get(f"/api/session/current?plan_id={plan['id']}")
    assert current.status_code == 200
    assert current.json()["session"]["id"] == session_id
    assert current.json()["plan"]["items"][0]["exercise_id"] == first_id
    assert current.json()["session"]["records"][0]["exercise_id"] == record["exercise_id"] == first_id

    db = database.SessionLocal()
    try:
        stored_plan = db.query(database.WorkoutPlan).filter_by(id=plan["id"]).one()
        stored_session = db.query(database.WorkoutSession).filter_by(id=session_id).one()
        stored_records = db.query(database.SessionRecord).filter_by(session_id=session_id).all()
        assert [item.exercise_id for item in stored_plan.exercises] == [first_id]
        assert stored_session.plan_id == stored_plan.id
        assert [item.exercise_id for item in stored_records] == [first_id]
    finally:
        db.close()


def test_explicit_cancel_then_switch_rebuilds_records_and_items(client, app_modules):
    database, _main = app_modules
    first_id = _create_exercise(client, "VAN-15 旧动作")
    second_id = _create_exercise(client, "VAN-15 换后动作")
    plan = _create_plan(client, "2031-01-16", first_id)

    first_session = client.post("/api/session/start", json={"plan_id": plan["id"]})
    assert first_session.status_code == 200, first_session.text
    first_session_id = first_session.json()["session"]["id"]
    cancelled = client.post("/api/session/cancel", json={"session_id": first_session_id})
    assert cancelled.status_code == 200, cancelled.text

    switched = client.put(
        f"/api/plans/{plan['id']}",
        json={"exercise_ids": [second_id], "is_training_day": True},
    )
    assert switched.status_code == 200, switched.text
    assert [item["exercise_id"] for item in switched.json()["items"]] == [second_id]

    second_session = client.post("/api/session/start", json={"plan_id": plan["id"]})
    assert second_session.status_code == 200, second_session.text
    second_session_id = second_session.json()["session"]["id"]
    assert second_session_id != first_session_id
    assert [record["exercise_id"] for record in second_session.json()["session"]["records"]] == [second_id]

    current = client.get(f"/api/session/current?plan_id={plan['id']}")
    assert current.json()["plan"]["items"][0]["exercise_id"] == second_id
    assert current.json()["session"]["records"][0]["exercise_id"] == second_id

    # A new SQLAlchemy connection sees the same plan/session context, which is
    # the persistence boundary used by a service restart.
    database.engine.dispose()
    db = database.SessionLocal()
    try:
        persisted = db.query(database.WorkoutSession).filter_by(id=second_session_id).one()
        persisted_plan = db.query(database.WorkoutPlan).filter_by(id=plan["id"]).one()
        persisted_record = db.query(database.SessionRecord).filter_by(session_id=second_session_id).one()
        assert persisted.plan_id == persisted_plan.id
        assert persisted_record.exercise_id == second_id
        assert persisted_plan.exercises[0].exercise_id == second_id
    finally:
        db.close()


def test_template_delete_is_blocked_while_its_plan_session_is_active(client):
    exercise_id = _create_exercise(client, "VAN-15 模板动作")
    template = client.post(
        "/api/templates",
        json={"name": "VAN-15 模板", "exercise_ids": [exercise_id]},
    )
    assert template.status_code == 201, template.text
    plan = _create_plan(client, "2031-01-17", exercise_id)
    bound = client.put(f"/api/plans/{plan['id']}", json={"template_id": template.json()["id"]})
    assert bound.status_code == 200, bound.text
    started = client.post("/api/session/start", json={"plan_id": plan["id"]})
    assert started.status_code == 200, started.text

    deleted = client.delete(f"/api/templates/{template.json()['id']}")
    assert deleted.status_code == 409, deleted.text
    assert "活跃训练会话" in str(deleted.json()["detail"])


def test_existing_mismatch_is_blocked_and_cancel_recovery_preserves_partial_facts(client, app_modules):
    database, _main = app_modules
    first_id = _create_exercise(client, "VAN-15 错位旧动作", sets=2)
    second_id = _create_exercise(client, "VAN-15 错位新动作", sets=1)
    plan = _create_plan(client, "2031-01-18", first_id)
    started = client.post("/api/session/start", json={"plan_id": plan["id"]})
    assert started.status_code == 200, started.text
    session_id = started.json()["session"]["id"]

    partial = client.post(
        "/api/session/update",
        json={
            "session_id": session_id,
            "exercise_id": first_id,
            "status": "pending",
            "sets_completed": 1,
            "duration_seconds": 17,
        },
    )
    assert partial.status_code == 200, partial.text

    # Simulate the already-corrupt SQLite state found in the field: the plan
    # row was replaced with B while the active session facts still point to A.
    db = database.SessionLocal()
    try:
        item = db.query(database.WorkoutExercise).filter_by(plan_id=plan["id"]).one()
        item.exercise_id = second_id
        item.name = "VAN-15 错位新动作"
        db.commit()
    finally:
        db.close()

    current = client.get(f"/api/session/current?plan_id={plan['id']}")
    assert current.status_code == 409, current.text
    assert current.json()["detail"]["code"] == "SESSION_PLAN_CONTEXT_MISMATCH"
    assert current.json()["detail"]["session_id"] == session_id

    resumed = client.post("/api/session/start", json={"plan_id": plan["id"]})
    assert resumed.status_code == 409, resumed.text
    wrong_update = client.post(
        "/api/session/update",
        json={"session_id": session_id, "exercise_id": second_id, "status": "completed", "sets_completed": 1},
    )
    assert wrong_update.status_code == 409, wrong_update.text
    completed = client.post("/api/session/complete", json={"session_id": session_id})
    assert completed.status_code == 409, completed.text
    summary = client.get(f"/api/session/{session_id}/summary")
    assert summary.status_code == 409, summary.text

    # Reopen the same SQLite file through a fresh process before using the
    # recovery path; no records are remapped or discarded across restart.
    database.engine.dispose()
    probe = subprocess.run(
        [
            sys.executable,
            "-c",
            """
import os
import sqlite3
path = os.environ['WORKOUT_DB_PATH']
session_id = int(os.environ['VAN15_SESSION_ID'])
with sqlite3.connect(path) as connection:
    row = connection.execute(
        'SELECT status, exercise_id, sets_completed, duration_seconds FROM session_records WHERE session_id = ?',
        (session_id,),
    ).fetchone()
assert row[0] == 'pending' and row[2] == 1 and row[3] == 17
""",
        ],
        capture_output=True,
        text=True,
        env={**os.environ, "VAN15_SESSION_ID": str(session_id)},
        cwd=APP_DIR,
        timeout=30,
    )
    assert probe.returncode == 0, probe.stderr or probe.stdout
    cancelled = client.post("/api/session/cancel", json={"session_id": session_id})
    assert cancelled.status_code == 200, cancelled.text
    assert cancelled.json()["recovery"]["status"] == "context_preserved"

    db = database.SessionLocal()
    try:
        old_session = db.query(database.WorkoutSession).filter_by(id=session_id).one()
        old_record = db.query(database.SessionRecord).filter_by(session_id=session_id).one()
        current_plan = db.query(database.WorkoutPlan).filter_by(id=plan["id"]).one()
        assert old_session.status == "cancelled"
        assert old_record.exercise_id == first_id
        assert old_record.sets_completed == 1
        assert old_record.duration_seconds == 17
        assert current_plan.exercises[0].exercise_id == second_id
    finally:
        db.close()

    replacement_start = client.post("/api/session/start", json={"plan_id": plan["id"]})
    assert replacement_start.status_code == 200, replacement_start.text
    assert replacement_start.json()["status"] == "started"
    replacement_session_id = replacement_start.json()["session"]["id"]
    assert replacement_session_id != session_id
    assert [row["exercise_id"] for row in replacement_start.json()["session"]["records"]] == [second_id]
    current_after = client.get(f"/api/session/current?plan_id={plan['id']}")
    assert current_after.status_code == 200, current_after.text
    assert current_after.json()["session"]["records"][0]["exercise_id"] == second_id
    assert current_after.json()["plan"]["items"][0]["exercise_id"] == second_id


def test_active_session_with_empty_plan_snapshot_is_blocked_and_recoverable(client, app_modules):
    database, _main = app_modules
    exercise_id = _create_exercise(client, "VAN-15 空快照动作")
    plan = _create_plan(client, "2031-01-22", exercise_id)
    started = client.post("/api/session/start", json={"plan_id": plan["id"]})
    assert started.status_code == 200, started.text
    session_id = started.json()["session"]["id"]

    db = database.SessionLocal()
    try:
        db.query(database.WorkoutExercise).filter_by(plan_id=plan["id"]).delete()
        db.commit()
    finally:
        db.close()

    current = client.get(f"/api/session/current?plan_id={plan['id']}")
    assert current.status_code == 409, current.text
    assert current.json()["detail"]["reason"] == "计划动作快照为空但训练记录仍存在"
    resumed = client.post("/api/session/start", json={"plan_id": plan["id"]})
    assert resumed.status_code == 409, resumed.text
    blocked_update = client.post(
        "/api/session/update",
        json={"session_id": session_id, "exercise_id": exercise_id, "status": "completed", "sets_completed": 1},
    )
    assert blocked_update.status_code == 409, blocked_update.text

    cancelled = client.post("/api/session/cancel", json={"session_id": session_id})
    assert cancelled.status_code == 200, cancelled.text
    assert cancelled.json()["recovery"]["status"] == "context_preserved"


def test_completed_history_mismatch_is_not_current_plan_completion_and_new_session_can_finish(client, app_modules):
    database, _main = app_modules
    first_id = _create_exercise(client, "VAN-15 已完成旧动作")
    second_id = _create_exercise(client, "VAN-15 新计划动作")
    plan = _create_plan(client, "2031-01-19", first_id)
    started = client.post("/api/session/start", json={"plan_id": plan["id"]})
    assert started.status_code == 200, started.text
    session_id = started.json()["session"]["id"]
    record_id = started.json()["session"]["records"][0]["exercise_id"]
    updated = client.post(
        "/api/session/update",
        json={"session_id": session_id, "exercise_id": record_id, "status": "completed", "sets_completed": 1, "duration_seconds": 31},
    )
    assert updated.status_code == 200, updated.text
    completed = client.post("/api/session/complete", json={"session_id": session_id})
    assert completed.status_code == 200, completed.text

    # This is the legacy completed A -> current plan B state from the review.
    switched = client.put(
        f"/api/plans/{plan['id']}",
        json={"exercise_ids": [second_id], "is_training_day": True},
    )
    assert switched.status_code == 200, switched.text

    current = client.get(f"/api/session/current?plan_id={plan['id']}&include_completed=true")
    assert current.status_code == 200, current.text
    assert current.json()["session"] is None
    assert current.json()["history_conflict"]["code"] == "COMPLETED_SESSION_PLAN_CONTEXT_MISMATCH"
    assert current.json()["history_conflict"]["can_cancel"] is False

    summary = client.get(f"/api/session/{session_id}/summary")
    assert summary.status_code == 200, summary.text
    assert summary.json()["history_conflict"]["code"] == "COMPLETED_SESSION_PLAN_CONTEXT_MISMATCH"
    assert summary.json()["summary"]["completed_exercises"] == 1
    assert summary.json()["summary"]["duration_seconds"] == 31
    cannot_cancel = client.post("/api/session/cancel", json={"session_id": session_id})
    assert cannot_cancel.status_code == 422, cannot_cancel.text

    detail = client.get("/api/stats/month/detail", params={"month": "2031-01"})
    assert detail.status_code == 200, detail.text
    day = next(row for row in detail.json()["days"] if row["date"] == "2031-01-19")
    assert day["status"] == "planned"
    month_before = client.get("/api/stats/month", params={"month": "2031-01"})
    assert month_before.status_code == 200, month_before.text
    assert month_before.json()["completed"] == 1
    assert month_before.json()["duration_seconds"] == 31
    assert month_before.json()["completion_rate"] == 0.0

    # The historical A log remains intact, while a new B session can create a
    # distinct session-backed log for the same plan/date.
    replacement = client.post("/api/session/start", json={"plan_id": plan["id"]})
    assert replacement.status_code == 200, replacement.text
    replacement_id = replacement.json()["session"]["id"]
    assert replacement.json()["status"] == "started"
    assert replacement.json()["session"]["records"][0]["exercise_id"] == second_id
    replacement_update = client.post(
        "/api/session/update",
        json={"session_id": replacement_id, "exercise_id": second_id, "status": "completed", "sets_completed": 1},
    )
    assert replacement_update.status_code == 200, replacement_update.text
    replacement_complete = client.post("/api/session/complete", json={"session_id": replacement_id})
    assert replacement_complete.status_code == 200, replacement_complete.text

    db = database.SessionLocal()
    try:
        logs = db.query(database.WorkoutLog).filter_by(plan_id=plan["id"], action="completed").order_by(database.WorkoutLog.id).all()
        assert len(logs) == 2
        assert [row.session_id for row in logs] == [session_id, replacement_id]
        old_record = db.query(database.SessionRecord).filter_by(session_id=session_id).one()
        new_record = db.query(database.SessionRecord).filter_by(session_id=replacement_id).one()
        assert old_record.exercise_id == first_id
        assert new_record.exercise_id == second_id
    finally:
        db.close()

    current_after = client.get(f"/api/session/current?plan_id={plan['id']}&include_completed=true")
    assert current_after.status_code == 200, current_after.text
    assert current_after.json()["session"]["id"] == replacement_id
    assert current_after.json()["session"]["status"] == "completed"
    assert current_after.json()["plan"]["items"][0]["exercise_id"] == second_id
    detail_after = client.get("/api/stats/month/detail", params={"month": "2031-01"})
    assert detail_after.status_code == 200, detail_after.text
    day_after = next(row for row in detail_after.json()["days"] if row["date"] == "2031-01-19")
    assert day_after["status"] == "completed"
    month_after = client.get("/api/stats/month", params={"month": "2031-01"})
    assert month_after.status_code == 200, month_after.text
    assert month_after.json()["completed"] == 2
    assert month_after.json()["duration_seconds"] == 31
    assert month_after.json()["completion_rate"] == 100.0


def test_mismatch_cancel_without_notes_preserves_session_and_record_facts(client, app_modules):
    database, _main = app_modules
    first_id = _create_exercise(client, "VAN-15 备注旧动作", sets=2)
    second_id = _create_exercise(client, "VAN-15 备注新动作")
    plan = _create_plan(client, "2031-01-20", first_id)
    started = client.post("/api/session/start", json={"plan_id": plan["id"]})
    assert started.status_code == 200, started.text
    session_id = started.json()["session"]["id"]
    partial = client.post(
        "/api/session/update",
        json={
            "session_id": session_id,
            "exercise_id": first_id,
            "status": "pending",
            "sets_completed": 1,
            "duration_seconds": 19,
            "notes": "动作事实备注",
        },
    )
    assert partial.status_code == 200, partial.text
    db = database.SessionLocal()
    try:
        session = db.query(database.WorkoutSession).filter_by(id=session_id).one()
        session.notes = "旧会话备注"
        item = db.query(database.WorkoutExercise).filter_by(plan_id=plan["id"]).one()
        item.exercise_id = second_id
        item.name = "VAN-15 备注新动作"
        db.commit()
    finally:
        db.close()

    cancelled = client.post("/api/session/cancel", json={"session_id": session_id})
    assert cancelled.status_code == 200, cancelled.text
    assert cancelled.json()["session"]["notes"] == "旧会话备注"
    db = database.SessionLocal()
    try:
        session = db.query(database.WorkoutSession).filter_by(id=session_id).one()
        record = db.query(database.SessionRecord).filter_by(session_id=session_id).one()
        assert session.notes == "旧会话备注"
        assert record.sets_completed == 1
        assert record.duration_seconds == 19
        assert record.notes == "动作事实备注"
    finally:
        db.close()

    # Explicit notes retain the pre-existing API behavior.
    plan2 = _create_plan(client, "2031-01-21", first_id)
    start2 = client.post("/api/session/start", json={"plan_id": plan2["id"]})
    assert start2.status_code == 200, start2.text
    sid2 = start2.json()["session"]["id"]
    db = database.SessionLocal()
    try:
        item2 = db.query(database.WorkoutExercise).filter_by(plan_id=plan2["id"]).one()
        item2.exercise_id = second_id
        item2.name = "VAN-15 备注新动作"
        db.commit()
    finally:
        db.close()
    explicit = client.post("/api/session/cancel", json={"session_id": sid2, "notes": "新会话备注"})
    assert explicit.status_code == 200, explicit.text
    assert explicit.json()["session"]["notes"] == "新会话备注"


def test_frontend_rejects_session_response_for_another_plan():
    script = r"""
const fs = require('fs');
const vm = require('vm');
const source = fs.readFileSync('static/index.html', 'utf8');
function section(startMarker, endMarker) {
  const start = source.indexOf(startMarker);
  const end = source.indexOf(endMarker, start);
  if (start < 0 || end < 0) throw new Error(`missing ${startMarker}`);
  return source.slice(start, end);
}
function response(body) { return { ok: true, status: 200, text: async () => JSON.stringify(body) }; }
async function run() {
  const context = {
    console, Promise, JSON, Object, Array, Error,
    v25Remote: { ready: true }, v25RemotePlanId: 7,
    v25RemoteSessionId: null, v25RemoteSessionPromise: null,
    v25RemotePlanPromise: Promise.resolve(7),
    fetch: async () => response({ status: 'started', session: { id: 8, plan_id: 99, status: 'in_progress' } }),
  };
  vm.createContext(context);
  vm.runInContext(section('function v25ApiFetch', 'function v25MigrationPreview'), context);
  let failed = false;
  try { await context.v25EnsureRemoteSession(); }
  catch (error) { failed = String(error.message).includes('不一致'); }
  if (!failed) throw new Error('mismatched session response was accepted');
  console.log('PASS');
}
run().catch((error) => { console.error(error.stack || error); process.exit(1); });
"""
    result = subprocess.run(
        ["node", "-e", script],
        capture_output=True,
        text=True,
        cwd=APP_DIR,
        timeout=30,
    )
    assert result.returncode == 0, result.stderr + "\n" + result.stdout
    assert "PASS" in result.stdout


def test_frontend_reconcile_refuses_mismatched_session_facts():
    script = r"""
const fs = require('fs');
const vm = require('vm');
const source = fs.readFileSync('static/index.html', 'utf8');
function section(startMarker, endMarker) {
  const start = source.indexOf(startMarker);
  const end = source.indexOf(endMarker, start);
  if (start < 0 || end < 0) throw new Error(`missing ${startMarker}`);
  return source.slice(start, end);
}
const context = {
  console, Promise, JSON, Object, Array, Error, Math, Date,
  clonePlain: (value) => Object.assign({}, value),
};
vm.createContext(context);
vm.runInContext(section('function v25ReconcileTodaySession', 'function v25ApplyCalendar'), context);
const result = context.v25ReconcileTodaySession(
  null,
  [{ exerciseId: 22, name: '动作 B', sets: 1, time: 5 }],
  '计划 B', false, true, false,
  { id: 8, plan_id: 7, status: 'in_progress', records: [{ exercise_id: 11, status: 'pending', sets_completed: 1, duration_seconds: 17 }] }
);
if (!result.contextConflict || result.started || result.done || result.records.length || result.pending) {
  throw new Error(`mismatch was mapped into current plan: ${JSON.stringify(result)}`);
}
console.log('PASS');
"""
    result = subprocess.run(
        ["node", "-e", script],
        capture_output=True,
        text=True,
        cwd=APP_DIR,
        timeout=30,
    )
    assert result.returncode == 0, result.stderr + "\n" + result.stdout
    assert "PASS" in result.stdout


def test_frontend_completed_history_conflict_has_no_cancel_action():
    script = r"""
const fs = require('fs');
const vm = require('vm');
const source = fs.readFileSync('static/index.html', 'utf8');
function section(startMarker, endMarker) {
  const start = source.indexOf(startMarker);
  const end = source.indexOf(endMarker, start);
  if (start < 0 || end < 0) throw new Error(`missing ${startMarker}`);
  return source.slice(start, end);
}
let modal = '';
const context = {
  console, Promise, JSON, Object, Array, Error, Math, Date,
  v25RemoteSessionConflictPrompted: false,
  openModal: (html) => { modal = html; },
  escapeHtml: (value) => String(value),
};
vm.createContext(context);
vm.runInContext(section('function v25ShowSessionConflict', 'var v25ToastTimer'), context);
context.v25ShowSessionConflict({ kind: 'completed_mismatch', sessionId: 8, canCancel: false, message: '历史完成事实与当前计划不一致' });
if (modal.includes('data-v25-cancel-conflict') || !modal.includes('历史完成事实与当前计划不一致')) {
  throw new Error(`completed conflict exposed an impossible cancel action: ${modal}`);
}
console.log('PASS');
"""
    result = subprocess.run(
        ["node", "-e", script],
        capture_output=True,
        text=True,
        cwd=APP_DIR,
        timeout=30,
    )
    assert result.returncode == 0, result.stderr + "\n" + result.stdout
    assert "PASS" in result.stdout
