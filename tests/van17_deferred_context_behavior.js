'use strict';

const { createPage, response, waitFor, tick } = require('./f01_real_dom_behavior');

const todayPlan = {
  id: 41,
  date: '2026-10-03',
  title: '今日两轮训练',
  isTrainingDay: true,
  is_training: true,
  items: [{ id: 1, exercise_id: 9, name: '延迟动作', sets: 2, reps: 8, duration_seconds: 30, spec: '2 组 · 8 次' }],
};
const futurePlan = {
  id: 42,
  date: '2026-10-04',
  title: '未来训练',
  isTrainingDay: true,
  is_training: true,
  items: [{ id: 2, exercise_id: 9, name: '未来动作', sets: 2, reps: 8, duration_seconds: 30, spec: '2 组 · 8 次' }],
};

function fixture(pathname) {
  if (pathname === '/api/plans/today') return response(todayPlan);
  if (pathname.startsWith('/api/session/current?date=')) return response({ session: null });
  if (pathname === '/api/session/current?include_completed=true') return response({ session: null });
  if (pathname.startsWith('/api/plans/month?month=')) return response({ days: [todayPlan, futurePlan] });
  if (pathname.startsWith('/api/calendar?month=')) return response({ days: [] });
  if (pathname.startsWith('/api/stats/month/detail?month=')) return response({ days: [{ date: todayPlan.date, status: 'planned', is_training: true }, { date: futurePlan.date, status: 'planned', is_training: true }], training_days: 2, completed_days: 0 });
  if (pathname.startsWith('/api/stats/month?month=')) return response({ month: '2026-10', training_days: 2, completed_days: 0, completed: 0, completion_rate: 0, duration_seconds: 0 });
  if (pathname.startsWith('/api/stats/week/detail?date=')) return response({ days: [], training_days: 0, completed_days: 0 });
  if (pathname === '/api/exercises') return response({ exercises: [{ id: 9, name: '延迟动作' }, { id: 9, name: '未来动作' }] });
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
    if (pathname === '/api/session/start') {
      return Promise.resolve(response({
        status: 'started',
        session: { id: 8, plan_id: 41, status: 'in_progress', records: [{ exercise_id: 9, status: 'pending', sets_completed: 0, duration_seconds: null }] },
      }));
    }
    if (pathname === '/api/session/update' && body && body.session_id === 8 && body.sets_completed === 1) {
      return Promise.resolve(response({ status: 'updated', record: { session_id: 8, exercise_id: 9, status: 'pending', sets_completed: 1, duration_seconds: 21 } }));
    }
    if (pathname === '/api/session/update' && body && body.session_id === 8 && body.sets_completed === 2) {
      return new Promise((resolve) => { releaseFinalUpdate = () => resolve(response({ status: 'updated', record: { session_id: 8, exercise_id: 9, status: 'completed', sets_completed: 2, duration_seconds: 92 } })); });
    }
    if (pathname === '/api/session/complete') {
      return Promise.resolve(response({ status: 'completed', session: { id: body.session_id, plan_id: 41, status: 'completed' } }));
    }
    return Promise.resolve(fixture(pathname));
  };

  page.dom.window.document.getElementById('startTodayBtn').click();
  await waitFor(() => page.dom.window.__qdApp.getTodayExecutionState().started, 'session start');
  page.dom.window.document.getElementById('startTodayBtn').click();
  await waitFor(() => page.dom.window.__qdApp.getTodayExecutionState().setIndex === 1, 'first set');
  page.dom.window.document.getElementById('startTodayBtn').click();
  await waitFor(() => releaseFinalUpdate !== null, 'held final update');

  page.dom.window.__qdApp.renderDayModal(4);
  const futureStart = page.dom.window.document.querySelector('[data-start-day="4"]');
  if (!futureStart) throw new Error('future plan start action missing');
  futureStart.click();
  await tick();
  if (page.dom.window.__qdTrainingState.today().key !== '2026-10-04') throw new Error('future context was not selected');

  releaseFinalUpdate();
  await waitFor(() => calls.some((call) => call.pathname === '/api/session/complete'), 'old session completion');
  await tick();
  const state = page.dom.window.__qdApp.getTodayExecutionState();
  const starts = calls.filter((call) => call.pathname === '/api/session/start');
  const completes = calls.filter((call) => call.pathname === '/api/session/complete');
  if (starts.length !== 1 || starts[0].body.plan_id !== 41) throw new Error(JSON.stringify({ calls, state }));
  if (completes.length !== 1 || completes[0].body.session_id !== 8) throw new Error(JSON.stringify({ calls, state }));
  if (state.done || page.dom.window.__qdTrainingState.today().key !== '2026-10-04') throw new Error(JSON.stringify({ calls, state }));
  page.dom.window.close();
  console.log(JSON.stringify({ PASS: true, old_session: 8, selected_date: '2026-10-04', starts: starts.length, completes: completes.length }));
})().catch((error) => { console.error(error.stack || error); process.exit(1); });
