'use strict';

// VAN-23 formal production-page harness. This loads the complete inline
// static/index.html and exercises the real FileReader -> validation -> preview
// -> confirmation -> API import/readback -> boot refresh path.
const fs = require('fs');
const path = require('path');
const { JSDOM, VirtualConsole } = require(path.join(
  process.env.VAN16_DOM_DEPS || '/private/tmp/van13-jsdom-deps/node_modules',
  'jsdom'
));

const SOURCE = fs.readFileSync(path.join(__dirname, '..', 'static', 'index.html'), 'utf8');
const TODAY = '2026-10-06';
const RAW_CASES = [
  ['tag', '<b>test</b>'],
  ['script', '<script>window.__van23Marker++</script>'],
  ['img', '<img src=x onerror="window.__van23Marker++">'],
  ['svg', '<svg onload="window.__van23Marker++"></svg>'],
  ['attribute', '" onmouseover="window.__van23Marker++" data-x="'],
  ['ordinary', "普通中文🧘 A & B <5kg '单双引号'"],
];
function valuesForCase(index) {
  const [label, raw] = RAW_CASES[index];
  return {
    label,
    raw,
    title: `备份标题 ${raw}`,
    name: `备份动作 ${raw}`,
    spec: `动作规格 ${raw}`,
    description: `动作说明 ${raw}`,
    focus: `备份焦点 ${raw}`,
    notes: `备份备注 ${raw}`,
  };
}
const PRIMARY = valuesForCase(0);
const ATTACK_TITLE = PRIMARY.title;
const ATTACK_NAME = PRIMARY.name;
const ATTACK_SPEC = PRIMARY.spec;
const ATTACK_ID = 'custom_<img src=x onerror="window.__van23Marker++">';

function response(body, status = 200) {
  return {
    ok: status >= 200 && status < 300,
    status,
    text: async () => JSON.stringify(body),
    json: async () => body,
  };
}

function itemRecord(values = PRIMARY) {
  return {
    id: 701,
    exercise_id: 9,
    name: values.name,
    sets: 3,
    reps: 8,
    duration_seconds: 60,
    notes: values.description,
    video_url: null,
    spec: values.spec,
  };
}

function remoteDay(date, values = PRIMARY) {
  return {
    id: date === TODAY ? 701 : 702,
    date,
    title: values.title,
    theme: '全身',
    focus: values.focus,
    notes: values.notes,
    template_id: null,
    is_training: true,
    items: [itemRecord(values)],
  };
}

