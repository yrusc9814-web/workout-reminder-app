"""VAN-13 session truth tests.

The API cases use the real FastAPI routes and an isolated SQLite database.  The
frontend case evaluates the tracked inline v25 functions themselves; it does
not copy their progress algorithm into a test helper.
"""
from __future__ import annotations

import json
import os
import subprocess
import textwrap
import time
from datetime import date
from pathlib import Path


EVIDENCE_DIR = Path(
    os.environ.get("VAN13_EVIDENCE_DIR", f"/private/tmp/van13-execution-{os.getpid()}")
)


def _create_exercise(client, name: str, sets: int):
    response = client.post(
        "/api/exercises",
        json={
            "name": name,
            "category": "VAN-13",
            "difficulty": "低",
            "defaultSets": sets,
            "defaultReps": "8次",
        },
    )
    assert response.status_code == 201, response.text
    return response.json()["id"]


def _create_plan(client, exercise_ids, token: str):
    response = client.post(
        "/api/plans/generate",
        json={
            "date": token,
            "title": "VAN-13 真实执行",
            "theme": "按组确认",
            "exerciseIds": exercise_ids,
        },
    )
    assert response.status_code == 200, response.text
    return response.json()["plan"]


def _snapshot(database, session_id: int, plan_id: int):
    db = database.SessionLocal()
    try:
        session = db.query(database.WorkoutSession).filter_by(id=session_id).one()
        records = db.query(database.SessionRecord).filter_by(session_id=session_id).order_by(database.SessionRecord.id).all()
        logs = db.query(database.WorkoutLog).filter_by(plan_id=plan_id).order_by(database.WorkoutLog.id).all()
        return {
            "session": {"id": session.id, "status": session.status},
            "records": [
                {
                    "exercise_id": row.exercise_id,
                    "status": row.status,
                    "sets_completed": row.sets_completed,
                    "duration_seconds": row.duration_seconds,
                }
                for row in records
            ],
            "logs": [
                {"action": row.action, "status": row.status, "session_id": row.session_id}
                for row in logs
            ],
        }
    finally:
        db.close()


