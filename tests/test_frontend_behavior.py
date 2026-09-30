"""Real mock-fetch frontend behavior tests (not source-string assertions)."""
from __future__ import annotations

import subprocess
from pathlib import Path

APP_DIR = Path(__file__).resolve().parents[1]


def _run(script: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["node", "-e", script],
        capture_output=True,
        text=True,
        cwd=str(APP_DIR),
        timeout=30,
    )


def _assert_ok(result: subprocess.CompletedProcess):
    assert result.returncode == 0, result.stderr + "\n" + result.stdout
    assert "PASS" in result.stdout


def test_empty_api_does_not_load_demo_data():
    script = r"""
const { createHarness } = require('./tests/frontend_behavior_harness.js');
const h = createHarness();
const result = h.stateFromApiPayload({ exercises: [], templates: [], days: [], logs: [] });
if (result.exercises.length || result.templates.length || Object.keys(result.schedule).length) {
  console.error('demo fallback', result);
  process.exit(1);
}
console.log('PASS');
"""
    _assert_ok(_run(script))


def test_api_init_template_binding_correct():
    script = r"""
const { createHarness } = require('./tests/frontend_behavior_harness.js');
const h = createHarness();
const result = h.stateFromApiPayload({
  exercises: [{ id: 1, name: 'A' }],
  templates: [{ id: 9, name: 'T', exercises: [{ id: 1 }] }],
  days: [{ date: '2026-08-03', is_training: true, template_id: 9, notes: 'n' }],
});
if (result.schedule['2026-08-03'].templateId !== '9') {
  console.error(result.schedule);
  process.exit(1);
}
const noGuess = h.apiPlanToScheduleEntry({ is_training: true, template_id: null });
if (noGuess.templateId !== undefined) process.exit(2);
console.log('PASS');
"""
    _assert_ok(_run(script))


def test_plan_edit_uses_target_month_and_template_payload():
    script = r"""
(async () => {
  const { createHarness } = require('./tests/frontend_behavior_harness.js');
  const h = createHarness({
    fetchImpl: async (url, options = {}) => {
      if (String(url).includes('/api/plans/month?month=2026-08')) {
        return { ok: true, status: 200, json: async () => ({ days: [{ date: '2026-08-03', id: 42, is_training: true }] }) };
      }
      if (String(url) === '/api/plans/42' && (options.method || '').toUpperCase() === 'PUT') {
        return { ok: true, status: 200, json: async () => ({ id: 42 }) };
      }
      return { ok: false, status: 500, json: async () => ({ detail: 'unexpected ' + url }) };
    }
  });
  h.state = { exercises: [], templates: [{ id: '3', exerciseIds: ['1'] }], schedule: {}, logs: [] };
  const res = await h.savePlanFromForm({ date: '2026-08-03', type: 'training', templateId: '3', note: 'hello' });
  if (!res.ok) { console.error(res, h.calls); process.exit(1); }
  const monthCall = h.calls.find(c => c.url.includes('/api/plans/month?month=2026-08'));
  const putCall = h.calls.find(c => c.url === '/api/plans/42' && c.method === 'PUT');
  if (!monthCall) process.exit(2);
  if (!putCall || putCall.body.template_id !== 3 || putCall.body.notes !== 'hello') {
    console.error(putCall);
    process.exit(3);
  }
  if (h.state.schedule['2026-08-03'].templateId !== '3') process.exit(4);
  console.log('PASS');
})().catch((e) => { console.error(e); process.exit(99); });
"""
    _assert_ok(_run(script))


def test_plan_save_failure_does_not_update_state_or_close_dialog():
    script = r"""
(async () => {
  const { createHarness } = require('./tests/frontend_behavior_harness.js');
  const h = createHarness({
    fetchImpl: async (url) => {
      if (String(url).includes('/api/plans/month')) {
        return { ok: true, status: 200, json: async () => ({ days: [{ date: '2026-08-03', id: 42 }] }) };
      }
      return { ok: false, status: 500, json: async () => ({ detail: 'fail' }) };
    }
  });
  h.state.schedule['2026-08-03'] = { type: 'rest', status: 'pending', note: 'old' };
  h.dialogOpen = true;
  const res = await h.savePlanFromForm({ date: '2026-08-03', type: 'training', templateId: '3', note: 'new' });
  if (res.ok) process.exit(1);
  if (h.state.schedule['2026-08-03'].note !== 'old') process.exit(2);
  if (h.dialogOpen !== true) process.exit(3);
  if (!h.toast || h.toast.type !== 'error') process.exit(4);
  console.log('PASS');
})().catch((e) => { console.error(e); process.exit(99); });
"""
    _assert_ok(_run(script))


