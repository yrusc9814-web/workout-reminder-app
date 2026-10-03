"""VAN-17 repeated sessions, date attribution, and statistics contracts."""
from __future__ import annotations

from datetime import date
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor
import subprocess
import threading
import textwrap

from fastapi.testclient import TestClient
from sqlalchemy import event


def _exercise(client, name="VAN-17 动作", sets=1):
    response = client.post(
        "/api/exercises",
        json={
            "name": name,
            "category": "VAN-17",
            "difficulty": "低",
            "defaultSets": sets,
            "defaultReps": "8次",
        },
    )
    assert response.status_code == 201, response.text
    return response.json()["id"]


def _plan(client, exercise_id, plan_date="2040-01-15"):
    response = client.post(
        "/api/plans/generate",
        json={
            "date": plan_date,
            "title": "VAN-17 日期训练",
            "theme": "日期归属",
            "exerciseIds": [exercise_id],
        },
    )
    assert response.status_code == 200, response.text
    return response.json()["plan"]


def _complete(client, plan_id, exercise_id, duration=31, sets_completed=1):
    started = client.post("/api/session/start", json={"plan_id": plan_id})
    assert started.status_code == 200, started.text
    session = started.json()["session"]
    updated = client.post(
        "/api/session/update",
        json={
            "session_id": session["id"],
            "exercise_id": exercise_id,
            "status": "completed",
            "sets_completed": sets_completed,
            "duration_seconds": duration,
        },
    )
    assert updated.status_code == 200, updated.text
    completed = client.post("/api/session/complete", json={"session_id": session["id"]})
    assert completed.status_code == 200, completed.text
    return session["id"]


def test_repeated_sessions_use_independent_facts_and_shared_stats_contract(client, app_modules):
    database, _main = app_modules
    exercise_id = _exercise(client)
    plan = _plan(client, exercise_id)

    first = _complete(client, plan["id"], exercise_id, 31)
    second = _complete(client, plan["id"], exercise_id, 29)
    assert first != second

    overall = client.get("/api/stats").json()
    month = client.get("/api/stats/month", params={"month": "2040-01"}).json()
    detail = client.get("/api/stats/month/detail", params={"month": "2040-01"}).json()
    for body in (overall, month, detail):
        assert body["completed"] == 2
        assert body["completed_sessions"] == 2
        assert body["completed_days"] == 1
        assert body["completion_rate"] > 0
    assert month["duration_seconds"] == 60
    assert detail["duration_seconds"] == 60

    logs = client.get("/api/logs").json()["logs"]
    rows = [row for row in logs if row["plan_id"] == plan["id"]]
    assert {row["session_id"] for row in rows} == {first, second}
    assert {row["log_date"] for row in rows} == {"2040-01-15"}

    db = database.SessionLocal()
    try:
        stored = db.query(database.WorkoutLog).filter_by(plan_id=plan["id"]).order_by(database.WorkoutLog.id).all()
        assert [(row.session_id, row.log_date) for row in stored] == [
            (first, date(2040, 1, 15)),
            (second, date(2040, 1, 15)),
        ]
    finally:
        db.close()


def test_partial_session_and_duplicate_complete_do_not_change_stats(client):
    exercise_id = _exercise(client, "VAN-17 多组动作", sets=2)
    plan = _plan(client, exercise_id, "2040-01-16")
    started = client.post("/api/session/start", json={"plan_id": plan["id"]}).json()["session"]
    partial = client.post(
        "/api/session/update",
        json={
            "session_id": started["id"],
            "exercise_id": exercise_id,
            "status": "completed",
            "sets_completed": 1,
            "duration_seconds": 12,
        },
    )
    assert partial.status_code == 422
    assert client.post("/api/session/complete", json={"session_id": started["id"]}).status_code == 422
    assert client.get("/api/stats").json()["completed"] == 0
    assert client.get("/api/stats/month", params={"month": "2040-01"}).json()["duration_seconds"] == 0


def test_partial_skip_duration_is_retained_in_month_and_day_stats(client):
    exercise_id = _exercise(client, "VAN-17 跳过保留时长", sets=3)
    plan = _plan(client, exercise_id, "2040-01-21")
    session = client.post("/api/session/start", json={"plan_id": plan["id"]}).json()["session"]
    first = client.post(
        "/api/session/update",
        json={
            "session_id": session["id"],
            "exercise_id": exercise_id,
            "status": "pending",
            "sets_completed": 1,
            "duration_seconds": 12,
        },
    )
    assert first.status_code == 200, first.text
    skipped = client.post(
        "/api/session/update",
        json={
            "session_id": session["id"],
            "exercise_id": exercise_id,
            "status": "skipped",
            "sets_completed": 1,
            "duration_seconds": 12,
        },
    )
    assert skipped.status_code == 200, skipped.text
    completed = client.post("/api/session/complete", json={"session_id": session["id"]})
    assert completed.status_code == 200, completed.text
    assert completed.json()["summary"]["duration_seconds"] == 12
    month = client.get("/api/stats/month", params={"month": "2040-01"}).json()
    detail = client.get("/api/stats/month/detail", params={"month": "2040-01"}).json()
    day = next(row for row in detail["days"] if row["date"] == "2040-01-21")
    assert month["duration_seconds"] == 12
    assert day["duration"]["duration_seconds"] == 12


