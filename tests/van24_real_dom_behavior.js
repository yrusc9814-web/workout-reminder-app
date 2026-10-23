'use strict';

// VAN-24 production-page check: duplicate occurrences are matched by their
// backend record identity and a range default remains display text instead of
// becoming the first numeric endpoint.
const { createPage, response, waitFor, tick } = require('./f01_real_dom_behavior');

const TODAY = '2026-10-02';
const plan = {
  date: TODAY,
  id: 101,
  title: 'VAN-24 重复动作',
  is_training: true,
  isTrainingDay: true,
  items: [
    { id: 11, exercise_id: 9, name: '重复动作', sets: 1, reps: 8, spec: '1 组 · 8 次', sort_order: 1 },
    { id: 12, exercise_id: 10, name: '中间动作', sets: 1, reps: null, duration_seconds: 60, spec: '1 组 · 60 秒', sort_order: 2 },
    { id: 13, exercise_id: 9, name: '重复动作', sets: 1, reps: 8, spec: '1 组 · 8 次', sort_order: 3 },
    { id: 14, exercise_id: 11, name: '第三动作', sets: 1, reps: 8, spec: '原始显示范围 8-12 次', sort_order: 4 },
    { id: 15, exercise_id: 9, name: '重复动作', sets: 1, reps: 8, spec: '1 组 · 8 次', sort_order: 5 },
  ],
};

let currentPlan = JSON.parse(JSON.stringify(plan));

function fixture(pathname, control) {
  if (pathname === '/api/plans/today') return response(currentPlan);
  if (pathname.startsWith('/api/plans/month?')) return response({ days: [currentPlan] });
  if (pathname.startsWith('/api/calendar?')) return response({ days: [currentPlan] });
  if (pathname.startsWith('/api/stats/month/detail?')) return response({ days: [{ date: TODAY, status: 'planned', is_training: true }], training_days: 1, completed_days: 0 });
  if (pathname.startsWith('/api/stats/month?')) return response({ month: '2026-10', training_days: 1, completed_days: 0, completed_days: 0, completion_rate: 0, duration_seconds: 0 });
  if (pathname.startsWith('/api/stats/week/detail?')) return response({ days: [], training_days: 0, completed_days: 0 });
  if (pathname === '/api/exercises') return response({ exercises: [
    { id: 9, name: '重复动作', default_sets: 1, default_reps: '8' },
    { id: 10, name: '中间动作', default_sets: 1, default_reps: '8' },
    { id: 11, name: '第三动作', default_sets: 1, default_reps: '8' },
    { id: 20, name: '范围动作', default_sets: 2, default_reps: '8-12', duration_seconds: null },
  ] });
  if (pathname === '/api/templates') return response({ templates: [] });
  if (pathname === '/api/favorites') return response({ favorites: [] });
  if (pathname === '/api/ai/provider') return response({ provider: 'local-demo', model: '' });
  if (pathname === '/api/ai/models') return response({ models: [] });
  if (pathname.startsWith('/api/session/current?')) return response({ session: null });
  if (pathname === '/api/plans/by-date/' + TODAY && control.lastPlanSave) return response({ status: 'saved', plan: plan });
  return response({});
}