def test_video_save_failure_does_not_update_local_state():
    script = r"""
(async () => {
  const { createHarness } = require('./tests/frontend_behavior_harness.js');
  const h = createHarness({
    fetchImpl: async () => ({ ok: false, status: 500, json: async () => ({ detail: 'nope' }) })
  });
  h.state.exercises = [{ id: '1', name: 'A', videos: [] }];
  h.dialogOpen = true;
  const res = await h.saveVideoFromForm({ exerciseId: '1', url: 'https://www.bilibili.com/video/BV1xx411c7mD' });
  if (res.ok) process.exit(1);
  if ((h.state.exercises[0].videos || []).length !== 0) process.exit(2);
  if (h.dialogOpen !== true) process.exit(3);
  console.log('PASS');
})().catch((e) => { console.error(e); process.exit(99); });
"""
    _assert_ok(_run(script))


def test_skip_waits_for_backend_before_next_and_keeps_on_failure():
    script = r"""
(async () => {
  const { createHarness } = require('./tests/frontend_behavior_harness.js');
  let mode = 'fail';
  const h = createHarness({
    fetchImpl: async (url) => {
      if (String(url).includes('/api/session/update')) {
        if (mode === 'fail') return { ok: false, status: 500, json: async () => ({ detail: 'x' }) };
        return { ok: true, status: 200, json: async () => ({ status: 'updated' }) };
      }
      if (String(url).includes('/api/session/complete')) {
        return { ok: true, status: 200, json: async () => ({ status: 'completed' }) };
      }
      return { ok: true, status: 200, json: async () => ({}) };
    }
  });
  h.session = {
    backendSession: { id: 7 },
    currentExerciseIndex: 0,
    currentSetIndex: 0,
    completed: [],
    skipped: [],
    exercises: [
      { id: '1', exercise_id: 1, defaultSets: 2 },
      { id: '2', exercise_id: 2, defaultSets: 1 },
    ],
  };
  const fail = await h.skipExercise();
  if (fail.ok || fail.advanced || h.session.currentExerciseIndex !== 0) {
    console.error('fail path', fail, h.session);
    process.exit(1);
  }
  mode = 'ok';
  const ok = await h.skipExercise();
  if (!ok.ok || !ok.advanced || h.session.currentExerciseIndex !== 1) {
    console.error('ok path', ok, h.session);
    process.exit(2);
  }
  console.log('PASS');
})().catch((e) => { console.error(e); process.exit(99); });
"""
    _assert_ok(_run(script))


def test_last_skipped_request_precedes_complete():
    script = r"""
(async () => {
  const { createHarness } = require('./tests/frontend_behavior_harness.js');
  const h = createHarness({
    fetchImpl: async (url) => {
      if (String(url).includes('/api/session/update') || String(url).includes('/api/session/complete')) {
        return { ok: true, status: 200, json: async () => ({ status: 'ok' }) };
      }
      return { ok: true, status: 200, json: async () => ({}) };
    }
  });
  h.session = {
    backendSession: { id: 9 },
    currentExerciseIndex: 1,
    currentSetIndex: 0,
    completed: [],
    skipped: [],
    exercises: [
      { id: '1', exercise_id: 1, defaultSets: 1 },
      { id: '2', exercise_id: 2, defaultSets: 1 },
    ],
  };
  const res = await h.skipExercise();
  if (!res.finished) { console.error(res, h.calls); process.exit(1); }
  const urls = h.calls.map(c => c.url + ':' + c.method);
  const upd = urls.findIndex(u => u.includes('/api/session/update:POST'));
  const cmp = urls.findIndex(u => u.includes('/api/session/complete:POST'));
  if (upd < 0 || cmp < 0 || !(upd < cmp)) {
    console.error(urls);
    process.exit(2);
  }
  if (h.calls[upd].body.status !== 'skipped') process.exit(3);
  console.log('PASS');
})().catch((e) => { console.error(e); process.exit(99); });
"""
    _assert_ok(_run(script))


