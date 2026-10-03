'use strict';

const { createPage, response, waitFor, tick } = require('./f01_real_dom_behavior');

const plan = { id: 41, date: '2026-10-03', title: '两组训练', isTrainingDay: true, is_training: true, items: [{ id: 1, exercise_id: 9, name: '延迟动作', sets: 2, reps: 8, duration_seconds: 30, spec: '2 组 · 8 次' }] };
function fixture(pathname) {
  if (pathname === '/api/plans/today') return response(plan);
  if (pathname.startsWith('/api/session/current?date=')) return response({ session: null });
  if (pathname === '/api/session/current?include_completed=true') return response({ session: null });
  if (pathname.startsWith('/api/plans/month?month=')) return response({ days: [plan] });
  if (pathname.startsWith('/api/calendar?month=')) return response({ days: [] });
  if (pathname.startsWith('/api/stats/month/detail?month=')) return response({ days: [{ date: plan.date, status: 'planned', is_training: true }], training_days: 1, completed_days: 0 });
  if (pathname.startsWith('/api/stats/month?month=')) return response({ month: '2026-10', training_days: 1, completed_days: 0, completed: 0, completion_rate: 0, duration_seconds: 0 });
  if (pathname.startsWith('/api/stats/week/detail?date=')) return response({ days: [], training_days: 0, completed_days: 0 });
  if (pathname === '/api/exercises') return response({ exercises: [{ id: 9, name: '延迟动作' }] });
  if (pathname === '/api/templates') return response({ templates: [] });
  if (pathname === '/api/favorites') return response({ favorites: [] });
  if (pathname === '/api/ai/provider') return response({ provider: 'local-demo', model: '' });
  if (pathname === '/api/ai/models') return response({ models: [] });
  throw new Error(`unexpected API path: ${pathname}`);
}

(async () => {
  const page = createPage({ date: [2026, 9, 3], seedOldState: false, fetchOverride: (pathname) => Promise.resolve(fixture(pathname)) });
  await waitFor(() => page.dom.window.__qdApp.getTodayPlan().length === 1, 'today plan');
  const calls = [];
  let releaseFinalUpdate = null;
  page.dom.window.fetch = (pathname, options = {}) => {
    const body = options.body ? JSON.parse(options.body) : null;
    calls.push({ pathname, body });
    if (pathname === '/api/session/start') return Promise.resolve(response({ status: 'started', session: { id: 8, plan_id: 41, status: 'in_progress', records: [{ exercise_id: 9, status: 'pending', sets_completed: 0, duration_seconds: null }] } }));
    if (pathname === '/api/session/update' && body && body.sets_completed === 1) return Promise.resolve(response({ status: 'updated', record: { session_id: 8, exercise_id: 9, status: 'pending', sets_completed: 1, duration_seconds: 21 } }));
    if (pathname === '/api/session/update' && body && body.sets_completed === 2) return new Promise((resolve) => { releaseFinalUpdate = () => resolve(response({ status: 'updated', record: { session_id: 8, exercise_id: 9, status: 'completed', sets_completed: 2, duration_seconds: 36 } })); });
    if (pathname === '/api/plans/by-date/2026-10-03') return Promise.resolve(response({ detail: { code: 'SESSION_LOCKED', message: 'active session' } }, 409));
    if (pathname === '/api/session/complete') return Promise.resolve(response({ status: 'completed', session: { id: 8, plan_id: 41, status: 'completed' } }));
    return Promise.resolve(fixture(pathname));
  };
  const start = page.dom.window.document.getElementById('startTodayBtn');
  start.click();
  await waitFor(() => page.dom.window.__qdApp.getTodayExecutionState().started, 'start');
  start.click();
  await waitFor(() => page.dom.window.__qdApp.getTodayExecutionState().setIndex === 1, 'first set');
  start.click();
  await waitFor(() => releaseFinalUpdate !== null, 'held update');
  page.dom.window.document.getElementById('clearTodayBtn').click();
  await waitFor(() => calls.some((call) => call.pathname === '/api/plans/by-date/2026-10-03'), 'failed plan save');
  releaseFinalUpdate();
  await waitFor(() => calls.some((call) => call.pathname === '/api/session/complete'), 'completion after failed edit');
  await tick();
  const state = page.dom.window.__qdApp.getTodayExecutionState();
  if (!state.done || state.records[0].setsCompleted !== 2 || state.records[0].durationSeconds !== 36 || page.dom.window.document.getElementById('startTodayBtn').disabled !== true) {
    throw new Error(JSON.stringify({ state, calls }));
  }
  page.dom.window.close();
  console.log(JSON.stringify({ PASS: true, session: 8, sets: state.records[0].setsCompleted, duration: state.records[0].durationSeconds }));
})().catch((error) => { console.error(error.stack || error); process.exit(1); });