def test_zero_set_skip_only_counts_positive_duration_as_training_time(client):
    exercise_id = _exercise(client, "VAN-17 零组跳过时长", sets=3)

    positive_plan = _plan(client, exercise_id, "2040-01-26")
    positive_session = client.post("/api/session/start", json={"plan_id": positive_plan["id"]}).json()["session"]
    positive = client.post(
        "/api/session/update",
        json={
            "session_id": positive_session["id"],
            "exercise_id": exercise_id,
            "status": "skipped",
            "sets_completed": 0,
            "duration_seconds": 12,
        },
    )
    assert positive.status_code == 200, positive.text
    assert client.post("/api/session/complete", json={"session_id": positive_session["id"]}).status_code == 200

    zero_plan = _plan(client, exercise_id, "2040-01-27")
    zero_session = client.post("/api/session/start", json={"plan_id": zero_plan["id"]}).json()["session"]
    zero = client.post(
        "/api/session/update",
        json={
            "session_id": zero_session["id"],
            "exercise_id": exercise_id,
            "status": "skipped",
            "sets_completed": 0,
            "duration_seconds": 0,
        },
    )
    assert zero.status_code == 200, zero.text
    assert client.post("/api/session/complete", json={"session_id": zero_session["id"]}).status_code == 200

    unknown_plan = _plan(client, exercise_id, "2040-01-28")
    unknown_session = client.post("/api/session/start", json={"plan_id": unknown_plan["id"]}).json()["session"]
    unknown = client.post(
        "/api/session/update",
        json={
            "session_id": unknown_session["id"],
            "exercise_id": exercise_id,
            "status": "skipped",
            "sets_completed": 0,
        },
    )
    assert unknown.status_code == 200, unknown.text
    assert client.post("/api/session/complete", json={"session_id": unknown_session["id"]}).status_code == 200

    month = client.get("/api/stats/month", params={"month": "2040-01"}).json()
    assert month["duration_seconds"] == 12
    assert month["duration_known_records"] == 1
    assert month["duration_unknown_records"] == 0
    assert month["duration_zero_records"] == 0


def test_rest_conversion_preserves_history_but_blocks_current_completed_hydration(client):
    exercise_id = _exercise(client, "VAN-17 休息日转换", sets=2)
    plan = _plan(client, exercise_id, "2040-01-22")
    session_id = _complete(client, plan["id"], exercise_id, duration=20, sets_completed=2)
    changed = client.put(f"/api/plans/{plan['id']}", json={"is_training_day": False})
    assert changed.status_code == 200, changed.text
    current = client.get(
        f"/api/session/current?plan_id={plan['id']}&include_completed=true"
    )
    assert current.status_code == 200, current.text
    assert current.json().get("session") is None
    assert current.json().get("history_conflict", {}).get("code") == "COMPLETED_SESSION_PLAN_CONTEXT_MISMATCH"
    month = client.get("/api/stats/month", params={"month": "2040-01"}).json()
    detail = client.get("/api/stats/month/detail", params={"month": "2040-01"}).json()
    day = next(row for row in detail["days"] if row["date"] == "2040-01-22")
    assert month["completed"] == 1
    assert month["completed_sessions"] == 1
    assert month["completed_days"] == 0
    assert month["duration_seconds"] == 20
    assert day["is_training"] is False
    assert day["status"] == "rest"


def test_nonduplicate_completion_integrity_error_rolls_back_and_retry_records_once(client, app_modules):
    database, main = app_modules
    exercise_id = _exercise(client, "VAN-17 非重复失败")
    plan = _plan(client, exercise_id, "2040-01-23")
    session = client.post("/api/session/start", json={"plan_id": plan["id"]}).json()["session"]
    updated = client.post(
        "/api/session/update",
        json={
            "session_id": session["id"],
            "exercise_id": exercise_id,
            "status": "completed",
            "sets_completed": 1,
            "duration_seconds": 22,
        },
    )
    assert updated.status_code == 200, updated.text
    connection = database.engine.connect()
    connection.exec_driver_sql(
        f"CREATE TRIGGER van17_reject_{session['id']} BEFORE INSERT ON workout_logs "
        f"WHEN NEW.session_id={session['id']} BEGIN SELECT RAISE(ABORT, 'van17 injected nonduplicate failure'); END"
    )
    connection.commit()
    connection.close()
    isolated_client = TestClient(main.app, raise_server_exceptions=False)
    try:
        failed = isolated_client.post("/api/session/complete", json={"session_id": session["id"]})
        assert failed.status_code == 500, failed.text
        db = database.SessionLocal()
        try:
            stored_session = db.get(database.WorkoutSession, session["id"])
            assert stored_session.status == "in_progress"
            assert db.query(database.WorkoutLog).filter_by(session_id=session["id"]).count() == 0
        finally:
            db.close()
    finally:
        connection = database.engine.connect()
        connection.exec_driver_sql(f"DROP TRIGGER van17_reject_{session['id']}")
        connection.commit()
        connection.close()
    retried = isolated_client.post("/api/session/complete", json={"session_id": session["id"]})
    assert retried.status_code == 200, retried.text
    assert retried.json()["status"] == "completed"
    db = database.SessionLocal()
    try:
        assert db.query(database.WorkoutLog).filter_by(session_id=session["id"]).count() == 1
    finally:
        db.close()