def test_complete_failure_keeps_session():
    script = r"""
(async () => {
  const { createHarness } = require('./tests/frontend_behavior_harness.js');
  const h = createHarness({
    fetchImpl: async () => ({ ok: false, status: 500, json: async () => ({ detail: 'boom' }) })
  });
  h.session = { backendSession: { id: 3 }, exercises: [], completed: [], skipped: [] };
  const res = await h.finishTraining('done');
  if (res.ok || res.sessionCleared || !h.session) process.exit(1);
  if (!res.canRetry) process.exit(2);
  console.log('PASS');
})().catch((e) => { console.error(e); process.exit(99); });
"""
    _assert_ok(_run(script))


def test_complete_set_does_not_advance_on_failure_and_blocks_double_click():
    script = r"""
(async () => {
  const { createHarness } = require('./tests/frontend_behavior_harness.js');
  const h = createHarness({
    fetchImpl: async () => {
      await new Promise((r) => setTimeout(r, 30));
      return { ok: false, status: 500, json: async () => ({ detail: 'x' }) };
    }
  });
  h.session = {
    backendSession: { id: 1 },
    currentExerciseIndex: 0,
    currentSetIndex: 0,
    totalSetsDone: 0,
    completed: [],
    skipped: [],
    exercises: [{ id: '1', exercise_id: 1, defaultSets: 3 }],
  };
  const p1 = h.completeSet();
  const p2 = h.completeSet();
  const [a, b] = await Promise.all([p1, p2]);
  if (!(a.ok === false && a.advanced === false)) process.exit(1);
  if (!b.skipped) process.exit(2);
  if (h.session.currentSetIndex !== 0 || h.session.totalSetsDone !== 0) process.exit(3);
  console.log('PASS');
})().catch((e) => { console.error(e); process.exit(99); });
"""
    _assert_ok(_run(script))


def test_restore_defaults_dry_run_then_confirm_and_cancel():
    script = r"""
(async () => {
  const { createHarness } = require('./tests/frontend_behavior_harness.js');
  const h1 = createHarness({
    confirmImpl: () => false,
    fetchImpl: async (url, options = {}) => {
      const body = options.body ? JSON.parse(options.body) : {};
      if (String(url).includes('/api/data/restore-defaults') && body.confirm === false) {
        return { ok: true, status: 200, json: async () => ({ status: 'dry_run', current_state: { plans: 12, exercises: 5, templates: 1, sessions: 0, logs: 2 } }) };
      }
      return { ok: true, status: 200, json: async () => ({ status: 'restored' }) };
    }
  });
  const cancelled = await h1.resetToDefaults({ userConfirms: true });
  if (!cancelled.cancelled) process.exit(1);
  if (h1.calls.length !== 1 || h1.calls[0].body.confirm !== false) process.exit(2);

  const h2 = createHarness({
    confirmImpl: () => true,
    fetchImpl: async (url, options = {}) => {
      const body = options.body ? JSON.parse(options.body) : {};
      if (body.confirm === false) return { ok: true, status: 200, json: async () => ({ status: 'dry_run', current_state: { plans: 1, exercises: 1, templates: 1, sessions: 0, logs: 0 } }) };
      if (body.confirm === true) return { ok: true, status: 200, json: async () => ({ status: 'restored' }) };
      return { ok: false, status: 500, json: async () => ({}) };
    }
  });
  const ok = await h2.resetToDefaults({ userConfirms: true });
  if (!ok.ok) process.exit(3);
  if (h2.calls.length !== 2) process.exit(4);
  if (h2.calls[0].body.confirm !== false || h2.calls[1].body.confirm !== true || h2.calls[1].body.backup !== true) process.exit(5);
  console.log('PASS');
})().catch((e) => { console.error(e); process.exit(99); });
"""
    _assert_ok(_run(script))


