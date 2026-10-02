'use strict';

const fs = require('fs');
const path = require('path');
const { JSDOM } = require(path.join(
  process.env.VAN16_DOM_DEPS || '/private/tmp/van13-jsdom-deps/node_modules',
  'jsdom'
));

const source = fs.readFileSync(process.env.VAN16_TEST_SOURCE || path.join(__dirname, '..', 'static', 'index.html'), 'utf8');
const OLD_PLAN = '旧本地假动作';
const REAL_PLAN = '真实动作';

function response(body, status = 200) {
  return {
    ok: status >= 200 && status < 300,
    status,
    text: async () => JSON.stringify(body),
    json: async () => body,
  };
}

function oldTrainingEnvelope() {
  return {
    version: 1,
    updatedAt: '',
    data: {
      calendarPlans: {},
      customTrainingPlans: {},
      dailySessions: {
        '2026-10-02': {
          items: [{
            id: 99,
            name: OLD_PLAN,
            exerciseId: 99,
            sets: 9,
            reps: 99,
            duration_seconds: 999,
            notes: '旧数据',
            video_url: null,
            spec: '旧数据',
            time: 99,
          }],
          source: '旧本地计划',
          stepIndex: 0,
          setIndex: 1,
          actionElapsedSeconds: 10,
          actionStartedAt: 1,
          skipped: [],
          records: [{ status: 'completed', setsCompleted: 9, durationSeconds: 999 }],
          pending: null,
          started: true,
          done: true,
          rest: false,
          updatedAt: '',
        },
      },
    },
  };
}

function payloadFor(pathname, mode) {
  if (pathname === '/api/plans/today') {
    if (mode === 'empty') return { date: '2026-10-02', is_training: false, isTrainingDay: false, items: [] };
    return {
      date: '2026-10-02',
      id: 41,
      title: '真实计划',
      is_training: true,
      isTrainingDay: true,
      items: [{ id: 7, exercise_id: 9, name: REAL_PLAN, sets: 3, reps: 8, duration_seconds: 30, spec: '3 组 · 8 次' }],
    };
  }
  if (pathname.startsWith('/api/calendar?month=')) return { days: [] };
  if (pathname.startsWith('/api/stats/month/detail?month=')) return { days: [], completed: 0 };
  if (pathname.startsWith('/api/stats/month?month=')) return { month: '2026-10', training_days: 0, completed: 0, completion_rate: 0, duration_seconds: 0 };
  if (pathname.startsWith('/api/stats/week/detail?date=')) return { days: [], training_days: 0, completed: 0 };
  if (pathname === '/api/exercises') return { exercises: [] };
  if (pathname === '/api/templates') return { templates: [] };
  if (pathname === '/api/favorites') return { favorites: [] };
  if (pathname === '/api/ai/provider') return { provider: 'local-demo', model: '' };
  if (pathname === '/api/ai/models') return { models: [] };
  if (pathname.startsWith('/api/plans/month?month=')) return { days: [] };
  if (pathname === '/api/session/current?include_completed=true') return { session: null };
  return {};
}

function createPage({ mode = 'data', delayToday = false, seedOldState = true, date = [2026, 9, 2], fetchOverride = null } = {}) {
  const control = { mode, delayToday, pendingToday: [], calls: [] };
  const dom = new JSDOM(source, {
    url: 'http://127.0.0.1:3000/',
    runScripts: 'dangerously',
    pretendToBeVisual: true,
    beforeParse(window) {
      // Keep the page's real Date source aligned with the isolated API and
      // localStorage fixtures. Without this, a future run could hydrate a
      // different day and accidentally make the pollution assertion vacuous.
      const RealDate = window.Date;
      // Use local noon so the local calendar date remains 2026-10-02 in every
      // timezone, including zones west of UTC.
      const fixedMs = new RealDate(...date, 12, 0, 0).getTime();
      function FixedDate(...args) {
        if (!(this instanceof FixedDate)) return RealDate(...args);
        return args.length ? new RealDate(...args) : new RealDate(fixedMs);
      }
      FixedDate.now = () => fixedMs;
      FixedDate.parse = RealDate.parse;
      FixedDate.UTC = RealDate.UTC;
      FixedDate.prototype = RealDate.prototype;
      window.Date = FixedDate;
      window.fetch = function fetchMock(pathname) {
        control.calls.push(String(pathname));
        if (fetchOverride) return fetchOverride(pathname, control);
        if (pathname === '/api/plans/today' && control.delayToday) {
          const delayedBody = payloadFor(pathname, control.mode);
          return new Promise((resolve, reject) => control.pendingToday.push({ resolve, reject, body: delayedBody }));
        }
        if (pathname === '/api/plans/today' && control.mode === 'error') {
          return Promise.resolve(response({ detail: 'offline' }, 503));
        }
        return Promise.resolve(response(payloadFor(pathname, control.mode)));
      };
      window.localStorage.setItem('qd-training-state', JSON.stringify({ legacy: OLD_PLAN }));
      if (seedOldState) window.localStorage.setItem('qd-training-state-v1', JSON.stringify(oldTrainingEnvelope()));
      window.confirm = () => true;
      window.prompt = () => null;
      window.alert = () => {};
      window.innerWidth = 1280;
      window.innerHeight = 800;
      window.scrollTo = () => {};
      window.scrollBy = () => {};
      window.requestAnimationFrame = (callback) => setTimeout(callback, 0);
      window.cancelAnimationFrame = (id) => clearTimeout(id);
    },
  });
  const hydratedState = dom.window.__qdTrainingState.read();
  const hydratedOldSession = hydratedState && hydratedState.data && hydratedState.data.dailySessions
    ? hydratedState.data.dailySessions['2026-10-02']
    : null;
  return { dom, control, hydratedOldSession };
}