def test_concurrent_old_progress_cannot_regress_newer_committed_fact(client, app_modules):
    database, _main = app_modules
    exercise_id = _exercise(client, "VAN-17 并发单调", sets=3)
    plan = _plan(client, exercise_id, "2040-01-24")
    session = client.post("/api/session/start", json={"plan_id": plan["id"]}).json()["session"]
    record_id = session["records"][0]["id"]
    reached = threading.Event()
    release = threading.Event()
    delayed_once = {"value": False}

    def delay_old_update(_conn, _cursor, statement, parameters, _context, _executemany):
        if (
            statement.startswith("UPDATE session_records SET")
            and record_id in tuple(parameters)
            and not delayed_once["value"]
        ):
            delayed_once["value"] = True
            reached.set()
            assert release.wait(15), "delayed update was not released"

    event.listen(database.engine, "before_cursor_execute", delay_old_update)
    try:
        with ThreadPoolExecutor(max_workers=2) as pool:
            old_request = pool.submit(
                client.post,
                "/api/session/update",
                json={
                    "session_id": session["id"],
                    "exercise_id": exercise_id,
                    "status": "pending",
                    "sets_completed": 1,
                    "duration_seconds": 10,
                },
            )
            assert reached.wait(10), "old update did not reach SQL"
            newer = client.post(
                "/api/session/update",
                json={
                    "session_id": session["id"],
                    "exercise_id": exercise_id,
                    "status": "pending",
                    "sets_completed": 2,
                    "duration_seconds": 20,
                },
            )
            release.set()
            older = old_request.result(timeout=15)
    finally:
        release.set()
        event.remove(database.engine, "before_cursor_execute", delay_old_update)
    assert newer.status_code == 200, newer.text
    assert older.status_code == 200, older.text
    db = database.SessionLocal()
    try:
        stored = db.get(database.SessionRecord, record_id)
        assert stored.sets_completed == 2
        assert stored.duration_seconds == 20
    finally:
        db.close()


def test_delayed_update_cannot_mutate_a_session_cancelled_in_the_meantime(client, app_modules):
    database, _main = app_modules
    exercise_id = _exercise(client, "VAN-17 终态竞争", sets=2)
    plan = _plan(client, exercise_id, "2040-01-25")
    session = client.post("/api/session/start", json={"plan_id": plan["id"]}).json()["session"]
    record_id = session["records"][0]["id"]
    reached = threading.Event()
    release = threading.Event()
    delayed_once = {"value": False}

    def delay_old_update(_conn, _cursor, statement, parameters, _context, _executemany):
        if (
            statement.startswith("UPDATE session_records SET")
            and record_id in tuple(parameters)
            and not delayed_once["value"]
        ):
            delayed_once["value"] = True
            reached.set()
            assert release.wait(15), "delayed update was not released"

    event.listen(database.engine, "before_cursor_execute", delay_old_update)
    try:
        with ThreadPoolExecutor(max_workers=2) as pool:
            old_request = pool.submit(
                client.post,
                "/api/session/update",
                json={
                    "session_id": session["id"],
                    "exercise_id": exercise_id,
                    "status": "pending",
                    "sets_completed": 1,
                    "duration_seconds": 10,
                },
            )
            assert reached.wait(10), "old update did not reach SQL"
            cancelled = client.post("/api/session/cancel", json={"session_id": session["id"]})
            release.set()
            older = old_request.result(timeout=15)
    finally:
        release.set()
        event.remove(database.engine, "before_cursor_execute", delay_old_update)
    assert cancelled.status_code == 200, cancelled.text
    assert older.status_code == 422, older.text
    db = database.SessionLocal()
    try:
        stored = db.get(database.SessionRecord, record_id)
        assert stored.status == "pending"
        assert stored.sets_completed is None
        assert db.get(database.WorkoutSession, session["id"]).status == "cancelled"
    finally:
        db.close()