(async () => {
  const calls = [];
  const page = createPage({
    date: [2026, 9, 2],
    seedOldState: false,
    fetchOverride: (pathname, control) => Promise.resolve(fixture(String(pathname), control)),
  });
  await waitFor(() => page.dom.window.__qdApp.getTodayPlan().length === 5, 'duplicate plan hydration');
  calls.length = 0;
  page.dom.window.fetch = function (pathname, options = {}) {
    const value = String(pathname);
    let body = null;
    try { body = options.body ? JSON.parse(options.body) : null; } catch (_) { body = options.body; }
    calls.push({ pathname: value, body });
    if (value === '/api/session/start') {
        return Promise.resolve(response({
          status: 'started',
          session: {
            id: 77,
            plan_id: 101,
            status: 'in_progress',
            records: [
              { id: 501, record_id: 501, exercise_id: 10, plan_item_order: 1, status: 'pending', sets_completed: 0 },
              { id: 502, record_id: 502, exercise_id: 9, plan_item_order: 2, status: 'pending', sets_completed: 0 },
              { id: 503, record_id: 503, exercise_id: 11, plan_item_order: 3, status: 'pending', sets_completed: 0 },
              { id: 504, record_id: 504, exercise_id: 9, plan_item_order: 4, status: 'pending', sets_completed: 0 },
            ],
          },
        }));
    }
    if (value === '/api/session/update') {
        return Promise.resolve(response({
          status: 'updated',
          record: { id: body.record_id, record_id: body.record_id, session_id: 77, exercise_id: body.exercise_id, plan_item_order: body.record_id - 500, status: 'completed', sets_completed: 1, duration_seconds: 10 },
        }));
    }
    if (value === '/api/session/complete') return Promise.resolve(response({ status: 'completed', session: { id: 77, plan_id: 101, status: 'completed' } }));
    if (value === '/api/plans/by-date/' + TODAY) {
        const rangeItem = body && Array.isArray(body.items) ? body.items.find((item) => item.exercise_id === 20) : null;
        if (rangeItem && rangeItem.reps == null) {
          calls[calls.length - 1].status = 422;
          return Promise.resolve(response({ detail: '动作次数范围不能隐式转换为单值' }, 422));
        }
        page.control.lastPlanSave = true;
        calls[calls.length - 1].status = 200;
        currentPlan = Object.assign({}, currentPlan, {
          items: body.items.map((item, index) => Object.assign({}, item, { id: 100 + index, sort_order: index + 1 }))
        });
        return Promise.resolve(response({ status: 'saved', plan: currentPlan }));
    }
    return Promise.resolve(fixture(value, page.control));
  };
  await page.dom.window.__qdApp.bootCanonical();
  await waitFor(() => page.dom.window.__qdApp.getTodayPlan().length === 5, 'duplicate plan rehydration');

  const firstRemove = page.dom.window.document.querySelector('[data-remove-today-index="0"]');
  if (!firstRemove) throw new Error('occurrence remove control missing');
  firstRemove.click();
  await waitFor(() => calls.some((call) => call.pathname === '/api/plans/by-date/' + TODAY && call.status === 200), 'occurrence removal save');
  await waitFor(() => page.dom.window.__qdApp.getTodayPlan().length === 4, 'occurrence removal readback');
  const remainingNames = page.dom.window.__qdApp.getTodayPlan().map((item) => item.name);
  if (JSON.stringify(remainingNames) !== JSON.stringify(['中间动作', '重复动作', '第三动作', '重复动作'])) {
    throw new Error(`wrong occurrence removed: ${JSON.stringify(remainingNames)}`);
  }
  const savedOccurrencePlan = calls.find((call) => call.pathname === '/api/plans/by-date/' + TODAY && call.status === 200);
  const explicitRange = savedOccurrencePlan && savedOccurrencePlan.body.items.find((item) => item.exercise_id === 11);
  if (!explicitRange || explicitRange.reps !== 8 || !String(explicitRange.spec).includes('8-12')) {
    throw new Error(`explicit scalar/range display was not preserved: ${JSON.stringify(savedOccurrencePlan && savedOccurrencePlan.body)}`);
  }
  if (page.dom.window.__qdApp.getTodayPlan()[0].reps !== null || page.dom.window.__qdApp.getTodayPlan()[0].duration_seconds !== 60) {
    throw new Error(`explicit nullable fields changed: ${JSON.stringify(page.dom.window.__qdApp.getTodayPlan()[0])}`);
  }

  const start = page.dom.window.document.getElementById('startTodayBtn');
  start.click();
  await waitFor(() => page.dom.window.__qdApp.getTodayExecutionState().started, 'remote session start');
  start.click();
  await waitFor(() => calls.filter((call) => call.pathname === '/api/session/update').length === 1, 'first record update');
  await waitFor(() => page.dom.window.__qdApp.getTodayExecutionState().stepIndex === 1, 'first record applied');
  start.click();
  start.click();
  await waitFor(() => calls.filter((call) => call.pathname === '/api/session/update').length === 2, 'second record update');
  await waitFor(() => page.dom.window.__qdApp.getTodayExecutionState().stepIndex === 2, 'second record applied');
  start.click();
  start.click();
  await waitFor(() => calls.filter((call) => call.pathname === '/api/session/update').length === 3, 'third record update');
  await waitFor(() => page.dom.window.__qdApp.getTodayExecutionState().stepIndex === 3, 'third record applied');
  start.click();
  start.click();
  await waitFor(() => calls.filter((call) => call.pathname === '/api/session/update').length === 4, 'fourth record update');

  const updates = calls.filter((call) => call.pathname === '/api/session/update');
  const recordIds = updates.map((call) => call.body.record_id);
  if (JSON.stringify(recordIds) !== JSON.stringify([501, 502, 503, 504])) throw new Error(`record identity mismatch: ${JSON.stringify(updates)}`);
  if (updates.some((call) => call.body.record_id == null)) throw new Error('production UI omitted record_id');

  // The exercise library still displays a range, but the add-to-plan payload
  // must not invent reps=8 from that range.
  page.dom.window.__qdApp.addToToday('范围动作');
  await waitFor(() => calls.some((call) => call.pathname === '/api/plans/by-date/' + TODAY), 'range plan save');
  const save = calls.find((call) => call.pathname === '/api/plans/by-date/' + TODAY && call.body.items.some((item) => item.exercise_id === 20));
  const rangeItem = save && save.body && save.body.items.find((item) => item.exercise_id === 20);
  if (!save || save.status !== 422 || !rangeItem || Object.prototype.hasOwnProperty.call(rangeItem, 'reps') || !String(rangeItem.spec).includes('8-12')) {
    throw new Error(`range scalar conversion: ${JSON.stringify(save && save.body)}`);
  }
  console.log(JSON.stringify({ PASS: true, record_ids: recordIds, range_rejected: save.status, range_spec: rangeItem.spec }));
})().catch((error) => { console.error(error.stack || error); process.exit(1); });