function tick() {
  return new Promise((resolve) => setImmediate(resolve));
}

async function waitFor(predicate, label) {
  for (let i = 0; i < 80; i += 1) {
    if (predicate()) return;
    await tick();
  }
  throw new Error(`timed out waiting for ${label}`);
}

function snapshot(page) {
  const { document } = page.dom.window;
  const fetchState = document.getElementById('dayFetchState');
  const emptyHero = document.getElementById('dayEmptyHero');
  const content = document.getElementById('dayHeroContent');
  const todayPlan = page.dom.window.__qdApp.getTodayPlan();
  return {
    state: document.getElementById('dayHero').getAttribute('data-today-state'),
    fetchHidden: fetchState.hidden,
    fetchDisplay: page.dom.window.getComputedStyle(fetchState).display,
    fetchText: fetchState.textContent,
    retryVisible: !fetchState.hidden && !!fetchState.querySelector('[data-v25-retry-today]'),
    emptyHidden: emptyHero.hidden,
    emptyDisplay: page.dom.window.getComputedStyle(emptyHero).display,
    emptyText: emptyHero.textContent,
    videoDisplay: page.dom.window.getComputedStyle(document.getElementById('dayHeroVideo')).display,
    contentHidden: content.hidden,
    contentDisplay: page.dom.window.getComputedStyle(content).display,
    planText: document.getElementById('todayPlanList').textContent,
    todayPlan: todayPlan.map((item) => item.name),
    todayKey: page.dom.window.__qdTrainingState.key(),
  };
}

function assert(condition, message) {
  if (!condition) throw new Error(message);
}

function assertLoading(page, label) {
  const state = snapshot(page);
  assert(state.state === 'loading', `${label}: expected loading: ${JSON.stringify(state)}`);
  assert(!state.fetchHidden && state.fetchDisplay !== 'none', `${label}: loading status is hidden: ${JSON.stringify(state)}`);
  assert(state.emptyHidden && state.emptyDisplay === 'none' && state.contentHidden && state.contentDisplay === 'none' && state.videoDisplay === 'none', `${label}: loading layers wrong: ${JSON.stringify(state)}`);
  assert(!state.fetchText.includes('今天还没有训练动作'), `${label}: loading contains empty copy: ${state.fetchText}`);
  assert(!state.planText.includes(OLD_PLAN), `${label}: old hydrated plan is visible: ${state.planText}`);
}

function assertError(page, label) {
  const state = snapshot(page);
  assert(state.state === 'error', `${label}: expected error: ${JSON.stringify(state)}`);
  assert(!state.fetchHidden && state.fetchDisplay !== 'none' && state.retryVisible, `${label}: error retry is not visible: ${JSON.stringify(state)}`);
  assert(state.emptyHidden && state.emptyDisplay === 'none' && state.contentHidden && state.contentDisplay === 'none' && state.videoDisplay === 'none', `${label}: error layers wrong: ${JSON.stringify(state)}`);
  assert(state.fetchText.includes('读取失败'), `${label}: missing error copy: ${state.fetchText}`);
  assert(!state.fetchText.includes('今天还没有训练动作'), `${label}: error contains empty copy: ${state.fetchText}`);
  assert(!state.planText.includes(OLD_PLAN), `${label}: old hydrated plan is visible: ${state.planText}`);
}

function assertEmpty(page, label) {
  const state = snapshot(page);
  assert(state.state === 'empty', `${label}: expected empty: ${JSON.stringify(state)}`);
  assert(state.fetchHidden && state.fetchDisplay === 'none', `${label}: fetch status remains visible: ${JSON.stringify(state)}`);
  assert(!state.emptyHidden && state.emptyDisplay !== 'none' && state.emptyText.includes('今天还没有训练动作'), `${label}: empty hero wrong: ${JSON.stringify(state)}`);
  assert(state.contentHidden && state.contentDisplay === 'none' && state.videoDisplay === 'none', `${label}: data hero leaked into empty: ${JSON.stringify(state)}`);
  assert(!state.planText.includes(OLD_PLAN), `${label}: old hydrated plan is visible: ${state.planText}`);
}

