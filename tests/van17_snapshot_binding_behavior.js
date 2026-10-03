'use strict';

const { createPage, response, waitFor, tick } = require('./f01_real_dom_behavior');

let phase = 'training';
const trainingPlan = { id: 8, date: '2026-10-04', title: '训练 A', isTrainingDay: true, is_training: true, items: [{ id: 1, exercise_id: 1, name: '动作 A', sets: 2, reps: 8, duration_seconds: 30, spec: '2 组 · 8 次' }] };
const restPlan = { id: 8, date: '2026-10-04', title: '恢复日', isTrainingDay: false, is_training: false, items: [] };
const newPlan = { id: 8, date: '2026-10-04', title: '伸展计划', isTrainingDay: true, is_training: true, items: [{ id: 2, exercise_id: 2, name: '伸展', sets: 2, reps: 8, duration_seconds: 30, spec: '2 组 · 8 次' }] };
function currentPlan() { return phase === 'rest' ? restPlan : (phase === 'new' ? newPlan : trainingPlan); }
function fixture(pathname) {
  if (pathname === '/api/plans/today') return response(currentPlan());
  if (pathname.startsWith('/api/session/current?date=')) return response({ session: null });
  if (pathname === '/api/session/current?include_completed=true') return response({ session: null });
  if (pathname.startsWith('/api/plans/month?month=')) return response({ days: [currentPlan()] });
  if (pathname.startsWith('/api/calendar?month=')) return response({ days: [] });
  if (pathname.startsWith('/api/stats/month/detail?month=')) return response({ days: [{ date: currentPlan().date, status: phase === 'rest' ? 'rest' : 'planned', is_training: phase !== 'rest' }], training_days: phase === 'rest' ? 0 : 1, completed_days: 0 });
  if (pathname.startsWith('/api/stats/month?month=')) return response({ month: '2026-10', training_days: phase === 'rest' ? 0 : 1, completed_days: 0, completed: 0, completion_rate: 0, duration_seconds: 0 });
  if (pathname.startsWith('/api/stats/week/detail?date=')) return response({ days: [], training_days: 0, completed_days: 0 });
  if (pathname === '/api/exercises') return response({ exercises: [{ id: 1, name: '动作 A' }, { id: 2, name: '伸展' }] });
  if (pathname === '/api/templates') return response({ templates: [] });
  if (pathname === '/api/favorites') return response({ favorites: [] });
  if (pathname === '/api/ai/provider') return response({ provider: 'local-demo', model: '' });
  if (pathname === '/api/ai/models') return response({ models: [] });
  throw new Error(`unexpected API path: ${pathname}`);
}

(async () => {
  const page = createPage({ date: [2026, 9, 4], seedOldState: false, fetchOverride: (pathname) => Promise.resolve(fixture(pathname)) });
  await waitFor(() => page.dom.window.__qdApp.getTodayPlan().length === 1, 'training plan');
  const calls = [];
  page.dom.window.fetch = (pathname, options = {}) => {
    const body = options.body ? JSON.parse(options.body) : null;
    calls.push({ pathname, body });
    if (pathname === '/api/session/start') {
      const id = phase === 'training' ? 15 : 16;
      const exerciseId = phase === 'training' ? 1 : 2;
      return Promise.resolve(response({ status: 'started', session: { id, plan_id: 8, status: 'in_progress', records: [{ exercise_id: exerciseId, status: 'pending', sets_completed: 0, duration_seconds: null }] } }));
    }
    if (pathname === '/api/session/update') {
      const target = body.session_id === 15 ? 1 : 2;
      const complete = body.sets_completed === 2;
      return Promise.resolve(response({ status: 'updated', record: { session_id: body.session_id, exercise_id: target, status: complete ? 'completed' : 'pending', sets_completed: body.sets_completed, duration_seconds: body.duration_seconds } }));
    }
    if (pathname === '/api/session/complete') return Promise.resolve(response({ status: 'completed', session: { id: body.session_id, plan_id: 8, status: 'completed' } }));
    if (pathname === '/api/plans/by-date/2026-10-04') {
      if (!body.is_training_day) phase = 'rest';
      else if ((body.items || []).some((item) => item.exercise_id === 2)) phase = 'new';
      else trainingPlan.title = body.title || trainingPlan.title;
      return Promise.resolve(response({ status: 'saved', plan: currentPlan() }));
    }
    return Promise.resolve(fixture(pathname));
  };

  const start = page.dom.window.document.getElementById('startTodayBtn');
  start.click();
  await waitFor(() => page.dom.window.__qdApp.getTodayExecutionState().started, 'old session start');
  start.click();
  await waitFor(() => page.dom.window.__qdApp.getTodayExecutionState().setIndex === 1, 'partial old session');

  page.dom.window.__qdApp.replaceDayPlan(4, { title: '标题改动', time: 5, intensity: '低', scene: '元数据', reason: '', items: [{ name: '动作 A', exercise_id: 1, sets: 2, reps: 8, duration_seconds: 30, spec: '2 组 · 8 次' }] });
  await waitFor(() => page.dom.window.document.getElementById('todayTitle').textContent.includes('标题改动'), 'metadata save');
  const afterMetadata = page.dom.window.__qdApp.getTodayExecutionState();
  if (!afterMetadata.started || afterMetadata.setIndex !== 1 || afterMetadata.records[0].setsCompleted !== 1) throw new Error(JSON.stringify(afterMetadata));

  start.click();
  await waitFor(() => page.dom.window.__qdApp.getTodayExecutionState().done, 'old completion');
  page.dom.window.document.getElementById('clearTodayBtn').click();
  await waitFor(() => phase === 'rest' && page.dom.window.document.getElementById('dayHero').getAttribute('data-today-state') === 'empty', 'rest replacement');
  await waitFor(() => page.dom.window.__qdApp.exerciseDetails['伸展'], 'new exercise');
  page.dom.window.__qdApp.addToToday('伸展');
  await waitFor(() => phase === 'new' && page.dom.window.__qdApp.getTodayPlan().length > 0 && page.dom.window.__qdApp.getTodayPlan()[0].name === '伸展', 'new training replacement');
  page.dom.window.document.getElementById('startTodayBtn').click();
  await waitFor(() => page.dom.window.__qdApp.getTodayExecutionState().started && calls.some((call) => call.pathname === '/api/session/start' && call.body.plan_id === 8), 'new session start');
  page.dom.window.document.getElementById('startTodayBtn').click();
  await waitFor(() => calls.some((call) => call.pathname === '/api/session/update' && call.body.session_id === 16));
  if (calls.some((call) => call.pathname === '/api/session/update' && call.body.session_id === 15 && call.body.sets_completed > 2)) throw new Error(JSON.stringify(calls));
  page.dom.window.close();
  console.log(JSON.stringify({ PASS: true, metadata_partial_sets: 1, old_session: 15, new_session: 16, phase }));
})().catch((error) => { console.error(error.stack || error); process.exit(1); });