def test_van10_frontend_snapshot_preserves_fields_and_rejects_offline_save():
    """Execute the v25 snapshot helpers from the real page source, not a string probe."""
    script = r"""
const fs = require('fs');
const source = fs.readFileSync('static/index.html', 'utf8');
var v25Remote = { ready: false, exercises: [] };
function v25RemoteExerciseByName() { return null; }
const helperStart = source.indexOf('function v25Has(');
const helperEnd = source.indexOf('function v25PlanPayload(');
eval(source.slice(helperStart, helperEnd));
const textStart = source.indexOf('function v25ItemText(');
const textEnd = source.indexOf('function v25PlanToUi(');
eval(source.slice(textStart, textEnd));

const first = {
  id: 91,
  exercise_id: 7,
  name: '保真动作',
  sets: 4,
  reps: 8,
  duration_seconds: 30,
  notes: '保留备注',
  spec: '4 组 · 8 次 · 30 秒',
  video_url: 'https://example.test/original',
};
const second = {
  id: 92,
  exercise_id: 8,
  name: '第二动作',
  sets: 2,
  reps: null,
  duration_seconds: null,
  notes: null,
  spec: '2 组',
};
const parsed = [first, second].map(v25ParseUiItem);
const survivor = parsed.filter(item => item.name !== '第二动作')[0];
if (survivor.id !== 91 || survivor.exercise_id !== 7 || survivor.sets !== 4 || survivor.reps !== 8 || survivor.duration_seconds !== 30 || survivor.notes !== '保留备注') process.exit(1);
if (!v25ItemText(survivor).includes('30 秒')) process.exit(2);

function v25CanonicalPlan() { return {}; }
function v25ApiFetch() { process.exit(3); }
function v25RefreshCanonical() { process.exit(4); }
const saveStart = source.indexOf('function v25SaveCanonicalPlan(');
const saveEnd = source.indexOf('function v25PostponeCanonical(');
eval(source.slice(saveStart, saveEnd));
v25SaveCanonicalPlan('2026-10-01', [survivor]).then(() => process.exit(5)).catch(error => {
  if (!String(error.message).includes('后端未连接')) process.exit(6);
  let toast = '';
  function showToast(message) { toast = String(message); }
  function v25TodayKey() { return '2026-10-01'; }
  function v25SaveCanonicalPlan() { process.exit(7); }
  let localSaveCalls = 0;
  function saveTrainingState() { localSaveCalls += 1; }
  var todayPlan = [];
  var exerciseDetails = { '离线动作': { tags: [] } };
  const addStart = source.indexOf('function addToToday(');
  const addEnd = source.indexOf('function renderFavorites(');
  eval(source.slice(addStart, addEnd));
  addToToday('离线动作');
  if (todayPlan.length !== 0 || localSaveCalls !== 0 || !toast.includes('未保存')) process.exit(8);
  v25Remote.ready = true;
  v25Remote.exercises = [{id:2, name:'正式动作', default_sets:2, default_reps:null, duration_seconds:20, notes:'正式备注', video_url:'https://example.test/exercise'}];
  exerciseDetails['正式动作'] = { remoteId:2, remote:v25Remote.exercises[0], tags:['<span>约 1 分钟</span>'] };
  var calendarPlans = {}, restPlan = { title:'恢复日', status:'rest', items:[] }, capturedAdd = null;
  v25SaveCanonicalPlan = function(date, items) { capturedAdd = items[0]; return Promise.resolve(); };
  function renderTodayPlan() {}
  function openModal() {}
  addToToday('正式动作');
  if (!capturedAdd || capturedAdd.exerciseId !== 2 || capturedAdd.sets !== 2 || capturedAdd.duration_seconds !== 20 || capturedAdd.notes !== '正式备注' || capturedAdd.video_url !== 'https://example.test/exercise' || capturedAdd.time !== 1) process.exit(9);
  var dailySessions = {}, todayStarted = false, todayDone = false, todayStepIndex = 0, todayIsRest = false;
  const persistStart = source.indexOf('function persistTodayToSession(');
  const persistEnd = source.indexOf('function clonePlain(');
  eval(source.slice(persistStart, persistEnd));
  todayPlan = [first];
  persistTodayToSession('2026-10-01', true);
  if (dailySessions['2026-10-01'].items[0].video_url !== first.video_url) process.exit(10);
  console.log('PASS');
});
"""
    _assert_ok(_run(script))