function createPage({ plans = null, trainingStateRaw = null } = {}) {
  const state = {
    calls: [],
    imports: [],
    plans: plans ? JSON.parse(JSON.stringify(plans)) : [remoteDay(TODAY), remoteDay('2026-10-07')],
  };
  const virtualConsole = new VirtualConsole();
  const errors = [];
  virtualConsole.on('jsdomError', (error) => errors.push(error.stack || error.message || String(error)));
  const dom = new JSDOM(SOURCE, {
    url: 'http://127.0.0.1:3823/',
    runScripts: 'dangerously',
    pretendToBeVisual: true,
    virtualConsole,
    beforeParse(window) {
      const RealDate = window.Date;
      const fixedMs = new RealDate(2026, 9, 6, 12, 0, 0).getTime();
      function FixedDate(...args) {
        if (!(this instanceof FixedDate)) return RealDate(...args);
        return args.length ? new RealDate(...args) : new RealDate(fixedMs);
      }
      FixedDate.now = () => fixedMs;
      FixedDate.parse = RealDate.parse;
      FixedDate.UTC = RealDate.UTC;
      FixedDate.prototype = RealDate.prototype;
      window.Date = FixedDate;
      window.__van23Marker = 0;
      window.matchMedia = () => ({ matches: false, addListener() {}, removeListener() {}, addEventListener() {}, removeEventListener() {} });
      window.confirm = () => true;
      window.prompt = () => null;
      window.alert = () => {};
      window.innerWidth = 1280;
      window.innerHeight = 800;
      window.scrollTo = () => {};
      window.scrollBy = () => {};
      window.requestAnimationFrame = (callback) => setTimeout(callback, 0);
      window.cancelAnimationFrame = (id) => clearTimeout(id);
      if (trainingStateRaw) window.localStorage.setItem('qd-training-state-v1', trainingStateRaw);
      window.fetch = function fetchMock(url, options = {}) {
        const pathname = String(url);
        const method = String(options.method || 'GET').toUpperCase();
        let body = null;
        try { body = options.body ? JSON.parse(options.body) : null; } catch (_) { body = options.body; }
        state.calls.push({ url: pathname, method, body });
        if (pathname === '/api/plans/import' && method === 'POST') {
          state.imports.push(body);
          const importedPlans = body && Array.isArray(body.plans) ? body.plans : [];
          state.plans = importedPlans.filter((plan) => plan && plan.date).map((plan, index) => ({
            id: 700 + index,
            date: plan.date,
            title: plan.title,
            theme: plan.focus,
            focus: plan.focus,
            notes: plan.notes,
            template_id: plan.template_id,
            is_training: plan.is_training_day,
            items: plan.items || [],
          }));
          return Promise.resolve(response({ status: 'imported', plans: state.plans }));
        }
        if (pathname === '/api/plans/today') {
          const day = state.plans.find((plan) => plan.date === TODAY);
          return Promise.resolve(response(day ? {
            date: TODAY,
            id: day.id,
            title: day.title,
            is_training: day.is_training,
            isTrainingDay: day.is_training,
            items: day.items,
          } : { date: TODAY, is_training: false, isTrainingDay: false, items: [] }));
        }
        if (pathname.startsWith('/api/plans/month?')) return Promise.resolve(response({ days: state.plans }));
        if (pathname.startsWith('/api/calendar?')) return Promise.resolve(response({ days: [] }));
        if (pathname.startsWith('/api/stats/month/detail?')) {
          return Promise.resolve(response({ days: state.plans.map((plan) => ({ date: plan.date, status: 'planned' })), completed: 0 }));
        }
        if (pathname.startsWith('/api/stats/month?')) return Promise.resolve(response({ month: '2026-10', training_days: state.plans.length, completed: 0, completion_rate: 0, duration_seconds: 0 }));
        if (pathname.startsWith('/api/stats/week/detail?')) return Promise.resolve(response({ days: [], training_days: 0, completed: 0 }));
        if (pathname === '/api/exercises') return Promise.resolve(response({ exercises: [{ id: 9, name: '测试动作', category: '核心', catalog_key: 'test' }] }));
        if (pathname === '/api/templates') return Promise.resolve(response({ templates: [] }));
        if (pathname === '/api/favorites') return Promise.resolve(response({ favorites: [] }));
        if (pathname === '/api/ai/provider') return Promise.resolve(response({ provider: 'local-demo', model: '' }));
        if (pathname === '/api/ai/models') return Promise.resolve(response({ models: [] }));
        if (pathname.startsWith('/api/session/current?')) return Promise.resolve(response({ session: null }));
        return Promise.resolve(response({}));
      };
    },
  });
  return { dom, state, errors };
}

function tick() { return new Promise((resolve) => setImmediate(resolve)); }

async function waitFor(predicate, label) {
  for (let i = 0; i < 160; i += 1) {
    if (predicate()) return;
    await tick();
  }
  throw new Error(`timed out waiting for ${label}`);
}

function renderedRoots(document) {
  return [
    document.getElementById('weekList'), document.getElementById('weekHint'),
    document.getElementById('calendar'), document.getElementById('appModalCard'),
    document.getElementById('todayPlanList'), document.getElementById('dayProgressTrack'),
    document.getElementById('dayProgressSteps'), document.getElementById('dayProgressCaption'),
    document.getElementById('trainingPlanList'),
  ].filter(Boolean);
}

function assertSafeRenderedPage(page, label) {
  const { document } = page.dom.window;
  const roots = renderedRoots(document);
  assert(roots.every((root) => !root.querySelector('b, script, img, svg')), `${label}: active or formatting element was created`);
  const elements = roots.flatMap((root) => [root, ...root.querySelectorAll('*')]);
  elements.forEach((element) => {
    [...element.attributes].forEach((attribute) => {
      assert(!/^on/i.test(attribute.name), `${label}: event attribute ${attribute.name} was created`);
    });
    ['error', 'load', 'mouseover'].forEach((type) => {
      element.dispatchEvent(new page.dom.window.Event(type, { bubbles: true }));
    });
  });
  assert(page.dom.window.__van23Marker === 0, `${label}: payload marker ran`);
}