def test_legacy_completion_is_idempotent_across_session_endpoint(client):
    exercise_id = _exercise(client, "VAN-17 legacy"); plan = _plan(client, exercise_id, "2040-01-17")
    session_id = _complete(client, plan["id"], exercise_id)
    replay = client.post("/api/logs/complete", json={"plan_id": plan["id"]})
    assert replay.status_code == 200, replay.text
    assert replay.json()["session_id"] == session_id
    assert client.get("/api/stats").json()["completed"] == 1


def test_legacy_fingerprint_survives_metadata_edit_but_blocks_action_replacement(client):
    first_id = _exercise(client, "VAN-17 原动作")
    second_id = _exercise(client, "VAN-17 新动作")
    plan = _plan(client, first_id, "2040-01-18")
    first = client.post("/api/logs/complete", json={"plan_id": plan["id"]})
    assert first.status_code == 200

    metadata = client.put(f"/api/plans/{plan['id']}", json={"title": "只改标题"})
    assert metadata.status_code == 200, metadata.text
    replay = client.post("/api/logs/complete", json={"plan_id": plan["id"]})
    assert replay.status_code == 200
    assert replay.json()["id"] == first.json()["id"]

    changed = client.put(f"/api/plans/{plan['id']}", json={"exercise_ids": [second_id], "is_training_day": True})
    assert changed.status_code == 200, changed.text
    stale = client.post("/api/logs/complete", json={"plan_id": plan["id"]})
    assert stale.status_code == 409, stale.text
    detail = client.get("/api/stats/month/detail", params={"month": "2040-01"}).json()
    assert next(day for day in detail["days"] if day["date"] == "2040-01-18")["status"] == "planned"


def test_pre_fingerprint_completed_session_is_frozen_before_target_change(client, app_modules):
    database, _main = app_modules
    exercise_id = _exercise(client, "VAN-17 旧 session", sets=3)
    plan = _plan(client, exercise_id, "2040-01-19")
    legacy = client.post("/api/logs/complete", json={"plan_id": plan["id"]})
    assert legacy.status_code == 200, legacy.text
    client.put(
        f"/api/plans/{plan['id']}",
        json={"items": [{"exercise_id": exercise_id, "sets": 4, "reps": 8}], "is_training_day": True},
    )
    session_id = _complete(client, plan["id"], exercise_id, 40, sets_completed=4)
    db = database.SessionLocal()
    try:
        session = db.get(database.WorkoutSession, session_id)
        session.plan_action_fingerprint = None
        for row in db.query(database.WorkoutLog).filter_by(session_id=session_id):
            row.plan_action_fingerprint = None
        db.commit()
    finally:
        db.close()
    changed = client.put(
        f"/api/plans/{plan['id']}",
        json={"items": [{"exercise_id": exercise_id, "sets": 5, "reps": 8}], "is_training_day": True},
    )
    assert changed.status_code == 200, changed.text
    totals = client.get("/api/stats").json()
    assert (totals["completed"], totals["completed_sessions"], totals["completed_days"], totals["duration_seconds"]) == (2, 1, 0, 40)
    current = client.get(f"/api/session/current?plan_id={plan['id']}&include_completed=true").json()
    assert current["session"] is None and current.get("history_conflict")


def test_template_change_freezes_old_legacy_and_session_facts_before_mutation(client, app_modules):
    database, _main = app_modules
    exercise_id = _exercise(client, "VAN-17 模板动作", sets=1)
    first_template = client.post("/api/templates", json={"name": "VAN-17 模板 A", "exercise_ids": [exercise_id]})
    second_template = client.post("/api/templates", json={"name": "VAN-17 模板 B", "exercise_ids": [exercise_id]})
    assert first_template.status_code == second_template.status_code == 201
    plan = _plan(client, exercise_id, "2040-01-20")
    bound = client.put(f"/api/plans/{plan['id']}", json={"template_id": first_template.json()["id"], "is_training_day": True})
    assert bound.status_code == 200, bound.text
    legacy = client.post("/api/logs/complete", json={"plan_id": plan["id"]})
    assert legacy.status_code == 200, legacy.text
    session_id = _complete(client, plan["id"], exercise_id, 22)
    db = database.SessionLocal()
    try:
        db.get(database.WorkoutSession, session_id).plan_action_fingerprint = None
        for row in db.query(database.WorkoutLog).filter_by(session_id=session_id):
            row.plan_action_fingerprint = None
        db.query(database.WorkoutLog).filter_by(id=legacy.json()["id"]).one().plan_action_fingerprint = None
        db.commit()
    finally:
        db.close()
    changed = client.put(f"/api/plans/{plan['id']}", json={"template_id": second_template.json()["id"], "is_training_day": True})
    assert changed.status_code == 200, changed.text
    totals = client.get("/api/stats").json()
    assert (totals["completed"], totals["completed_sessions"], totals["completed_days"]) == (2, 1, 0)