def test_van10_export_validate_import_roundtrip_preserves_item_records():
    """The real export validation/import helpers keep itemRecords and nullable fields."""
    script = r"""
const fs = require('fs');
const source = fs.readFileSync('static/index.html', 'utf8');
var v25Remote = { ready: true, exercises: [] };
var restPlan = { title: '恢复日', status: 'rest', items: [] };
function v25RemoteExerciseByName() { return null; }
function v25TodayKey() { return '2026-09-30'; }
const helperStart = source.indexOf('function v25Has(');
const helperEnd = source.indexOf('function v25PlanPayload(');
eval(source.slice(helperStart, helperEnd));
const viewStart = source.indexOf('function v25ItemText(');
const viewEnd = source.indexOf('function v25ApplyCalendar(');
eval(source.slice(viewStart, viewEnd));
var TRAINING_STATE_VERSION = 1;
function isValidDateKey(key) { return /^\d{4}-\d{2}-\d{2}$/.test(key); }
function isValidPlanValue(value) { return value && typeof value === 'object' && typeof value.title === 'string' && Array.isArray(value.items); }
function migrateTrainingState(raw) { return raw && raw.version === TRAINING_STATE_VERSION ? raw : null; }
const validateStart = source.indexOf('function validateTrainingState(');
const validateEnd = source.indexOf('function loadTrainingState(');
eval(source.slice(validateStart, validateEnd));
const importStart = source.indexOf('function v25ImportedPlanEntries(');
const importEnd = source.indexOf('function applyImportedTrainingState(');
eval(source.slice(importStart, importEnd));

const original = { id: 77, exercise_id: 1, name: '未来计划保真动作', sets: 4, reps: 8, duration_seconds: 75, notes: '不能丢失的原始备注', spec: '4 组 · 8 次 · 75 秒', video_url: null };
const uiPlan = v25PlanToUi({ id: 9, title: '未来计划', theme: '原主题', focus: '原主题', notes: '计划原备注', template_id: 1, isTrainingDay: true, items: [original] }, 'planned');
const backup = { version: 1, data: { calendarPlans: { '2026-10-03': uiPlan }, customTrainingPlans: {}, dailySessions: {} } };
const validated = validateTrainingState(backup);
const importedEntry = v25ImportedPlanEntries(validated)[0];
const imported = importedEntry.items[0];
if (imported.sets !== 4 || imported.reps !== 8 || imported.duration_seconds !== 75 || imported.notes !== original.notes || imported.spec !== original.spec || imported.exercise_id !== original.exercise_id || importedEntry.notes !== '计划原备注' || importedEntry.focus !== '原主题' || importedEntry.template_id !== 1) process.exit(1);
console.log('PASS');
"""
    _assert_ok(_run(script))


def test_van10_import_refreshes_today_and_loaded_month_cache():
    """The real canonical refresh fetches all loaded months and today after import."""
    script = r"""
const fs = require('fs');
const source = fs.readFileSync('static/index.html', 'utf8');
var v25Remote = { ready: true, today: {id: 1, is_training: true, items: [{name:'旧动作'}]}, loadedMonths: {'2026-09': true}, exercises: [] };
var todayPlan = [{name:'旧动作'}], todayIsRest = false, calls = [];
function v25MonthForDate(key) { return String(key).slice(0, 7); }
function v25TodayKey() { return '2026-09-30'; }
function v25ApiFetch(path) {
  calls.push(path);
  if (path.indexOf('/api/plans/today') >= 0) return Promise.resolve({date:'2026-09-30', is_training:false, items:[]});
  return Promise.resolve({days:[]});
}
function v25ApplyPlanDays() {}
function renderTodayPlan() {}
function renderWeek() {}
function renderCalendarMonth() {}
function saveTrainingState() {}
const refreshStart = source.indexOf('function v25RefreshMonth(');
const refreshEnd = source.indexOf('function v25SaveCanonicalPlan(');
eval(source.slice(refreshStart, refreshEnd));
v25RefreshCanonical(['2026-10-03'], {refreshLoaded:true, forceToday:true}).then(() => {
  if (!calls.includes('/api/plans/month?month=2026-10')) process.exit(1);
  if (!calls.includes('/api/plans/month?month=2026-09')) process.exit(2);
  if (!calls.includes('/api/plans/today')) process.exit(3);
  if (todayPlan.length !== 0 || !todayIsRest) process.exit(4);
  console.log('PASS');
}).catch(error => { console.error(error); process.exit(5); });
"""
    _assert_ok(_run(script))