function assert(condition, message) { if (!condition) throw new Error(message); }

function bundle() {
  const cases = RAW_CASES.map((_, index) => valuesForCase(index));
  const planDate = (index) => `2026-10-${String(6 + index).padStart(2, '0')}`;
  const calendarPlans = {};
  cases.forEach((values, index) => {
    calendarPlans[planDate(index)] = {
      title: values.title, status: 'planned', label: '计划中', time: 5,
      intensity: '低强度', body: '全身', focus: values.focus, notes: values.notes,
      items: [values.name + ' · ' + values.spec], itemRecords: [itemRecord(values)],
    };
  });
  return {
    format: 'qingdong-training-backup',
    version: 1,
    exportedAt: '2026-10-06T00:00:00.000Z',
    trainingState: {
      version: 1,
      updatedAt: '',
      data: {
        calendarPlans,
        customTrainingPlans: {
          [ATTACK_ID]: {
            id: ATTACK_ID, title: ATTACK_TITLE, time: 10, intensity: '低强度',
            scene: ATTACK_TITLE, reason: ATTACK_TITLE, items: [ATTACK_NAME + ' · ' + ATTACK_SPEC],
          },
        },
        dailySessions: {
          [TODAY]: {
            items: [itemRecord(cases[0])], source: ATTACK_TITLE, stepIndex: 0, setIndex: 0,
            actionElapsedSeconds: 0, actionStartedAt: null, skipped: [], records: [],
            pending: null, started: false, done: false, rest: false, updatedAt: '',
          },
        },
      },
    },
  };
}

function normalBundle() {
  const values = {
    title: '普通中文计划🧘 A & B <5kg "单双引号" \'quotes\'',
    name: '普通动作🧘 A & B <5kg',
    spec: '3 组 · 8 次 · A & B <5kg "单双引号"',
    description: '普通动作说明 A & B <5kg',
    focus: '普通焦点🧘',
    notes: '普通备注 A & B <5kg',
  };
  return {
    format: 'qingdong-training-backup', version: 1, exportedAt: '2026-10-06T00:00:00.000Z',
    trainingState: {
      version: 1, updatedAt: '', data: {
        calendarPlans: {
          [TODAY]: {
            title: values.title, status: 'planned', label: '计划中', time: 5,
            intensity: '低强度', body: '全身', focus: values.focus, notes: values.notes,
            items: [values.name + ' · ' + values.spec], itemRecords: [itemRecord(values)],
          },
        },
        customTrainingPlans: {},
        dailySessions: {
          [TODAY]: {
            items: [itemRecord(values)], source: values.title, stepIndex: 0, setIndex: 0,
            actionElapsedSeconds: 0, actionStartedAt: null, skipped: [], records: [], pending: null,
            started: false, done: false, rest: false, updatedAt: '',
          },
        },
      },
    },
  };
}

async function chooseBackup(page, payload, label) {
  const { dom } = page;
  const { document } = dom.window;
  dom.window.__qdApp.promptImportFile();
  const input = document.querySelector('input[type="file"]');
  assert(input, `${label}: file input was not created`);
  const file = new dom.window.File([JSON.stringify(payload)], `${label}.json`, { type: 'application/json' });
  Object.defineProperty(input, 'files', { configurable: true, value: [file] });
  input.dispatchEvent(new dom.window.Event('change', { bubbles: true }));
  await waitFor(() => !!document.querySelector('[data-import-confirm]'), `${label} preview`);
}

