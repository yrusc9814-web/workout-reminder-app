"""Focused VAN-17 frontend context and late-response regressions."""
from __future__ import annotations

from pathlib import Path
import subprocess
import textwrap


APP_DIR = Path(__file__).resolve().parents[1]


def _run_node(script: str) -> str:
    result = subprocess.run(
        ["node", "-e", textwrap.dedent(script)],
        cwd=APP_DIR,
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert result.returncode == 0, result.stderr + "\n" + result.stdout
    return result.stdout


def test_active_session_wins_over_completed_day_and_keeps_partial_facts():
    output = _run_node(
        r'''
        const fs = require('fs'), vm = require('vm');
        const source = fs.readFileSync('static/index.html', 'utf8');
        const start = source.indexOf('function v25ReconcileTodaySession');
        const end = source.indexOf('function v25UiDoneConfirmed', start);
        const context = {
          console, Date, clonePlain: (value) => Object.assign({}, value),
          todaySessionKey: '2026-10-03',
        };
        vm.createContext(context);
        vm.runInContext(source.slice(start, end), context);
        const result = context.v25ReconcileTodaySession(
          null,
          [{ id: 1, name: '动作', exerciseId: 9, sets: 2, reps: 8, time: 1 }],
          '第二轮', false, true, true,
          { id: 2, plan_id: 41, status: 'in_progress', records: [
            { exercise_id: 9, status: 'pending', sets_completed: 1, duration_seconds: 30 }
          ] }
        );
        if (result.done || result.records[0].setsCompleted !== 1 || result.records[0].durationSeconds !== 30 || result.setIndex !== 1) {
          throw new Error(JSON.stringify(result));
        }
        console.log(JSON.stringify({ PASS: true, done: result.done, sets: result.records[0].setsCompleted, duration: result.records[0].durationSeconds }));
        ''',
    )
    assert '"PASS":true' in output.replace(" ", "")


def test_frontend_duration_summary_preserves_completed_unknown_zero_but_filters_noop_skip():
    output = _run_node(
        r'''
        const fs = require('fs'), vm = require('vm');
        const source = fs.readFileSync('static/index.html', 'utf8');
        const start = source.indexOf('function todayExecutionSummary');
        const end = source.indexOf('function renderTodayPlan', start);
        const context = {
          console, Number,
          todayRecordFacts: [
            { status: 'completed', setsCompleted: 0, durationSeconds: null },
            { status: 'completed', setsCompleted: 0, durationSeconds: 0 },
            { status: 'skipped', setsCompleted: 0, durationSeconds: null },
            { status: 'skipped', setsCompleted: 0, durationSeconds: 0 },
            { status: 'skipped', setsCompleted: 0, durationSeconds: 12 },
            { status: 'pending', setsCompleted: 1, durationSeconds: null },
          ],
        };
        vm.createContext(context);
        vm.runInContext(source.slice(start, end), context);
        const summary = context.todayExecutionSummary();
        if (summary.durationSeconds !== 12 || summary.durationKnownRecords !== 2 || summary.durationUnknownRecords !== 2 || summary.completedSets !== 1) throw new Error(JSON.stringify(summary));
        console.log(JSON.stringify({ PASS: true, summary }));
        ''',
    )
    assert '"PASS":true' in output.replace(" ", "")


def test_foreign_active_session_cannot_replace_selected_date_context():
    output = _run_node(
        r'''
        const fs = require('fs'), vm = require('vm');
        const source = fs.readFileSync('static/index.html', 'utf8');
        const start = source.indexOf('function v25ResolveBootSessionContext');
        const end = source.indexOf('function v25EnsureRemoteSession', start);
        const context = { console, isValidDateKey: (value) => /^\d{4}-\d{2}-\d{2}$/.test(value) };
        vm.createContext(context);
        vm.runInContext(source.slice(start, end), context);
        const selected = context.v25ResolveBootSessionContext(
          { id: 7, plan_id: 41, status: 'in_progress', date: '2026-10-03' },
          { id: 41, date: '2026-10-03', title: '今日计划', items: [{ exercise_id: 9, name: '今日动作', sets: 2 }] },
          42,
          '2026-10-04'
        );
        if (selected.targetActive || !selected.foreignActive || selected.activeSession !== null) throw new Error(JSON.stringify(selected));
        console.log(JSON.stringify({ PASS: true, foreign: selected.foreignActive }));
        ''',
    )
    assert '"PASS":true' in output.replace(" ", "")


def test_late_progress_response_is_ignored_after_context_switch():
    output = _run_node(
        r'''
        const fs = require('fs'), vm = require('vm');
        const source = fs.readFileSync('static/index.html', 'utf8');
        const start = source.indexOf('function v25SubmitProgress');
        const end = source.indexOf('function advanceTodayTraining', start);
        let release;
        const context = {
          console, Promise, Date, String, Number, Math,
          todayPlan: [{ sets: 2 }], todayStepIndex: 0, todaySetIndex: 1,
          todayActionElapsedSeconds: 10, todayActionStartedAt: null,
          todayPendingProgress: null, todayDone: false, todayStarted: true,
          todayRecordFacts: [], todaySkipped: [], todaySessionKey: '2026-10-03',
          v25ActiveContextGeneration: 1, v25RemotePlanId: 41,
          v25RemoteProgressPending: false, v25RemoteStatusVerified: false,
          v25LocalDoneAwaitingVerification: false, v25RemoteFinalUpdateConfirmed: false,
          v25TodayKey: () => '2026-10-03',
          v25ActiveSessionDateKey: () => context.activeDate,
          v25TargetSets: () => 2,
          v25ProgressPayload: () => ({ index: 0, setsCompleted: 2, durationSeconds: 20, status: 'completed', finalAction: true }),
          v25QueueRemoteProgress: () => new Promise((resolve) => { release = resolve; }),
          v25CaptureExecutionContext: () => ({ dateKey: context.activeDate, planId: context.v25RemotePlanId, sessionId: null, generation: context.v25ActiveContextGeneration, queue: Promise.resolve() }),
          v25ExecutionContextOwns: (owner) => owner.dateKey === context.activeDate && owner.generation === context.v25ActiveContextGeneration && String(owner.planId) === String(context.v25RemotePlanId),
          v25ApplyProgressSuccess: () => { throw new Error('late response mutated active context'); },
          v25RefreshCanonical: () => Promise.resolve(),
          renderTodayPlan: () => {}, saveTrainingState: () => {}, showToast: () => {},
          v25Remote: { monthRequests: {} }, calendarDisplayYear: 2026,
        };
        context.activeDate = '2026-10-03';
        vm.createContext(context);
        vm.runInContext(source.slice(start, end), context);
        const request = context.v25SubmitProgress('completed');
        context.activeDate = '2026-10-04';
        context.v25ActiveContextGeneration = 2;
        context.v25RemotePlanId = 42;
        release({ update: { record: { status: 'completed', sets_completed: 2, duration_seconds: 20 } }, complete: { status: 'completed' } });
        request.then((result) => {
          if (context.todayDone || context.todayRecordFacts.length) throw new Error(JSON.stringify({ result, todayDone: context.todayDone, facts: context.todayRecordFacts }));
          console.log(JSON.stringify({ PASS: true, result, date: context.activeDate }));
        }).catch((error) => { console.error(error.stack || error); process.exit(1); });
        ''',
    )
    assert '"PASS":true' in output.replace(" ", "")


def test_changed_date_inside_current_week_invalidates_week_cache():
    output = _run_node(
        r'''
        const fs = require('fs'), vm = require('vm');
        const source = fs.readFileSync('static/index.html', 'utf8');
        const start = source.indexOf('function v25RefreshCanonical');
        const end = source.indexOf('function v25SaveCanonicalPlan', start);
        const calls = [];
        const context = {
          console, Promise, Object, Array, String, Number, Math, Date,
          v25Remote: { loadedMonths: {}, planDays: {}, monthStatus: {}, monthRequests: {}, statsByMonth: {}, detailByMonth: {}, today: { id: 41 } },
          v25MonthForDate: (key) => String(key).slice(0, 7), v25TodayKey: () => '2026-10-03',
          v25ActiveSessionDateKey: () => '2026-10-04', v25ActiveContextGeneration: 1, v25RemotePlanId: 42,
          v25MonthRequestSequence: 0, v25WeekRequestSequence: 0, v25WeekRequestOwner: 0, v25WeekRequestDateKey: '',
          getToday: () => new Date('2026-10-03T12:00:00Z'), formatDateKey: (d) => d.toISOString().slice(0, 10),
          getCurrentWeekDates: () => ['2026-09-27','2026-09-28','2026-09-29','2026-09-30','2026-10-01','2026-10-02','2026-10-03'].map((key) => new Date(key + 'T12:00:00Z')),
          v25RefreshMonth: (month) => { calls.push('month:' + month); return Promise.resolve({ month }); },
          v25ApiFetch: (path) => { calls.push(path); return Promise.resolve(path.indexOf('/stats/week/') >= 0 ? { days: [] } : {}); },
          v25ApplyWeekStats: () => {}, renderTodayPlan: () => {}, renderWeek: () => {}, renderCalendarMonth: () => {}, saveTrainingState: () => {},
          v25DisplayedMonthToken: () => '2026-10', v25ApplyStats: () => {},
        };
        vm.createContext(context);
        vm.runInContext(source.slice(start, end), context);
        context.v25RefreshCanonical(['2026-10-03', '2026-10-05']).then(() => {
          if (!calls.includes('/api/stats/week/detail?date=2026-10-03')) throw new Error(JSON.stringify(calls));
          console.log(JSON.stringify({ PASS: true, week: calls.filter((call) => call.indexOf('/stats/week/') >= 0) }));
        }).catch((error) => { console.error(error.stack || error); process.exit(1); });
        ''',
    )
    assert '"PASS":true' in output.replace(" ", "")


def test_full_page_deferred_progress_stays_bound_to_old_session_after_date_switch():
    result = subprocess.run(
        ["node", "tests/van17_deferred_context_behavior.js"],
        cwd=APP_DIR,
        capture_output=True,
        text=True,
        timeout=45,
    )
    assert result.returncode == 0, result.stderr + "\n" + result.stdout
    assert '"PASS":true' in result.stdout.replace(" ", "")


def test_full_page_unseen_resume_keeps_backend_partial_sets_and_duration():
    result = subprocess.run(
        ["node", "tests/van17_unseen_resume_behavior.js"],
        cwd=APP_DIR,
        capture_output=True,
        text=True,
        timeout=45,
    )
    assert result.returncode == 0, result.stderr + "\n" + result.stdout
    assert '"PASS":true' in result.stdout.replace(" ", "")


def test_full_page_selected_date_failure_does_not_fallback_to_today_plan():
    result = subprocess.run(
        ["node", "tests/van17_selected_date_failure_behavior.js"],
        cwd=APP_DIR,
        capture_output=True,
        text=True,
        timeout=45,
    )
    assert result.returncode == 0, result.stderr + "\n" + result.stdout
    assert '"PASS":true' in result.stdout.replace(" ", "")


def test_full_page_deferred_local_plan_save_cannot_reactivate_old_date():
    result = subprocess.run(
        ["node", "tests/van17_plan_save_deferred_behavior.js"],
        cwd=APP_DIR,
        capture_output=True,
        text=True,
        timeout=45,
    )
    assert result.returncode == 0, result.stderr + "\n" + result.stdout
    assert '"PASS":true' in result.stdout.replace(" ", "")


def test_full_page_failed_plan_edit_does_not_drop_held_progress_response():
    result = subprocess.run(
        ["node", "tests/van17_failed_edit_inflight_behavior.js"],
        cwd=APP_DIR,
        capture_output=True,
        text=True,
        timeout=45,
    )
    assert result.returncode == 0, result.stderr + "\n" + result.stdout
    assert '"PASS":true' in result.stdout.replace(" ", "")


def test_full_page_successful_plan_save_readback_failure_enters_error_and_retries_same_date():
    result = subprocess.run(
        ["node", "tests/van17_save_readback_retry_behavior.js"],
        cwd=APP_DIR,
        capture_output=True,
        text=True,
        timeout=45,
    )
    assert result.returncode == 0, result.stderr + "\n" + result.stdout
    assert '"PASS":true' in result.stdout.replace(" ", "")


def test_full_page_snapshot_replacement_resets_old_session_but_metadata_save_preserves_partial_facts():
    result = subprocess.run(
        ["node", "tests/van17_snapshot_binding_behavior.js"],
        cwd=APP_DIR,
        capture_output=True,
        text=True,
        timeout=45,
    )
    assert result.returncode == 0, result.stderr + "\n" + result.stdout
    assert '"PASS":true' in result.stdout.replace(" ", "")


def test_full_page_postpone_and_import_readback_failures_enter_error_and_retry():
    result = subprocess.run(
        ["node", "tests/van17_readback_mutation_retry_behavior.js"],
        cwd=APP_DIR,
        capture_output=True,
        text=True,
        timeout=45,
    )
    assert result.returncode == 0, result.stderr + "\n" + result.stdout
    assert '"PASS":true' in result.stdout.replace(" ", "")