def test_old_and_future_plan_dates_stay_on_their_plan_date(client, app_modules):
    database, _main = app_modules
    exercise_id = _exercise(client, "VAN-17 跨日期")
    old_plan = _plan(client, exercise_id, "2039-12-31")
    future_plan = _plan(client, exercise_id, "2040-02-01")
    old_session = _complete(client, old_plan["id"], exercise_id, 17)
    future_session = _complete(client, future_plan["id"], exercise_id, 19)
    dated_current = client.get(
        "/api/session/current",
        params={"date": "2040-02-01", "include_completed": "true"},
    )
    assert dated_current.status_code == 200, dated_current.text
    assert dated_current.json()["session"]["id"] == future_session
    assert dated_current.json()["plan"]["date"] == "2040-02-01"
    db = database.SessionLocal()
    try:
        logs = db.query(database.WorkoutLog).filter(database.WorkoutLog.session_id.in_([old_session, future_session])).all()
        assert {(row.session_id, row.log_date) for row in logs} == {
            (old_session, date(2039, 12, 31)),
            (future_session, date(2040, 2, 1)),
        }
    finally:
        db.close()


def test_calendar_start_passes_the_selected_date_to_start_plan():
    source = (Path(__file__).resolve().parents[1] / "static" / "index.html").read_text(encoding="utf-8")
    assert "startPlan(getCalendarPlan(dateKey), dateKey)" in source
    assert "function v25ActiveSessionDateKey()" in source
    assert "function v25SetActiveSessionDate(dateKey, options)" in source


