"""VAN-14 behavior checks against the real inline v25 page logic."""
from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path


APP_DIR = Path(__file__).resolve().parents[1]
EVIDENCE_DIR = Path(os.environ.get("VAN14_EVIDENCE_DIR", "/private/tmp/van14-evidence"))


def test_van14_remote_failures_do_not_advance_or_fake_completion():
    script = r"""
const fs = require('fs');
const vm = require('vm');
const source = fs.readFileSync('static/index.html', 'utf8');

function section(startMarker, endMarker) {
  const start = source.indexOf(startMarker);
  const end = source.indexOf(endMarker, start);
  if (start < 0 || end < 0) throw new Error(`missing source section ${startMarker}`);
  return source.slice(start, end);
}

function makeResponse(status, body) {
  return {
    ok: status >= 200 && status < 300,
    status,
    text: async () => JSON.stringify(body),
  };
}

function makeHarness(planLength = 1) {
  const calls = [];
  const saves = [];
  const toasts = [];
  let modes = { update: 'ok', complete: 'ok', favorite: 'ok' };
  let completeCommitted = false;
  const context = {
    console,
    Promise,
    JSON,
    Object,
    Array,
    Error,
    Date,
    Math,
    setTimeout,
    clearTimeout,
    document: {},
    fetch: async (url, options = {}) => {
      const body = options.body ? JSON.parse(options.body) : null;
      calls.push({ url: String(url), method: String(options.method || 'GET'), body });
      if (String(url).includes('/api/session/update')) {
        if (modes.update === 'network') throw new Error('offline');
        if (modes.update === '422') return makeResponse(422, { detail: 'not allowed' });
        if (modes.update === '500') return makeResponse(500, { detail: 'update down' });
        return makeResponse(200, { status: 'updated', record: { status: 'completed' } });
      }
      if (String(url).includes('/api/session/complete')) {
        if (modes.complete === 'network') throw new Error('offline');
        if (modes.complete === '503') return makeResponse(503, { detail: 'complete down' });
        if (modes.complete === 'lost') {
          completeCommitted = true;
          throw new Error('response lost after commit');
        }
        return makeResponse(200, { status: completeCommitted ? 'already_completed' : 'completed', session: { status: 'completed' } });
      }
      if (String(url).includes('/api/favorites')) {
        if (modes.favorite === 'network') throw new Error('offline');
        if (modes.favorite === '500') return makeResponse(500, { detail: 'favorite down' });
        return makeResponse(200, { status: 'created' });
      }
      return makeResponse(200, {});
    },
    v25Remote: { ready: true, exercises: [{ id: 11, name: '动作 A' }] },
    v25RemotePlanId: 7,
    v25RemotePlanPromise: null,
    v25RemoteSessionId: 8,
    v25RemoteSessionPromise: null,
    v25RemoteStepPromise: Promise.resolve(),
    v25RemoteCompleted: false,
    v25RemoteProgressPending: false,
    v25RemoteFinalUpdateConfirmed: false,
    v25RemoteStatusVerified: false,
    v25LocalDoneAwaitingVerification: false,
    todayPlan: Array.from({ length: planLength }, (_, i) => ({ exerciseId: 11, name: `动作 ${i + 1}` })),
    todayStepIndex: 0,
    todayStarted: false,
    todayDone: false,
    favorites: [],
    renderTodayPlan: () => {},
    saveTrainingState: () => saves.push({ started: context.todayStarted, step: context.todayStepIndex, done: context.todayDone }),
    saveFavorites: () => saves.push({ favorites: context.favorites.slice() }),
    renderFavorites: () => {},
    showToast: (message, type) => toasts.push({ message: String(message), type }),
    formatDateKey: () => '2026-09-30',
    getToday: () => new Date('2026-09-30T00:00:00Z'),
  };
  vm.createContext(context);
  vm.runInContext(section('function v25ApiFetch', 'function v25MigrationPreview'), context);
  vm.runInContext(section('function advanceTodayTraining', 'function renderNewPlanModal'), context);
  // The page's showToast is intentionally replaced only as a test observer;
  // all request and state functions above are the actual page functions.
  context.showToast = (message, type) => toasts.push({ message: String(message), type });
  return { context, calls, saves, toasts, setModes: (next) => { modes = { ...modes, ...next }; } };
}

async function run() {
  const evidence = {};

  const success = makeHarness(1);
  const first = await success.context.advanceTodayTraining();
  const second = await success.context.advanceTodayTraining();
  if (first !== true || second !== true || !success.context.todayStarted || !success.context.todayDone || success.calls.filter(c => c.url.includes('/api/session/update')).length !== 2 || success.calls.filter(c => c.url.includes('/api/session/complete')).length !== 1) {
    throw new Error(`success path mismatch ${JSON.stringify({ first, second, calls: success.calls, state: { started: success.context.todayStarted, done: success.context.todayDone } })}`);
  }
  evidence.success = { calls: success.calls, state: { started: success.context.todayStarted, done: success.context.todayDone } };

  for (const mode of ['422', '500', 'network']) {
    const failed = makeHarness(1);
    failed.setModes({ update: mode });
    const result = await failed.context.advanceTodayTraining();
    if (result !== false || failed.context.todayStarted || failed.context.todayDone || failed.context.todayStepIndex !== 0 || failed.saves.length !== 0 || !failed.toasts.some(t => t.type === 'error' && t.message.includes('训练保存失败'))) {
      throw new Error(`update ${mode} was treated as success ${JSON.stringify({ result, calls: failed.calls, saves: failed.saves, toasts: failed.toasts, state: failed.context })}`);
    }
    evidence[`update_${mode}`] = { calls: failed.calls, saves: failed.saves, toast: failed.toasts.at(-1) };
  }

  const completeFailed = makeHarness(1);
  completeFailed.context.todayStarted = true;
  completeFailed.setModes({ complete: '503' });
  const completeResult = await completeFailed.context.advanceTodayTraining();
  if (completeResult !== false || completeFailed.context.todayDone || completeFailed.context.todayStepIndex !== 0 || completeFailed.saves.length !== 0) {
    throw new Error(`complete failure advanced local state ${JSON.stringify({ completeResult, calls: completeFailed.calls, saves: completeFailed.saves, state: { done: completeFailed.context.todayDone, step: completeFailed.context.todayStepIndex } })}`);
  }
  evidence.complete_failure = { calls: completeFailed.calls, state: { done: completeFailed.context.todayDone, step: completeFailed.context.todayStepIndex }, toast: completeFailed.toasts.at(-1) };

  const retry = makeHarness(1);
  retry.context.todayStarted = true;
  retry.setModes({ complete: '503' });
  const firstComplete = await retry.context.advanceTodayTraining();
  if (firstComplete !== false || !retry.context.v25RemoteFinalUpdateConfirmed) throw new Error('final update confirmation was not retained after complete failure');
  const callsBeforeRetry = retry.calls.length;
  retry.setModes({ complete: 'ok' });
  const secondComplete = await retry.context.advanceTodayTraining();
  const retryCalls = retry.calls.slice(callsBeforeRetry);
  if (secondComplete !== true || !retry.context.todayDone || retryCalls.some(c => c.url.includes('/api/session/update')) || retryCalls.filter(c => c.url.includes('/api/session/complete')).length !== 1) {
    throw new Error(`complete retry repeated update or stayed incomplete ${JSON.stringify({ secondComplete, retryCalls, state: { done: retry.context.todayDone }, finalUpdateConfirmed: retry.context.v25RemoteFinalUpdateConfirmed })}`);
  }
  evidence.complete_retry_after_lost_response = { first_attempt: retry.calls.slice(0, callsBeforeRetry), retry_calls: retryCalls, state: { done: retry.context.todayDone } };

  const lostResponse = makeHarness(1);
  lostResponse.context.todayStarted = true;
  lostResponse.setModes({ complete: 'lost' });
  const lostFirst = await lostResponse.context.advanceTodayTraining();
  const lostCallsBeforeRetry = lostResponse.calls.length;
  lostResponse.setModes({ complete: 'ok' });
  const lostSecond = await lostResponse.context.advanceTodayTraining();
  const lostRetryCalls = lostResponse.calls.slice(lostCallsBeforeRetry);
  if (lostFirst !== false || lostSecond !== true || !lostResponse.context.todayDone || lostRetryCalls.some(c => c.url.includes('/api/session/update')) || lostRetryCalls.filter(c => c.url.includes('/api/session/complete')).length !== 1) {
    throw new Error(`lost complete response was not safely retried ${JSON.stringify({ lostFirst, lostSecond, lostRetryCalls, state: { done: lostResponse.context.todayDone } })}`);
  }
  evidence.complete_commit_then_response_loss = { first_attempt: lostResponse.calls.slice(0, lostCallsBeforeRetry), retry_calls: lostRetryCalls, retry_response_status: 'already_completed', state: { done: lostResponse.context.todayDone } };

  const favorite = makeHarness(1);
  favorite.setModes({ favorite: '500' });
  const favoriteFailure = await favorite.context.v25ToggleFavorite('动作 A');
  if (favoriteFailure !== false || favorite.context.favorites.length !== 0 || !favorite.toasts.some(t => t.type === 'error' && t.message.includes('收藏同步失败'))) throw new Error('favorite failure changed local state');
  favorite.setModes({ favorite: 'ok' });
  const favoriteSuccess = await favorite.context.v25ToggleFavorite('动作 A');
  if (favoriteSuccess !== true || favorite.context.favorites.join(',') !== '动作 A') throw new Error('favorite retry did not persist after success');
  evidence.favorite = { failure_result: favoriteFailure, success_result: favoriteSuccess, favorites: favorite.context.favorites, calls: favorite.calls };

  const statusDetail = { days: [{ date: '2026-09-30', status: 'planned' }] };
  const refresh = makeHarness(1);
  if (refresh.context.v25BackendStatusForDay(statusDetail, '2026-09-30') !== 'planned') throw new Error('backend status helper not read from real page logic');
  const staleDone = refresh.context.v25ReconcileTodaySession({ started: true, done: true, stepIndex: 0 }, refresh.context.todayPlan, '今日训练', false, true, false);
  const confirmedDone = refresh.context.v25ReconcileTodaySession({ started: true, done: false, stepIndex: 0 }, refresh.context.todayPlan, '今日训练', false, true, true);
  const unknownStatus = refresh.context.v25ReconcileTodaySession({ started: true, done: true, stepIndex: 0 }, refresh.context.todayPlan, '今日训练', false, false, false);
  if (staleDone.done || !confirmedDone.done || !confirmedDone.started || unknownStatus.done) throw new Error('refresh reconciliation accepted an unconfirmed local done flag');
  refresh.context.todayDone = true;
  refresh.context.v25RemoteStatusVerified = false;
  if (refresh.context.v25UiDoneConfirmed()) throw new Error('UI exposed done before backend verification');
  refresh.context.v25ResetUnverifiedDone();
  if (refresh.context.todayDone || refresh.context.v25LocalDoneAwaitingVerification !== true) throw new Error('initial unverified done was not isolated');
  refresh.context.v25RemoteStatusVerified = true;
  refresh.context.todayDone = true;
  if (!refresh.context.v25UiDoneConfirmed()) throw new Error('confirmed backend done was not shown');
  const unverifiedRetry = makeHarness(1);
  unverifiedRetry.context.todayDone = true;
  unverifiedRetry.context.v25RemoteStatusVerified = false;
  const unverifiedRetryResult = await unverifiedRetry.context.advanceTodayTraining();
  if (unverifiedRetryResult !== true || unverifiedRetry.calls.length !== 1) throw new Error('unverified local done blocked a retry');
  evidence.refresh_reconciliation = { planned_status: statusDetail.days[0].status, stale_done_reset: staleDone.done, completed_status_done: confirmedDone.done, unknown_status_done: unknownStatus.done, initial_done_hidden: true, confirmed_done_shown: true, unverified_done_retry_allowed: true };

  console.log(JSON.stringify({ PASS: true, evidence }, null, 2));
}

run().catch((error) => { console.error(error.stack || error); process.exit(1); });
"""
    result = subprocess.run(
        ["node", "-e", script],
        capture_output=True,
        text=True,
        cwd=str(APP_DIR),
        timeout=30,
    )
    EVIDENCE_DIR.mkdir(parents=True, exist_ok=True)
    (EVIDENCE_DIR / "frontend-behavior-output.json").write_text(
        result.stdout if result.stdout else result.stderr,
        encoding="utf-8",
    )
    assert result.returncode == 0, result.stderr + "\n" + result.stdout
    assert '"PASS": true' in result.stdout