async function run() {
  const page = createPage();
  const { dom, state } = page;
  const { document } = dom.window;
  await waitFor(() => !!dom.window.__qdApp && state.calls.some((call) => call.url === '/api/plans/today'), 'production boot');
  await waitFor(() => dom.window.__qdApp.getTodayPlan().length === 1, 'initial readback');

  // Malformed version/schema keep the existing import semantics: an error
  // modal is shown, no POST is made, and local storage is untouched.
  const beforeMalformed = dom.window.localStorage.getItem('qd-training-state-v1');
  dom.window.__qdApp.importFromText(JSON.stringify({ format: 'qingdong-training-backup', version: 2, trainingState: {} }));
  await waitFor(() => document.getElementById('appModalCard').textContent.includes('版本不受支持'), 'malformed version error');
  assert(!document.querySelector('[data-import-confirm]') && state.imports.length === 0, 'malformed version reached confirmation/import');
  assert(dom.window.localStorage.getItem('qd-training-state-v1') === beforeMalformed, 'malformed version changed storage');
  document.querySelector('#appModalCard [data-modal-close]').click();
  dom.window.__qdApp.importFromText(JSON.stringify({ format: 'qingdong-training-backup', version: 1, trainingState: { version: 1, data: { calendarPlans: [], customTrainingPlans: {}, dailySessions: {} } } }));
  await waitFor(() => document.getElementById('appModalCard').textContent.includes('字段类型错误'), 'malformed schema error');
  assert(!document.querySelector('[data-import-confirm]') && state.imports.length === 0, 'malformed schema reached confirmation/import');
  assert(dom.window.localStorage.getItem('qd-training-state-v1') === beforeMalformed, 'malformed schema changed storage');
  document.querySelector('#appModalCard [data-modal-close]').click();

  // FileReader and input change: no POST or state mutation occurs in preview.
  const storageBeforePreview = dom.window.localStorage.getItem('qd-training-state-v1');
  const plansBeforePreview = JSON.stringify(state.plans);
  await chooseBackup(page, bundle(), 'attack');
  assert(state.imports.length === 0, 'preview sent an API import');
  assert(dom.window.localStorage.getItem('qd-training-state-v1') === storageBeforePreview, 'preview changed raw localStorage');
  assert(JSON.stringify(state.plans) === plansBeforePreview, 'preview changed mock backend plans');
  assert(!document.getElementById('appModalCard').textContent.includes(ATTACK_TITLE), 'preview leaked payload text');
  assertSafeRenderedPage(page, 'preview');

  // Confirmation performs the canonical POST and the subsequent readback.
  document.querySelector('[data-import-confirm]').click();
  await waitFor(() => state.imports.length === 1, 'canonical import POST');
  await waitFor(() => state.calls.filter((call) => call.url === '/api/plans/month?month=2026-10').length >= 2, 'canonical month readback');
  await waitFor(() => dom.window.__qdApp.getTodayPlan()[0] && dom.window.__qdApp.getTodayPlan()[0].name === ATTACK_NAME, 'canonical today readback');
  RAW_CASES.forEach((_, index) => {
    const values = valuesForCase(index);
    const date = `2026-10-${String(6 + index).padStart(2, '0')}`;
    const posted = state.imports[0].plans.find((plan) => plan.date === date);
    const readback = state.plans.find((plan) => plan.date === date);
    assert(posted && posted.title === values.title, `POST did not preserve ${values.label} title`);
    assert(readback && readback.title === values.title, `readback did not preserve ${values.label} title`);
    assert(readback.items[0].name === values.name && readback.items[0].spec === values.spec, `readback did not preserve ${values.label} item text`);
  });
  assert(!document.getElementById('appModalCard').textContent.includes('<b>test</b>'), 'success modal leaked active HTML');
  assertSafeRenderedPage(page, 'post-import');

  // Every requested related rendering path uses the same imported values.
  dom.window.__qdApp.renderTodayPlan();
  dom.window.__qdApp.renderWeek();
  dom.window.__qdApp.renderCalendarMonth();
  dom.window.__qdApp.renderDayModal(6);
  assert(document.getElementById('weekList').textContent.includes(ATTACK_TITLE), 'week title was not rendered as text');
  assert(document.getElementById('weekHint').textContent.includes(ATTACK_TITLE), 'week hint was not rendered as text');
  assert(document.getElementById('calendar').textContent.includes(ATTACK_TITLE), 'calendar title was not rendered as text');
  assert(document.getElementById('todayPlanList').textContent.includes(ATTACK_NAME) && document.getElementById('todayPlanList').textContent.includes(ATTACK_SPEC), 'today item/spec was not rendered as text');
  assert(document.getElementById('dayProgressSteps').textContent.includes(ATTACK_NAME), 'progress step was not rendered as text');
  assert(document.getElementById('dayProgressCaption').textContent.includes(ATTACK_NAME), 'progress caption was not rendered as text');
  const todayWeekButton = [...document.querySelectorAll('#weekList [data-date]')].find((button) => button.getAttribute('data-date') === TODAY);
  assert(todayWeekButton && todayWeekButton.getAttribute('data-plan') === ATTACK_TITLE, 'week data-plan attribute changed original text');
  assert(document.querySelector('#dayProgressTrack [title]').getAttribute('title') === ATTACK_NAME, 'progress title attribute changed original text');
  assert(document.querySelector('[data-remove-today]').getAttribute('data-remove-today') === ATTACK_NAME, 'remove attribute changed original text');
  assert(document.getElementById('appModalCard').textContent.includes(ATTACK_TITLE), 'day modal title was not rendered as text');
  assertSafeRenderedPage(page, 'day modal');

  dom.window.__qdApp.renderAdjustModal(6);
  assert(document.getElementById('appModalCard').textContent.includes(ATTACK_TITLE), 'adjust modal original title was not rendered as text');
  assertSafeRenderedPage(page, 'adjust modal');

  dom.window.__qdApp.renderTrainingPlans();
  const customButton = [...document.querySelectorAll('[data-start-plan]')].find((button) => button.getAttribute('data-start-plan') === ATTACK_ID);
  assert(customButton && customButton.getAttribute('data-start-plan') === ATTACK_ID, 'custom ID attribute changed original text');
  assert(document.getElementById('trainingPlanList').textContent.includes(ATTACK_TITLE), 'custom plan title was not rendered as text');
  assertSafeRenderedPage(page, 'custom plans');

  // The future candidate includes a server-returned title in currentLabel.
  customButton.closest('.list-card').querySelector('.plan-schedule-btn').click();
  await tick();
  assert(document.getElementById('appModalCard').textContent.includes(ATTACK_TITLE), 'schedule currentLabel/title was not rendered as text');
  assertSafeRenderedPage(page, 'schedule modal');

  // Raw storage remains raw business text, and a fresh canonical boot keeps it safe.
  const stored = JSON.parse(dom.window.localStorage.getItem('qd-training-state-v1'));
  const storedText = JSON.stringify(stored);
  const storedPlan = stored.data.calendarPlans[TODAY];
  const storedItem = storedPlan.itemRecords[0];
  assert(storedPlan.title === ATTACK_TITLE && storedItem.name === ATTACK_NAME && storedItem.spec === ATTACK_SPEC, 'storage did not preserve original text');
  assert(!storedText.includes('&lt;') && !storedText.includes('&gt;'), 'storage contains HTML entities and risks double encoding');
  const storedRawBeforeRefresh = dom.window.localStorage.getItem('qd-training-state-v1');
  const backendSnapshotBeforeRefresh = JSON.stringify(state.plans);
  const refreshed = createPage({ plans: state.plans, trainingStateRaw: storedRawBeforeRefresh });
  dom.window.close();
  await waitFor(() => !!refreshed.dom.window.__qdApp && refreshed.state.calls.some((call) => call.url === '/api/plans/today'), 'new JSDOM boot');
  await waitFor(() => refreshed.dom.window.__qdApp.getTodayPlan()[0] && refreshed.dom.window.__qdApp.getTodayPlan()[0].name === ATTACK_NAME, 'new JSDOM readback');
  const refreshedDocument = refreshed.dom.window.document;
  refreshed.dom.window.__qdApp.renderTodayPlan();
  refreshed.dom.window.__qdApp.renderWeek();
  refreshed.dom.window.__qdApp.renderCalendarMonth();
  refreshed.dom.window.__qdApp.renderDayModal(6);
  assert(refreshedDocument.getElementById('todayPlanList').textContent.includes(ATTACK_NAME), 'new JSDOM lost original action text');
  assert(refreshedDocument.getElementById('weekList').textContent.includes(ATTACK_TITLE), 'new JSDOM lost original title text');
  assert(refreshedDocument.getElementById('calendar').textContent.includes(ATTACK_TITLE), 'new JSDOM lost calendar text');
  refreshed.dom.window.__qdApp.renderTrainingPlans();
  const refreshedCustom = [...refreshedDocument.querySelectorAll('[data-start-plan]')].find((button) => button.getAttribute('data-start-plan') === ATTACK_ID);
  assert(refreshedCustom, 'new JSDOM lost custom plan ID');
  assert(JSON.stringify(refreshed.state.plans) === backendSnapshotBeforeRefresh, 'new JSDOM changed mock backend snapshot');
  assertSafeRenderedPage(refreshed, 'new JSDOM refresh');
  assert(!refreshed.errors.some((error) => /uncaught|syntaxerror/i.test(error)), `unexpected refreshed JSDOM errors: ${refreshed.errors.join('\n')}`);
  refreshed.dom.window.close();

  // A separate legal backup exercises import -> export -> import roundtrip.
  const normal = createPage();
  await waitFor(() => !!normal.dom.window.__qdApp && normal.state.calls.some((call) => call.url === '/api/plans/today'), 'normal boot');
  await chooseBackup(normal, normalBundle(), 'normal');
  const normalDocument = normal.dom.window.document;
  assert(normal.state.imports.length === 0, 'normal preview sent an API import');
  normalDocument.querySelector('[data-import-confirm]').click();
  await waitFor(() => normal.state.imports.length === 1, 'normal import POST');
  await waitFor(() => normal.dom.window.__qdApp.getTodayPlan()[0] && normal.dom.window.__qdApp.getTodayPlan()[0].name.includes('普通动作'), 'normal import readback');
  const exported = normal.dom.window.__qdApp.buildTrainingExportBundle();
  const rawBeforeRoundtrip = normal.dom.window.localStorage.getItem('qd-training-state-v1');
  await chooseBackup(normal, exported, 'normal-roundtrip');
  assert(normal.state.imports.length === 1, 'normal roundtrip preview sent an API import');
  assert(normal.dom.window.localStorage.getItem('qd-training-state-v1') === rawBeforeRoundtrip, 'normal roundtrip preview changed storage');
  normalDocument.querySelector('[data-import-confirm]').click();
  await waitFor(() => normal.state.imports.length === 2, 'normal roundtrip POST');
  await waitFor(() => normal.dom.window.__qdApp.getTodayPlan()[0] && normal.dom.window.__qdApp.getTodayPlan()[0].name.includes('普通动作'), 'normal roundtrip readback');
  const normalStored = JSON.parse(normal.dom.window.localStorage.getItem('qd-training-state-v1'));
  const normalStoredPlan = normalStored.data.calendarPlans[TODAY];
  assert(normalStoredPlan.title === normalBundle().trainingState.data.calendarPlans[TODAY].title, 'normal roundtrip changed title');
  assert(normalStoredPlan.itemRecords[0].name === normalBundle().trainingState.data.calendarPlans[TODAY].itemRecords[0].name, 'normal roundtrip changed action name');
  assert(!JSON.stringify(normalStored).includes('&lt;') && !JSON.stringify(normalStored).includes('&gt;'), 'normal roundtrip double-encoded text');
  normal.dom.window.__qdApp.renderTodayPlan();
  normal.dom.window.__qdApp.renderWeek();
  normal.dom.window.__qdApp.renderCalendarMonth();
  assertSafeRenderedPage(normal, 'normal roundtrip');
  await new Promise((resolve) => setTimeout(resolve, 25));
  normal.dom.window.close();

  console.log(JSON.stringify({
    PASS: true,
    previewPostCount: 0,
    importPostCount: state.imports.length,
    readbackMonthCount: state.calls.filter((call) => call.url === '/api/plans/month?month=2026-10').length,
    attackCases: RAW_CASES.map((item) => item[0]),
    normalRoundtripImports: normal.state.imports.length,
    marker: 0,
    paths: ['FileReader/change', 'preview', 'POST /api/plans/import', 'month readback', 'today readback', 'new JSDOM refresh', 'normal export/import roundtrip', 'week', 'calendar', 'today', 'day modal', 'adjust modal', 'schedule modal', 'custom plans'],
  }));
}

run().catch((error) => {
  console.error(error.stack || error);
  process.exitCode = 1;
});