def _run_node(script: str):
    result = subprocess.run(
        ["node", "-e", textwrap.dedent(script)],
        cwd=Path(__file__).resolve().parents[1],
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert result.returncode == 0, result.stderr + "\n" + result.stdout
    return result.stdout


def test_frontend_boot_keeps_a_valid_historical_active_session_in_its_date_context():
    output = _run_node(
        r'''
        const fs = require('fs'), vm = require('vm');
        const source = fs.readFileSync('static/index.html', 'utf8');
        const start = source.indexOf('function v25ResolveBootSessionContext');
        const end = source.indexOf('function v25EnsureRemoteSession', start);
        const context = { console, isValidDateKey: (value) => /^\d{4}-\d{2}-\d{2}$/.test(value) };
        vm.createContext(context);
        vm.runInContext(source.slice(start, end), context);
        const plan = { id: 3, date: '2026-09-30', isTrainingDay: true, items: [{ exercise_id: 11, name: '三组动作', sets: 3 }] };
        const session = { id: 7, plan_id: 3, status: 'in_progress', date: '2026-09-30' };
        const active = context.v25ResolveBootSessionContext(session, plan, 1);
        if (!active.targetActive || active.foreignActive || active.activeDateKey !== '2026-09-30' || active.activeSession.id !== 7) throw new Error(JSON.stringify(active));
        const foreign = context.v25ResolveBootSessionContext({ id: 8, plan_id: 99, status: 'in_progress' }, null, 1);
        if (!foreign.foreignActive || foreign.activeSession !== null) throw new Error(JSON.stringify(foreign));
        console.log(JSON.stringify({ PASS: true, active_date: active.activeDateKey, session_id: active.activeSession.id }));
        '''
    )
    assert '"PASS":true' in output.replace(" ", "")


def test_frontend_refresh_keeps_active_context_and_refreshes_only_current_week():
    output = _run_node(
        r'''
        const fs = require('fs'), vm = require('vm');
        const source = fs.readFileSync('static/index.html', 'utf8');
        const start = source.indexOf('function v25RefreshCanonical');
        const end = source.indexOf('function v25SaveCanonicalPlan', start);
        const calls = [];
        const context = {
          console, Promise, Object, Array, String, Number, Math, Date,
          v25Remote: { loadedMonths: { '2026-10': true }, planDays: {}, monthStatus: {}, monthRequests: {}, statsByMonth: {}, detailByMonth: {}, today: { id: 1, title: '今天' }, weekStats: null },
          v25WeekRequestSequence: 0, v25WeekRequestOwner: 0, v25WeekRequestDateKey: '',
          v25MonthForDate: (key) => String(key).slice(0, 7), v25TodayKey: () => '2026-10-03',
          v25ActiveSessionDateKey: () => context.activeDate, v25ActiveContextGeneration: 1,
          v25RemotePlanId: 3, v25RemoteSessionId: 7, todayStarted: true, todayDone: false, v25RemoteProgressPending: false,
          getToday: () => new Date('2026-10-03T00:00:00Z'), formatDateKey: (d) => d.toISOString().slice(0, 10),
          getCurrentWeekDates: () => ['2026-09-27','2026-09-28','2026-09-29','2026-09-30','2026-10-01','2026-10-02','2026-10-03'].map((key) => new Date(key + 'T00:00:00Z')),
          v25RefreshMonth: (month) => { calls.push('month:' + month); return Promise.resolve({ month }); },
          v25ApiFetch: (path) => { calls.push(path); return Promise.resolve(path.includes('/stats/week/') ? { week: true } : { id: 1 }); },
          v25ApplyWeekStats: (value) => { context.weekApplied = value; },
          v25ApplyActiveSessionPlan: () => { context.activeApplied = true; },
          v25DisplayedMonthToken: () => '2026-10', v25ApplyStats: () => {}, renderTodayPlan: () => { context.rendered = true; },
          renderWeek: () => {}, renderCalendarMonth: () => {}, saveTrainingState: () => {},
        };
        vm.createContext(context);
        vm.runInContext(source.slice(start, end), context);
        (async () => {
          context.activeDate = '2026-09-30';
          await context.v25RefreshCanonical(['2026-09-30'], { forceToday: true, refreshLoaded: true });
          if (calls.includes('/api/plans/today') || !calls.includes('/api/stats/week/detail?date=2026-10-03') || context.activeApplied) throw new Error(JSON.stringify({ calls, activeApplied: context.activeApplied }));
          calls.length = 0;
          context.activeDate = '2030-11-02';
          await context.v25RefreshCanonical(['2030-11-02'], { forceToday: true });
          if (calls.some((call) => String(call).includes('/api/stats/week/'))) throw new Error(JSON.stringify({ calls }));
          console.log(JSON.stringify({ PASS: true, historical_calls: calls }));
        })().catch((error) => { console.error(error.stack || error); process.exit(1); });
        '''
    )
    assert '"PASS":true' in output.replace(" ", "")


def test_frontend_active_date_controls_use_active_target_for_canonical_writes():
    source = (Path(__file__).resolve().parents[1] / "static" / "index.html").read_text(encoding="utf-8")
    assert "v25SaveCanonicalPlan(activeDateKey, nextItems, nextPlan)" in source
    assert "v25SaveCanonicalPlan(activeDateKey, nextTodayItems, currentTodayPlan)" in source
    assert "v25SaveCanonicalPlan(activeDateKey, [], clearPlan)" in source
    assert "var activeDateKey = typeof v25ActiveSessionDateKey === 'function' ? v25ActiveSessionDateKey() : v25TodayKey();" in source


def test_frontend_start_plan_keeps_remote_date_and_saves_local_plan_to_target_date():
    output = _run_node(
        r'''
        const fs = require('fs'), vm = require('vm');
        const source = fs.readFileSync('static/index.html', 'utf8');
        const start = source.indexOf('function startPlan');
        const end = source.indexOf('function addToToday', start);
        const saves = [];
        const context = {
          console, Promise, JSON, Object, Array, Error, Math, Date, Number, String,
          v25Remote: { ready: true, exercises: [{ id: 7, name: '动作 A' }] },
          v25RemoteSessionConflict: null, v25RemoteSessionConflictPrompted: false,
          v25RemotePlanId: null, v25RemotePlanPromise: null, v25RemoteSessionId: null,
          v25RemoteSessionPromise: null, v25RemoteStepPromise: Promise.resolve(), v25RemoteCompleted: false,
          v25RemoteProgressPending: false, v25RemoteFinalUpdateConfirmed: false,
          v25RemoteStatusVerified: true, v25LocalDoneAwaitingVerification: false,
          todaySessionKey: '2026-10-03', dailySessions: {}, todayPlan: [], todayDone: false,
          todayStarted: false, todayIsRest: false, todayStepIndex: 0, todaySetIndex: 0,
          todayActionElapsedSeconds: 0, todayActionStartedAt: null, todaySkipped: [], todayRecordFacts: [], todayPendingProgress: null,
          v25TodayKey: () => '2026-10-03', isValidDateKey: (value) => /^\d{4}-\d{2}-\d{2}$/.test(value),
          v25RemoteExerciseByName: (name) => context.v25Remote.exercises.find((row) => row.name === name) || null,
          v25ParseUiItem: (item) => typeof item === 'object' ? { id: item.id || null, exercise_id: item.exercise_id || 7, name: item.name, sets: item.sets || 1, reps: item.reps || null, duration_seconds: item.duration_seconds || null, notes: null, video_url: null, spec: item.spec || '1 组' } : { id: null, exercise_id: 7, name: String(item).split(' · ')[0], sets: 1, reps: 8, duration_seconds: null, notes: null, video_url: null, spec: '1 组 · 8 次' },
          v25SpecForItem: () => '1 组 · 8 次', v25SetActiveSessionDate: (key) => { context.todaySessionKey = key; return key; },
          v25SaveCanonicalPlan: (dateKey, items, plan) => { saves.push({ dateKey, items, plan }); return Promise.resolve({ plan: { id: 88 } }); },
          resetStartBtn: () => {}, saveTrainingState: () => {}, renderTodayPlan: () => {}, showView: () => {}, showToast: () => {},
        };
        vm.createContext(context);
        vm.runInContext(source.slice(start, end), context);
        (async () => {
          context.startPlan({ id: 42, remote: true, title: '历史计划', time: 10, items: [{ id: 9, exercise_id: 7, name: '动作 A', sets: 2, reps: 8, spec: '2 组 · 8 次' }] }, '2030-01-05');
          if (saves.length !== 0 || context.todaySessionKey !== '2030-01-05' || context.v25RemotePlanId !== 42) throw new Error(JSON.stringify({ saves, key: context.todaySessionKey, plan: context.v25RemotePlanId }));
          context.todaySessionKey = '2026-10-03';
          context.startPlan({ remote: false, title: '未来方案', time: 12, intensity: '低', scene: '测试', items: ['动作 A · 2×8'] }, '2030-02-06');
          await Promise.resolve();
          if (saves.length !== 1 || saves[0].dateKey !== '2030-02-06' || context.todaySessionKey !== '2030-02-06' || context.v25RemotePlanId !== 88) throw new Error(JSON.stringify({ saves, key: context.todaySessionKey, plan: context.v25RemotePlanId }));
          console.log(JSON.stringify({ PASS: true, remote_date: '2030-01-05', local_date: saves[0].dateKey }));
        })().catch((error) => { console.error(error.stack || error); process.exit(1); });
        '''
    )
    assert '"PASS":true' in output.replace(" ", "")


def test_frontend_fresh_hydrate_reads_last_active_plan_session_records():
    output = _run_node(
        r'''
        const fs = require('fs'), vm = require('vm');
        const source = fs.readFileSync('static/index.html', 'utf8');
        const start = source.indexOf('function bootV25Api');
        const end = source.indexOf('// P0-2：启动前同步 hydrate', start);
        const calls = [];
        const context = {
          console, Promise, JSON, Object, Array, Error, Math, Number, String, Date,
          v25Remote: { ready: false, today: null, calendar: {}, calendarDays: {}, planDays: {}, loadedMonths: {}, monthStatus: {}, monthRequests: {}, statsByMonth: {}, detailByMonth: {}, stats: null, weekStats: null, exercises: [], templates: [], favorites: [] },
          v25MonthRequestSequence: 0, v25WeekRequestSequence: 0, v25WeekRequestOwner: 0, v25WeekRequestDateKey: '',
          v25BootRequestSequence: 0, v25DisplayedMonthRequest: 0, v25RemoteDataVerified: false,
          v25RemotePlanId: 1, v25RemotePlanPromise: null, v25RemoteSessionId: null, v25RemoteSessionPromise: null,
          v25RemoteStepPromise: Promise.resolve(), v25RemoteCompleted: false, v25RemoteSessionConflict: null, v25RemoteSessionConflictPrompted: false,
          v25RemoteProgressPending: false, v25RemoteFinalUpdateConfirmed: false, v25RemoteStatusVerified: false, v25LocalDoneAwaitingVerification: false,
          todaySessionKey: '2030-11-02', dailySessions: { '2030-11-02': { started: true, done: false, items: [] } },
          todayPlan: [], todayIsRest: true, todayDone: false, todayStarted: false, todayStepIndex: 0, todaySetIndex: 0,
          todayActionElapsedSeconds: 0, todayActionStartedAt: null, todaySkipped: [], todayRecordFacts: [], todayPendingProgress: null,
          calendarPlans: {}, calendarDisplayYear: 2026, calendarDisplayMonth: 9,
          v25TodayDisplayState: 'loading', v25ActiveContextGeneration: 1,
          formatDateKey: (d) => d.toISOString().slice(0, 10), getToday: () => new Date('2026-10-03T00:00:00Z'),
          v25TodayKey: () => '2026-10-03', v25MonthForDate: (key) => String(key).slice(0, 7), isValidDateKey: (key) => /^\d{4}-\d{2}-\d{2}$/.test(key),
          v25WeekMonthTokens: () => [], v25DisplayedMonthToken: () => '2026-10', v25ClearMonth: () => {},
          resetTodayRuntimeForUnverifiedData: () => {}, renderTodayPlan: () => {}, renderWeek: () => {}, renderCalendarMonth: () => {},
          v25ApplyStats: () => {}, v25ApplyWeekStats: () => {}, v25ApplyCalendar: () => {}, v25ApplyPlanDays: () => {},
          v25RenderLibrary: () => {}, v25ApplyTemplates: () => {}, renderFavorites: () => {}, saveFavorites: () => {}, mode: () => {}, apiSettings: {},
          v25ShowSessionConflict: () => {}, showToast: () => {}, saveTrainingState: () => {},
          v25RefreshMonth: (month) => Promise.resolve({ month }),
          v25BackendStatusForDay: () => null,
          v25ParseUiItem: (item) => ({ id: item.id || null, exercise_id: item.exercise_id || null, name: item.name, sets: item.sets || 1, reps: item.reps || null, duration_seconds: item.duration_seconds || null, notes: null, video_url: null, spec: item.spec || '' }),
          v25SpecForItem: () => '',
          v25ApplyActiveSessionPlan: (plan, dateKey) => {
            context.todaySessionKey = dateKey;
            context.todayPlan = (plan.items || []).map((item) => ({ name: item.name, exerciseId: item.exercise_id, sets: item.sets, reps: item.reps, duration_seconds: item.duration_seconds, spec: item.spec || '', time: 5 }));
            context.todayPlan.source = plan.title;
            context.todayIsRest = false;
            context.v25TodayDisplayState = 'data';
          },
          v25ResolveBootSessionContext: (session, plan, currentPlanId, selectedDate) => ({
            activeSession: session && session.status === 'completed' ? session : null,
            activePlan: plan,
            activeDateKey: selectedDate,
            targetActive: true,
            foreignActive: false,
          }),
          v25ReconcileTodaySession: (previous, planItems, source, isRest, known, done, session) => ({
            items: planItems, source, stepIndex: 1, setIndex: 0, actionElapsedSeconds: 0, actionStartedAt: null, skipped: [],
            records: (session.records || []).map((record) => ({ status: record.status, setsCompleted: record.sets_completed || 0, durationSeconds: record.duration_seconds })),
            pending: null, started: true, done: session.status === 'completed', rest: false,
          }),
          v25ApiFetch: (path) => {
            calls.push(path);
            if (path === '/api/plans/today') return Promise.resolve({ id: 1, date: '2026-10-03', title: '今天', isTrainingDay: true, is_training: true, items: [{ id: 1, exercise_id: 11, name: '今天动作', sets: 1 }] });
            if (path.indexOf('/api/session/current?date=2030-11-02') === 0) return Promise.resolve({ session: { id: 8, plan_id: 99, status: 'completed', records: [{ exercise_id: 21, status: 'completed', sets_completed: 3, duration_seconds: 90 }] }, plan: { id: 99, date: '2030-11-02', title: '未来训练', isTrainingDay: true, items: [{ id: 2, exercise_id: 21, name: '未来动作', sets: 3 }] } });
            if (path === '/api/session/current?include_completed=true') return Promise.resolve({ session: null });
            if (path.indexOf('/api/stats/week/') === 0) return Promise.resolve({ days: [] });
            if (path.indexOf('/api/stats/month/detail') === 0) return Promise.resolve({ days: [] });
            if (path.indexOf('/api/stats/month') === 0) return Promise.resolve({ training_days: 0, completed: 0, completed_days: 0, completion_rate: 0 });
            if (path.indexOf('/api/calendar') === 0 || path.indexOf('/api/plans/month') === 0) return Promise.resolve({ days: [] });
            if (path === '/api/exercises') return Promise.resolve({ exercises: [] });
            if (path === '/api/templates') return Promise.resolve({ templates: [] });
            if (path === '/api/favorites') return Promise.resolve({ favorites: [] });
            if (path === '/api/ai/provider') return Promise.resolve({ provider: 'local-demo', model: '' });
            if (path === '/api/ai/models') return Promise.resolve({ models: [] });
            throw new Error('unexpected path ' + path);
          },
        };
        vm.createContext(context);
        vm.runInContext(source.slice(start, end), context);
        (async () => {
          await context.bootV25Api();
          if (context.todaySessionKey !== '2030-11-02' || context.todayPlan[0].name !== '未来动作' || !context.todayDone || context.todayRecordFacts[0].setsCompleted !== 3 || context.todayRecordFacts[0].durationSeconds !== 90) {
            throw new Error(JSON.stringify({ key: context.todaySessionKey, plan: context.todayPlan, done: context.todayDone, facts: context.todayRecordFacts, calls }));
          }
          if (!calls.some((path) => path.indexOf('/api/session/current?date=2030-11-02') === 0)) throw new Error('date-bound session request missing');
          console.log(JSON.stringify({ PASS: true, date: context.todaySessionKey, sets: context.todayRecordFacts[0].setsCompleted, duration: context.todayRecordFacts[0].durationSeconds }));
        })().catch((error) => { console.error(error.stack || error); process.exit(1); });
        '''
    )
    assert '"PASS":true' in output.replace(" ", "")


def test_frontend_full_page_click_and_fresh_hydrate_production_flow():
    result = subprocess.run(
        ["node", "tests/van17_fresh_hydrate_behavior.js"],
        cwd=Path(__file__).resolve().parents[1],
        capture_output=True,
        text=True,
        timeout=45,
    )
    assert result.returncode == 0, result.stderr + "\n" + result.stdout
    assert '"PASS":true' in result.stdout.replace(" ", "")