def test_van14_player_complete_button_retries_before_closing():
    """Exercise the real playerCompleteBtn click callback, not only its callee."""
    script = r"""
const fs = require('fs');
const vm = require('vm');
const source = fs.readFileSync('static/index.html', 'utf8');

function FakeElement(id, tag = 'div') {
  this.id = id;
  this.tagName = tag.toUpperCase();
  this.hidden = true;
  this.disabled = false;
  this.textContent = '';
  this.style = {};
  this.offsetParent = this;
  this.listeners = {};
  this.attributes = {};
  this.children = [];
  this.classList = {
    values: new Set(),
    add: (...names) => names.forEach((name) => this.classList.values.add(name)),
    remove: (...names) => names.forEach((name) => this.classList.values.delete(name)),
    contains: (name) => this.classList.values.has(name),
  };
}
FakeElement.prototype.addEventListener = function (type, handler) {
  this.listeners[type] = handler;
};
FakeElement.prototype.removeEventListener = function (type, handler) {
  if (this.listeners[type] === handler) delete this.listeners[type];
};
FakeElement.prototype.click = function () {
  const handler = this.listeners.click;
  return handler && handler({ target: this });
};
FakeElement.prototype.appendChild = function (child) {
  this.children.push(child);
  if (child.tagName === 'VIDEO') this.video = child;
  return child;
};
FakeElement.prototype.setAttribute = function (name, value) {
  this.attributes[name] = String(value);
};
FakeElement.prototype.getAttribute = function (name) {
  return Object.prototype.hasOwnProperty.call(this.attributes, name) ? this.attributes[name] : null;
};
FakeElement.prototype.focus = function () {
  this.ownerDocument.activeElement = this;
};
FakeElement.prototype.querySelector = function (selector) {
  if (selector === 'video') return this.video || null;
  if (selector === '.ai-verified-badge') return this.badge || null;
  return null;
};
FakeElement.prototype.querySelectorAll = function () {
  return this.children.filter((child) => !child.disabled && child.offsetParent !== null);
};

function makeVideo() {
  const video = new FakeElement('playerVideo', 'video');
  video.play = () => Promise.resolve();
  video.pause = () => {};
  video.load = () => {};
  video.removeAttribute = (name) => { delete video[name]; };
  return video;
}

const ids = {
  playerLayer: new FakeElement('playerLayer'),
  playerStage: new FakeElement('playerStage'),
  playerTitle: new FakeElement('playerTitle'),
  playerExerciseName: new FakeElement('playerExerciseName'),
  playerDescription: new FakeElement('playerDescription'),
  previewTimer: new FakeElement('previewTimer'),
  closePlayer: new FakeElement('closePlayer', 'button'),
  playerCompleteBtn: new FakeElement('playerCompleteBtn', 'button'),
  playerAddTodayBtn: new FakeElement('playerAddTodayBtn', 'button'),
};
ids.playerLayer.badge = new FakeElement('verifiedBadge');
ids.playerLayer.children = [ids.closePlayer, ids.playerCompleteBtn, ids.playerAddTodayBtn];
ids.playerStage.children = [];
ids.playerStage.video = null;

const document = {
  body: { style: {} },
  activeElement: null,
  listeners: {},
  getElementById: (id) => ids[id] || null,
  createElement: (tag) => {
    const element = tag === 'video' ? makeVideo() : new FakeElement('', tag);
    element.ownerDocument = document;
    if (tag === 'video') {
      ids.playerStage.video = element;
      ids.playerStage.children.push(element);
    }
    return element;
  },
  addEventListener: (type, handler) => { document.listeners[type] = handler; },
  removeEventListener: (type, handler) => {
    if (document.listeners[type] === handler) delete document.listeners[type];
  },
};
Object.values(ids).forEach((element) => { element.ownerDocument = document; });
document.activeElement = document.body;

let attempts = 0;
const context = {
  console,
  Promise,
  Set,
  Array,
  Object,
  Error,
  document,
  window: { scrollY: 0, pageYOffset: 0, scrollTo: () => {} },
  requestAnimationFrame: (callback) => callback(),
  exerciseDetails: {
    '动作 A': {
      videoData: {
        src: 'https://example.test/verified.mp4',
        verified: true,
        verifiedAt: '2026-09-30T00:00:00.000Z',
        title: '动作 A 教学',
        duration: '30 秒',
      },
    },
  },
  todaySessionKey: '2026-10-01',
  todayStepIndex: 0,
  v25UiDoneConfirmed: () => false,
  advanceTodayTraining: () => {
    attempts += 1;
    return Promise.resolve(attempts === 2);
  },
  addToToday: () => { throw new Error('library add path should not run'); },
  escapeHtml: (value) => String(value),
};
vm.createContext(context);
const start = source.indexOf('      // ── P1-1 视频真实性：verified 状态判定 ──');
const end = source.indexOf('      function renderTrainingPlans', start);
if (start < 0 || end < 0) throw new Error('missing player source section');
vm.runInContext(source.slice(start, end), context);

async function run() {
  context.showVideoPlayer('动作 A', 'today');
  if (ids.playerLayer.hidden || ids.playerCompleteBtn.textContent !== '完成跟练') {
    throw new Error(`player did not open in today context ${JSON.stringify({ hidden: ids.playerLayer.hidden, label: ids.playerCompleteBtn.textContent })}`);
  }

  ids.playerCompleteBtn.click();
  await new Promise((resolve) => setImmediate(resolve));
  if (ids.playerLayer.hidden || ids.playerCompleteBtn.disabled || ids.playerCompleteBtn.textContent !== '重试同步' || attempts !== 1) {
    throw new Error(`failed completion closed or did not expose retry ${JSON.stringify({ hidden: ids.playerLayer.hidden, disabled: ids.playerCompleteBtn.disabled, label: ids.playerCompleteBtn.textContent, attempts })}`);
  }

  ids.playerCompleteBtn.click();
  await new Promise((resolve) => setImmediate(resolve));
  if (!ids.playerLayer.hidden || ids.playerLayer.getAttribute('aria-hidden') !== 'true' || attempts !== 2) {
    throw new Error(`successful retry did not close player ${JSON.stringify({ hidden: ids.playerLayer.hidden, ariaHidden: ids.playerLayer.getAttribute('aria-hidden'), attempts })}`);
  }
  console.log(JSON.stringify({ PASS: true, attempts, failure: { open: true, retryLabel: '重试同步' }, success: { closed: true } }));
}

run().catch((error) => { console.error(error.stack || error); process.exit(1); });
"""
    result = subprocess.run(
        ["node", "-e", script],
        capture_output=True,
        text=True,
        cwd=str(APP_DIR),
        timeout=30,
    )
    EVIDENCE_DIR.mkdir(parents=True, exist_ok=True)
    (EVIDENCE_DIR / "player-button-output.json").write_text(
        result.stdout if result.stdout else result.stderr,
        encoding="utf-8",
    )
    assert result.returncode == 0, result.stderr + "\n" + result.stdout
    assert '"PASS":true' in result.stdout