function assertData(page, label) {
  const state = snapshot(page);
  assert(state.state === 'data', `${label}: expected data: ${JSON.stringify(state)}`);
  assert(state.fetchHidden && state.fetchDisplay === 'none' && state.emptyHidden && state.emptyDisplay === 'none', `${label}: stale status layer remains: ${JSON.stringify(state)}`);
  assert(!state.contentHidden && state.contentDisplay !== 'none' && state.videoDisplay !== 'none' && state.todayPlan.includes(REAL_PLAN), `${label}: backend data is not visible: ${JSON.stringify(state)}`);
  assert(!state.planText.includes(OLD_PLAN), `${label}: old hydrated plan survived: ${state.planText}`);
}

async function settleDelayedToday(page) {
  const pending = page.control.pendingToday.splice(0);
  assert(pending.length === 1, `expected one delayed today request, got ${pending.length}`);
  page.control.delayToday = false;
  pending.forEach((item) => item.resolve(response(item.body)));
}

async function clickProductionRetry(page, nextMode, label) {
  const button = page.dom.window.document.querySelector('[data-v25-retry-today]');
  assert(button, `${label}: production retry button is missing`);
  const todayCallsBefore = page.control.calls.filter((pathName) => pathName === '/api/plans/today').length;
  page.control.mode = nextMode;
  button.click();
  await waitFor(() => page.control.calls.filter((pathName) => pathName === '/api/plans/today').length > todayCallsBefore, `${label} retry request`);
}

if (require.main === module) (async () => {
  // The exact production key is exercised by hydrateTrainingState, not a hand-written runtime stub.
  const loadingData = createPage({ mode: 'data', delayToday: true, seedOldState: true });
  assert(snapshot(loadingData).todayKey === 'qd-training-state-v1', 'production uses the wrong localStorage key');
  assert(loadingData.control.pendingToday.length === 1, 'full page did not issue the delayed today request');
  assert(loadingData.hydratedOldSession && loadingData.hydratedOldSession.items[0].name === OLD_PLAN, 'production hydrate did not read the seeded old session');
  assertLoading(loadingData, 'loading → data');
  await settleDelayedToday(loadingData);
  await waitFor(() => snapshot(loadingData).state === 'data', 'loading → data render');
  assertData(loadingData, 'loading → data');

  const loadingEmpty = createPage({ mode: 'empty', delayToday: true, seedOldState: true });
  assertLoading(loadingEmpty, 'loading → empty');
  await settleDelayedToday(loadingEmpty);
  await waitFor(() => snapshot(loadingEmpty).state === 'empty', 'loading → empty render');
  assertEmpty(loadingEmpty, 'loading → empty');

  const loadingError = createPage({ mode: 'error', seedOldState: true });
  await waitFor(() => snapshot(loadingError).state === 'error', 'loading → error render');
  assertError(loadingError, 'loading → error');

  const retryData = createPage({ mode: 'error', seedOldState: true });
  await waitFor(() => snapshot(retryData).state === 'error', 'error → retry → data initial error');
  assertError(retryData, 'error → retry → data initial error');
  await clickProductionRetry(retryData, 'data', 'error → retry → data');
  await waitFor(() => snapshot(retryData).state === 'data', 'error → retry → data render');
  assertData(retryData, 'error → retry → data');

  const retryEmpty = createPage({ mode: 'error', seedOldState: true });
  await waitFor(() => snapshot(retryEmpty).state === 'error', 'error → retry → empty initial error');
  assertError(retryEmpty, 'error → retry → empty initial error');
  await clickProductionRetry(retryEmpty, 'empty', 'error → retry → empty');
  await waitFor(() => snapshot(retryEmpty).state === 'empty', 'error → retry → empty render');
  assertEmpty(retryEmpty, 'error → retry → empty');

  console.log(JSON.stringify({
    PASS: true,
    productionInlineScript: true,
    localStorageKey: 'qd-training-state-v1',
    states: ['loading→data', 'loading→empty', 'loading→error'],
    retries: ['error→retry→data', 'error→retry→empty'],
    clickPath: 'production document delegation',
    cssVisibility: 'computed display asserted',
  }));
})().catch((error) => {
  console.error(error.stack || error);
  process.exit(1);
});

module.exports = { createPage, response, payloadFor, snapshot, assert, assertLoading, assertError, assertEmpty, assertData, waitFor, tick };