def test_van13_real_api_tracks_groups_duration_and_terminal_truth(client, app_modules):
    database, _main = app_modules
    first_id = _create_exercise(client, "VAN-13 多组动作", 3)
    second_id = _create_exercise(client, "VAN-13 跳过动作", 2)
    plan = _create_plan(client, [first_id, second_id], "2026-12-13")

    started = client.post("/api/session/start", json={"plan_id": plan["id"]})
    assert started.status_code == 200, started.text
    session = started.json()["session"]
    session_id = session["id"]
    assert session["status"] == "in_progress"
    assert [record["status"] for record in session["records"]] == ["pending", "pending"]

    before_finish = client.post("/api/session/complete", json={"session_id": session_id})
    assert before_finish.status_code == 422
    assert _snapshot(database, session_id, plan["id"])["logs"] == []

    first_record = session["records"][0]
    for count, duration in ((1, 7), (2, 13)):
        update = client.post(
            "/api/session/update",
            json={
                "session_id": session_id,
                "exercise_id": first_id,
                "status": "pending",
                "sets_completed": count,
                "duration_seconds": duration,
            },
        )
        assert update.status_code == 200, update.text
        assert update.json()["record"]["status"] == "pending"
        assert update.json()["record"]["sets_completed"] == count
        assert update.json()["record"]["duration_seconds"] == duration

    # Omitted fields preserve facts already committed by a prior set update.
    preserved = client.post(
        "/api/session/update",
        json={"session_id": session_id, "exercise_id": first_id, "status": "pending"},
    )
    assert preserved.status_code == 200
    assert preserved.json()["record"]["sets_completed"] == 2
    assert preserved.json()["record"]["duration_seconds"] == 13

    completed_action = client.post(
        "/api/session/update",
        json={
            "session_id": session_id,
            "exercise_id": first_id,
            "status": "completed",
            "sets_completed": 3,
            "duration_seconds": 21,
        },
    )
    assert completed_action.status_code == 200, completed_action.text
    assert completed_action.json()["record"]["status"] == "completed"
    assert completed_action.json()["record"]["sets_completed"] == 3
    assert completed_action.json()["record"]["duration_seconds"] == 21
    replayed_action = client.post(
        "/api/session/update",
        json={
            "session_id": session_id,
            "exercise_id": first_id,
            "status": "completed",
            "sets_completed": 3,
            "duration_seconds": 21,
        },
    )
    assert replayed_action.status_code == 200, replayed_action.text
    assert replayed_action.json()["record"]["sets_completed"] == 3

    skipped_action = client.post(
        "/api/session/update",
        json={
            "session_id": session_id,
            "exercise_id": second_id,
            "status": "skipped",
            "sets_completed": 1,
            "duration_seconds": 4,
        },
    )
    assert skipped_action.status_code == 200, skipped_action.text
    assert skipped_action.json()["record"]["status"] == "skipped"
    assert skipped_action.json()["record"]["sets_completed"] == 1
    assert skipped_action.json()["record"]["duration_seconds"] == 4

    finished = client.post("/api/session/complete", json={"session_id": session_id})
    assert finished.status_code == 200, finished.text
    body = finished.json()
    assert body["status"] == "completed"
    assert body["session"]["status"] == "completed"
    assert body["summary"] == {
        "completed_records": 1,
        "skipped_records": 1,
        "completed_sets": 4,
        "duration_seconds": 25,
    }
    detailed_summary = client.get(f"/api/session/{session_id}/summary")
    assert detailed_summary.status_code == 200
    assert detailed_summary.json()["summary"]["completed_sets"] == 4

    retried_finish = client.post("/api/session/complete", json={"session_id": session_id})
    assert retried_finish.status_code == 200
    assert retried_finish.json()["status"] == "already_completed"
    snapshot = _snapshot(database, session_id, plan["id"])
    assert snapshot == {
        "session": {"id": session_id, "status": "completed"},
        "records": [
            {"exercise_id": first_id, "status": "completed", "sets_completed": 3, "duration_seconds": 21},
            {"exercise_id": second_id, "status": "skipped", "sets_completed": 1, "duration_seconds": 4},
        ],
        "logs": [{"action": "completed", "status": "completed", "session_id": session_id}],
    }

    EVIDENCE_DIR.mkdir(parents=True, exist_ok=True)
    (EVIDENCE_DIR / "api-sqlite-session-truth.json").write_text(
        json.dumps({"plan_id": plan["id"], "session_id": session_id, "snapshot": snapshot}, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def test_van13_inline_production_js_counts_groups_and_freezes_failed_retry_duration():
    script = textwrap.dedent(
        r"""
        const fs = require('fs');
        const vm = require('vm');
        const source = fs.readFileSync('static/index.html', 'utf8');
        function section(startMarker, endMarker) {
          const start = source.indexOf(startMarker);
          const end = source.indexOf(endMarker, start);
          if (start < 0 || end < 0) throw new Error(`missing ${startMarker}`);
          return source.slice(start, end);
        }
        function response(status, body) {
          return { ok: status >= 200 && status < 300, status, text: async () => JSON.stringify(body) };
        }
        let now = 100000;
        let updateMode = 'ok';
        const calls = [];
        const saves = [];
        const context = {
          console, Promise, JSON, Object, Array, Error, Math,
          Date: class extends Date { static now() { return now; } },
          setTimeout, clearTimeout, document: {},
          fetch: async (url, options = {}) => {
            const body = options.body ? JSON.parse(options.body) : null;
            calls.push({ url: String(url), body });
            if (String(url).includes('/api/session/update')) {
              if (updateMode === '500') return response(500, { detail: 'isolated update failure' });
              return response(200, { status: 'updated', record: { status: body.status, sets_completed: body.sets_completed, duration_seconds: body.duration_seconds } });
            }
            if (String(url).includes('/api/session/complete')) return response(200, { status: 'completed', session: { status: 'completed' } });
            return response(200, {});
          },
          v25Remote: { ready: true, exercises: [{ id: 11, name: '真实动作' }] },
          v25RemotePlanId: 7, v25RemotePlanPromise: null,
          v25RemoteSessionId: 8, v25RemoteSessionPromise: null,
          v25RemoteStepPromise: Promise.resolve(), v25RemoteCompleted: false,
          v25RemoteProgressPending: false, v25RemoteFinalUpdateConfirmed: false,
          v25RemoteStatusVerified: true, v25LocalDoneAwaitingVerification: false,
          todayPlan: [{ exerciseId: 11, name: '真实动作', sets: 3, time: 5 }],
          todayStepIndex: 0, todaySetIndex: 0, todayActionElapsedSeconds: 0,
          todayActionStartedAt: null, todaySkipped: [], todayRecordFacts: [], todayPendingProgress: null,
          todayStarted: false, todayDone: false,
          renderTodayPlan: () => {}, saveTrainingState: () => saves.push({ started: context.todayStarted, step: context.todayStepIndex, set: context.todaySetIndex, done: context.todayDone, pending: context.todayPendingProgress }),
          showToast: () => {}, clonePlain: (value) => Object.assign({}, value),
          formatDateKey: () => '2026-09-30', getToday: () => new Date('2026-09-30T00:00:00Z')
        };
        vm.createContext(context);
        vm.runInContext(section('function v25ApiFetch', 'function v25MigrationPreview'), context);
        vm.runInContext(section('function v25CurrentItem', 'function renderNewPlanModal'), context);
        context.showToast = () => {};
        async function run() {
          if (await context.advanceTodayTraining() !== true) throw new Error('start failed');
          if (context.todayDone || calls.some((call) => call.url.includes('/api/session/update') || call.url.includes('/api/session/complete'))) throw new Error('start wrote completion');
          now += 12000;
          if (await context.advanceTodayTraining() !== true) throw new Error('set 1 failed');
          now += 5000;
          if (await context.advanceTodayTraining() !== true) throw new Error('set 2 failed');
          now += 7000;
          if (await context.advanceTodayTraining() !== true) throw new Error('set 3 failed');
          const updates = calls.filter((call) => call.url.includes('/api/session/update'));
          if (updates.length !== 3) throw new Error(`expected 3 updates, got ${updates.length}`);
          if (updates.map((call) => call.body.sets_completed).join(',') !== '1,2,3') throw new Error('group counts are not monotonic');
          if (updates.map((call) => call.body.duration_seconds).join(',') !== '12,17,24') throw new Error('execution durations are not cumulative');
          if (updates[0].body.status !== 'pending' || updates[1].body.status !== 'pending' || updates[2].body.status !== 'completed') throw new Error('action completion happened before final set');
          if (!context.todayDone || context.todaySetIndex !== 0) throw new Error('final session state mismatch');

          const retry = Object.assign({}, context, {
            todayPlan: [{ exerciseId: 11, name: '真实动作', sets: 2, time: 5 }],
            todayStepIndex: 0, todaySetIndex: 0, todayActionElapsedSeconds: 0,
            todayActionStartedAt: 200000, todayStarted: true, todayDone: false,
            todayPendingProgress: null, todayRemoteProgressPending: false
          });
          vm.createContext(retry);
          vm.runInContext(section('function v25ApiFetch', 'function v25MigrationPreview'), retry);
          vm.runInContext(section('function v25CurrentItem', 'function renderNewPlanModal'), retry);
          retry.showToast = () => {};
          now = 212000;
          updateMode = '500';
          const firstFailure = await retry.advanceTodayTraining();
          if (firstFailure !== false || !retry.todayPendingProgress) throw new Error('failed update advanced state');
          const frozen = retry.todayPendingProgress.durationSeconds;
          now += 100000;
          updateMode = 'ok';
          if (await retry.advanceTodayTraining() !== true) throw new Error('retry did not recover');
          const retryUpdate = calls.filter((call) => call.url.includes('/api/session/update')).at(-1);
          if (retryUpdate.body.duration_seconds !== frozen) throw new Error('failed retry wait was counted twice');
          console.log(JSON.stringify({ PASS: true, updates, retry_duration_seconds: frozen, final: { done: context.todayDone, sets: context.todaySetIndex } }));
        }
        run().catch((error) => { console.error(error.stack || error); process.exit(1); });
        """
    )
    result = subprocess.run(["node", "-e", script], capture_output=True, text=True, cwd=Path(__file__).resolve().parents[1], timeout=30)
    EVIDENCE_DIR.mkdir(parents=True, exist_ok=True)
    (EVIDENCE_DIR / "inline-js-group-duration.json").write_text(result.stdout or result.stderr, encoding="utf-8")
    assert result.returncode == 0, result.stderr + "\n" + result.stdout
    assert '"PASS":true' in result.stdout


def test_van13_backend_facts_replay_time_and_name_fallback(client, app_modules):
    database, _main = app_modules
    db = database.SessionLocal()
    try:
        exercise = database.Exercise(
            name="VAN-13 未关联快照动作",
            category="VAN-13",
            difficulty="低",
            default_sets=2,
            default_reps="8次",
        )
        plan = database.WorkoutPlan(
            plan_date=date(2026, 12, 14),
            title="VAN-13 未关联快照",
            is_training_day=True,
            focus="name fallback",
        )
        db.add_all([exercise, plan])
        db.flush()
        db.add(
            database.WorkoutExercise(
                plan_id=plan.id,
                exercise_id=None,
                sort_order=1,
                name=exercise.name,
                description="",
                sets=2,
                duration_seconds=None,
                reps=8,
                video_url=None,
            )
        )
        db.commit()
        plan_id = plan.id
        exercise_id = exercise.id
    finally:
        db.close()

    started = client.post("/api/session/start", json={"plan_id": plan_id})
    assert started.status_code == 200, started.text
    session = started.json()["session"]
    session_id = session["id"]
    assert session["records"][0]["exercise_id"] == exercise_id

    first = client.post(
        "/api/session/update",
        json={
            "session_id": session_id,
            "exercise_id": exercise_id,
            "status": "pending",
            "sets_completed": 1,
            "duration_seconds": 11,
        },
    )
    assert first.status_code == 200
    terminal = client.post(
        "/api/session/update",
        json={
            "session_id": session_id,
            "exercise_id": exercise_id,
            "status": "completed",
            "sets_completed": 2,
            "duration_seconds": 23,
        },
    )
    assert terminal.status_code == 200

    db = database.SessionLocal()
    try:
        before = db.query(database.SessionRecord).filter_by(session_id=session_id).one().completed_at
    finally:
        db.close()
    time.sleep(0.02)
    replay = client.post(
        "/api/session/update",
        json={
            "session_id": session_id,
            "exercise_id": exercise_id,
            "status": "completed",
            "sets_completed": 2,
            "duration_seconds": 23,
        },
    )
    assert replay.status_code == 200
    db = database.SessionLocal()
    try:
        after = db.query(database.SessionRecord).filter_by(session_id=session_id).one().completed_at
    finally:
        db.close()
    assert after == before

    completed = client.post("/api/session/complete", json={"session_id": session_id})
    assert completed.status_code == 200
    assert completed.json()["summary"]["completed_sets"] == 2
    assert client.get(f"/api/session/current?plan_id={plan_id}").json()["session"] is None
    completed_facts = client.get(
        f"/api/session/current?plan_id={plan_id}&include_completed=true"
    )
    assert completed_facts.status_code == 200
    assert completed_facts.json()["session"]["status"] == "completed"
    assert completed_facts.json()["session"]["records"][0]["sets_completed"] == 2

    skipped_exercise = _create_exercise(client, "VAN-13 skip replay", 3)
    skipped_plan = _create_plan(client, [skipped_exercise], "2026-12-15")
    skipped_start = client.post("/api/session/start", json={"plan_id": skipped_plan["id"]})
    skipped_session_id = skipped_start.json()["session"]["id"]
    skipped_first = client.post(
        "/api/session/update",
        json={
            "session_id": skipped_session_id,
            "exercise_id": skipped_exercise,
            "status": "skipped",
            "sets_completed": 1,
            "duration_seconds": 9,
        },
    )
    assert skipped_first.status_code == 200
    db = database.SessionLocal()
    try:
        skipped_before = db.query(database.SessionRecord).filter_by(session_id=skipped_session_id).one().completed_at
    finally:
        db.close()
    time.sleep(0.02)
    skipped_replay = client.post(
        "/api/session/update",
        json={
            "session_id": skipped_session_id,
            "exercise_id": skipped_exercise,
            "status": "skipped",
            "sets_completed": 1,
            "duration_seconds": 9,
        },
    )
    assert skipped_replay.status_code == 200
    db = database.SessionLocal()
    try:
        skipped_after = db.query(database.SessionRecord).filter_by(session_id=skipped_session_id).one().completed_at
    finally:
        db.close()
    assert skipped_after == skipped_before

    EVIDENCE_DIR.mkdir(parents=True, exist_ok=True)
    (EVIDENCE_DIR / "api-edge-review.json").write_text(
        json.dumps(
            {
                "session_id": session_id,
                "name_fallback_exercise_id": exercise_id,
                "completed_at_stable": after == before,
                "skipped_completed_at_stable": skipped_after == skipped_before,
                "default_current": None,
                "include_completed_status": completed_facts.json()["session"]["status"],
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )


def test_van13_inline_reconcile_facts_and_terminal_skip_retry():
    script = textwrap.dedent(
        r"""
        const fs = require('fs');
        const vm = require('vm');
        const { JSDOM } = require(require('path').join(
          process.env.VAN13_DOM_DEPS || '/private/tmp/van13-jsdom-deps/node_modules',
          'jsdom'
        ));
        const source = fs.readFileSync('static/index.html', 'utf8');
        function section(startMarker, endMarker) {
          const start = source.indexOf(startMarker);
          const end = source.indexOf(endMarker, start);
          if (start < 0 || end < 0) throw new Error(`missing ${startMarker}`);
          return source.slice(start, end);
        }
        (async function run() {
        const plan = [
          { exerciseId: 11, name: 'A', sets: 2, time: 5 },
          { exerciseId: 12, name: 'B', sets: 3, time: 5 },
          { exerciseId: 13, name: 'C', sets: 1, time: 5 },
        ];
        const base = {
          console, Promise, JSON, Object, Array, Error, Math, Date,
          v25Remote: { ready: true, exercises: [] },
          v25RemotePlanId: 7, v25RemotePlanPromise: null,
          v25RemoteSessionId: 8, v25RemoteSessionPromise: null,
          v25RemoteStepPromise: Promise.resolve(), v25RemoteCompleted: false,
          v25RemoteProgressPending: false, v25RemoteFinalUpdateConfirmed: false,
          v25RemoteStatusVerified: true, v25LocalDoneAwaitingVerification: false,
          todayPlan: plan, todayStepIndex: 0, todaySetIndex: 0,
          todayActionElapsedSeconds: 0, todayActionStartedAt: 12345,
          todaySkipped: [], todayRecordFacts: [], todayPendingProgress: null,
          todayStarted: true, todayDone: false,
          renderTodayPlan: () => {}, saveTrainingState: () => {}, showToast: () => {},
          clonePlain: (value) => Object.assign({}, value),
          fetch: async (url, options = {}) => {
            const body = options.body ? JSON.parse(options.body) : {};
            if (String(url).includes('/api/session/update')) return { ok: true, status: 200, text: async () => JSON.stringify({ status: 'updated', record: { status: body.status, sets_completed: body.sets_completed, duration_seconds: body.duration_seconds } }) };
            return { ok: true, status: 200, text: async () => JSON.stringify({ status: 'completed', session: { status: 'completed' } }) };
          },
          formatDateKey: () => '2026-09-30', getToday: () => new Date('2026-09-30T00:00:00Z'),
        };
        vm.createContext(base);
        vm.runInContext(section('function v25ApiFetch', 'function v25MigrationPreview'), base);
        vm.runInContext(section('function v25ReconcileTodaySession', 'function v25ApplyCalendar'), base);
        const active = base.v25ReconcileTodaySession(
          { stepIndex: 0, setIndex: 1, actionStartedAt: 12345, pending: { index: 0, setsCompleted: 2, durationSeconds: 83, status: 'completed' } },
          plan, '真实计划', false, true, false,
          { status: 'in_progress', records: [
            { exercise_id: 11, status: 'completed', sets_completed: 2, duration_seconds: 83 },
            { exercise_id: 12, status: 'pending', sets_completed: 1, duration_seconds: 31 },
            { exercise_id: 13, status: 'pending', sets_completed: null, duration_seconds: null },
          ] }
        );
        if (active.stepIndex !== 1 || active.setIndex !== 1 || active.actionStartedAt !== null || active.pending !== null) throw new Error(`stale action state survived ${JSON.stringify(active)}`);
        if (active.records[0].status !== 'completed' || active.records[1].setsCompleted !== 1 || active.records[1].durationSeconds !== 31) throw new Error('backend facts not consumed');

        const fresh = base.v25ReconcileTodaySession(
          null, plan.slice(0, 2), '真实计划', false, true, false,
          { status: 'in_progress', records: [
            { exercise_id: 11, status: 'completed', sets_completed: 2, duration_seconds: 83 },
            { exercise_id: 12, status: 'skipped', sets_completed: 1, duration_seconds: 31 },
          ] }
        );
        if (!fresh.pending || fresh.pending.index !== 1 || fresh.pending.status !== 'skipped' || fresh.pending.setsCompleted !== 1) throw new Error(`terminal skipped retry missing ${JSON.stringify(fresh)}`);
        const completedFacts = base.v25ReconcileTodaySession(
          null, plan.slice(0, 2), '真实计划', false, true, true,
          { status: 'completed', records: [
            { exercise_id: 11, status: 'completed', sets_completed: 2, duration_seconds: 83 },
            { exercise_id: 12, status: 'skipped', sets_completed: 1, duration_seconds: 31 },
          ] }
        );
        if (!completedFacts.done || completedFacts.records[0].setsCompleted !== 2 || completedFacts.records[1].status !== 'skipped' || completedFacts.actionStartedAt !== null) throw new Error('fresh completed facts were not restored');
        const retry = Object.assign({}, base, {
          todayPlan: plan.slice(0, 2), todayStepIndex: fresh.stepIndex, todaySetIndex: fresh.setIndex,
          todayActionElapsedSeconds: fresh.actionElapsedSeconds, todayActionStartedAt: null,
          todayRecordFacts: fresh.records, todayPendingProgress: fresh.pending, todayStarted: true,
          todayDone: false, v25RemoteFinalUpdateConfirmed: false,
        });
        vm.createContext(retry);
        vm.runInContext(section('function v25ApiFetch', 'function v25MigrationPreview'), retry);
        vm.runInContext(section('function v25CurrentItem', 'function renderNewPlanModal'), retry);
        retry.showToast = () => {};
        const result = await retry.advanceTodayTraining();
        if (result !== true || !retry.todayDone || retry.todayRecordFacts[1].setsCompleted !== 1) throw new Error('terminal skipped complete retry failed');
        const renderDom = new JSDOM(source, { url: 'http://127.0.0.1:3000/' });
        const ids = {};
        ['todayPlanList', 'todayTitle', 'todayMeta', 'todaySummary', 'dayEmptyHero', 'dayHeroContent', 'dayHeroVideo', 'dayHeroProgress', 'dayDetailPanel', 'todayStatusPill', 'todayCountPill', 'startTodayBtn', 'skipTodayBtn', 'dayVideoName', 'dayVideoCap', 'dayVideoHint', 'dayVideoThumb', 'dayProgressTrack', 'dayProgressSteps', 'dayProgressLabel', 'dayProgressStat', 'dayProgressCaption', 'todayEditMeta'].forEach((id) => { ids[id] = renderDom.window.document.getElementById(id); });
        const view = {
          console, Promise, JSON, Object, Array, Error, Math, Date,
          document: renderDom.window.document,
          todayPlan: plan, todayStepIndex: 2, todaySetIndex: 0, todayActionElapsedSeconds: 0,
          todayActionStartedAt: null, todaySkipped: [1], todayRecordFacts: [
            { status: 'completed', setsCompleted: 2, durationSeconds: 83 },
            { status: 'skipped', setsCompleted: 1, durationSeconds: 31 },
            { status: 'completed', setsCompleted: 1, durationSeconds: 42 },
          ], todayPendingProgress: null, todayStarted: true, todayDone: true,
          todayIsRest: false, v25RemoteProgressPending: false,
          v25UiDoneConfirmed: () => true, aggregateIntensity: () => '低强度',
          getTodayCurrentName: () => 'C', exerciseDetails: {}, isVerifiedVideo: () => false,
          escapeHtml: (value) => String(value), todayPlanEl: (id) => ids[id],
        };
        vm.createContext(view);
        vm.runInContext(section('function v25ClearChildren', 'function openModal'), view);
        vm.runInContext(section('function todayRecordFact', 'function startPlan'), view);
        view.todayPlanEl = (id) => ids[id];
        view.renderTodayPlan();
        if (!ids.todayPlanList.innerHTML.includes('2 / 2 组 · 已完成') || !ids.todayPlanList.innerHTML.includes('1 / 3 组 · 已跳过') || !ids.todayPlanList.innerHTML.includes('实际 42 秒')) throw new Error(`render facts mismatch ${ids.todayPlanList.innerHTML}`);
        if (!ids.todaySummary.textContent.includes('实际执行 156 秒') || !ids.todaySummary.textContent.includes('完成组 4')) throw new Error(`summary facts mismatch ${ids.todaySummary.textContent}`);
        view.todayRecordFacts = view.todayRecordFacts.map((record) => Object.assign({}, record, { durationSeconds: null }));
        view.renderTodayPlan();
        if (!ids.todaySummary.textContent.includes('实际时长未知')) throw new Error(`unknown duration was presented as zero ${ids.todaySummary.textContent}`);
        console.log(JSON.stringify({ PASS: true, active, fresh, completedFacts, final: { done: retry.todayDone, records: retry.todayRecordFacts }, rendered: ids.todaySummary.textContent }));
        })().catch((error) => { console.error(error.stack || error); process.exit(1); });
        """
    )
    result = subprocess.run(["node", "-e", script], capture_output=True, text=True, cwd=Path(__file__).resolve().parents[1], timeout=30)
    EVIDENCE_DIR.mkdir(parents=True, exist_ok=True)
    (EVIDENCE_DIR / "reconciliation-review.json").write_text(result.stdout or result.stderr, encoding="utf-8")
    assert result.returncode == 0, result.stderr + "\n" + result.stdout
    assert '"PASS":true' in result.stdout


def test_van13_real_dom_terminal_progress_uses_record_facts_after_index_reset():
    """真实 jsdom DOM 专项；依赖可临时安装：

    npm install --prefix /private/tmp/van13-jsdom-deps --no-save --no-package-lock jsdom@26
    VAN13_DOM_DEPS=/private/tmp/van13-jsdom-deps/node_modules pytest ...
    """
    script = textwrap.dedent(
        r"""
        const fs = require('fs');
        const vm = require('vm');
        const path = require('path');
        const { JSDOM } = require(path.join(
          process.env.VAN13_DOM_DEPS || '/private/tmp/van13-jsdom-deps/node_modules',
          'jsdom'
        ));
        const source = fs.readFileSync('static/index.html', 'utf8');
        function section(startMarker, endMarker) {
          const start = source.indexOf(startMarker);
          const end = source.indexOf(endMarker, start);
          if (start < 0 || end < 0) throw new Error(`missing ${startMarker}`);
          return source.slice(start, end);
        }
        function renderCase(testCase) {
          const dom = new JSDOM(source);
          const context = {
            console, Promise, JSON, Object, Array, Error, Math, Number, String, Date,
            document: dom.window.document,
            todayPlan: testCase.plan,
            todayStepIndex: testCase.stepIndex,
            todaySetIndex: testCase.setIndex,
            todayActionElapsedSeconds: 0,
            todayActionStartedAt: null,
            todaySkipped: testCase.skipped,
            todayRecordFacts: testCase.facts,
            todayPendingProgress: null,
            todayStarted: true,
            todayDone: true,
            todayIsRest: false,
            v25RemoteStatusVerified: true,
            v25RemoteProgressPending: false,
            exerciseDetails: {},
            isVerifiedVideo: () => false,
            saveTrainingState: () => {},
            resetStartBtn: () => {}
          };
          vm.createContext(context);
          vm.runInContext(section('function escapeHtml', 'function openModal'), context);
          vm.runInContext(section('function getTodayCurrentName', 'function startPlan'), context);
          vm.runInContext(section('function v25UiDoneConfirmed', 'function v25ResetUnverifiedDone'), context);
          context.renderTodayPlan();
          const document = context.document;
          const stat = document.getElementById('dayProgressStat').textContent;
          const status = document.getElementById('todayStatusPill').textContent;
          const caption = document.getElementById('dayProgressCaption').textContent;
          const summary = document.getElementById('todaySummary').textContent;
          const count = document.getElementById('todayCountPill').textContent;
          if (stat !== testCase.expectedStat) throw new Error(`${testCase.name} stat: ${stat}`);
          if (status !== '已完成') throw new Error(`${testCase.name} status: ${status}`);
          if (caption !== `当前动作：${testCase.expectedCurrent}`) throw new Error(`${testCase.name} caption: ${caption}`);
          if (!summary.includes(testCase.expectedSummary)) throw new Error(`${testCase.name} summary: ${summary}`);
          if (count !== testCase.expectedCount) throw new Error(`${testCase.name} count: ${count}`);
          return { stat, status, caption, summary, count };
        }
        const cases = [
          {
            name: 'single action, three groups',
            plan: [{ name: '三组动作', sets: 3, time: 5, spec: '3 组 · 8 次' }],
            // Final completion resets the active indexes to 0; facts remain authoritative.
            stepIndex: 0, setIndex: 0, skipped: [],
            facts: [{ status: 'completed', setsCompleted: 3, durationSeconds: 29 }],
            expectedStat: '训练已结束 · 已处理 1 / 1 动作 · 共完成 3 组',
            expectedCurrent: '三组动作',
            expectedSummary: '完成动作 1 · 跳过 0 · 完成组 3',
            expectedCount: '1 动作 · 0 跳过'
          },
          {
            name: 'partial skip',
            plan: [
              { name: '完成动作', sets: 3, time: 5, spec: '3 组 · 8 次' },
              { name: '跳过动作', sets: 2, time: 5, spec: '2 组 · 8 次' }
            ],
            // The final action is skipped and the active indexes are reset/clamped to its slot.
            stepIndex: 1, setIndex: 0, skipped: [1],
            facts: [
              { status: 'completed', setsCompleted: 3, durationSeconds: 29 },
              { status: 'skipped', setsCompleted: 1, durationSeconds: 4 }
            ],
            expectedStat: '训练已结束 · 已处理 2 / 2 动作 · 共完成 4 组',
            expectedCurrent: '跳过动作',
            expectedSummary: '完成动作 1 · 跳过 1 · 完成组 4',
            expectedCount: '2 动作 · 1 跳过'
          }
        ];
        const rendered = cases.map(renderCase);
        console.log(JSON.stringify({ PASS: true, rendered }));
        """
    )
    result = subprocess.run(
        ["node", "-e", script],
        capture_output=True,
        text=True,
        cwd=Path(__file__).resolve().parents[1],
        timeout=30,
        env={**os.environ, "VAN13_DOM_DEPS": os.environ.get("VAN13_DOM_DEPS", "/private/tmp/van13-jsdom-deps/node_modules")},
    )
    EVIDENCE_DIR.mkdir(parents=True, exist_ok=True)
    (EVIDENCE_DIR / "real-dom-terminal-progress.json").write_text(result.stdout or result.stderr, encoding="utf-8")
    assert result.returncode == 0, result.stderr + "\n" + result.stdout
    assert '"PASS":true' in result.stdout
