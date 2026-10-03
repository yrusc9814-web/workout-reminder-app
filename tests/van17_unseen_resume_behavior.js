'use strict';

const { createPage, response, waitFor, tick } = require('./f01_real_dom_behavior');

const todayPlan = { id: 41, date: '2026-10-03', title: '今日计划', isTrainingDay: true, is_training: true, items: [{ id: 1, exercise_id: 9, name: '今日动作', sets: 1, reps: 8 }] };
const historicalPlan = { id: 6, date: '2026-09-30', title: '历史三组计划', isTrainingDay: true, is_training: true, items: [{ id: 6, exercise_id: 9, name: '历史三组动作', sets: 3, reps: 8, duration_seconds: 30, spec: '3 组 · 8 次' }] };

function fixture(pathname) {
  if (pathname === '/api/plans/today') return response(todayPlan);
  if (pathname.startsWith('/api/session/current?date=')) return response({ session: null });
  if (pathname === '/api/session/current?include_completed=true') return response({ session: null });
  if (pathname.startsWith('/api/plans/month?month=2026-09')) return response({ days: [historicalPlan] });
  if (pathname.startsWith('/api/plans/month?month=')) return response({ days: [todayPlan] });
  if (pathname.startsWith('/api/calendar?month=')) return response({ days: [] });
  if (pathname.startsWith('/api/stats/month/detail?month=')) return response({ days: [{ date: historicalPlan.date, status: 'planned', is_training: true }], training_days: 1, completed_days: 0 });
  if (pathname.startsWith('/api/stats/month?month=')) return response({ month: '2026-09', training_days: 1, completed_days: 0, completed: 0, completion_rate: 0, duration_seconds: 0 });
  if (pathname.startsWith('/api/stats/week/detail?date=')) return response({ days: [], training_days: 0, completed_days: 0 });
  if (pathname === '/api/exercises') return response({ exercises: [{ id: 9, name: '历史三组动作' }, { id: 9, name: '今日动作' }] });
  if (pathname === '/api/templates') return response({ templates: [] });
  if (pathname === '/api/favorites') return response({ favorites: [] });
  if (pathname === '/api/ai/provider') return response({ provider: 'local-demo', model: '' });
  if (pathname === '/api/ai/models') return response({ models: [] });
  throw new Error(`unexpected API path: ${pathname}`);
}

(async () => {
  const page = createPage({ date: [2026, 9, 3], seedOldState: false, fetchOverride: (pathname) => Promise.resolve(fixture(pathname)) });
  await waitFor(() => page.dom.window.__qdApp.getTodayPlan().length === 1, 'today plan');
  page.dom.window.fetch = (pathname, options = {}) => {
    const body = options.body ? JSON.parse(options.body) : null;
    if (pathname === '/api/session/start' && body && body.plan_id === 6) {
      return Promise.resolve(response({
        status: 'resumed',
        session: { id: 10, plan_id: 6, status: 'in_progress', records: [{ exercise_id: 9, status: 'pending', sets_completed: 1, duration_seconds: 21 }] },
      }));
    }
    return Promise.resolve(fixture(pathname));
  };
  page.dom.window.__qdApp.shiftDisplayMonth(-1);
  await waitFor(() => page.dom.window.document.getElementById('calendar').getAttribute('data-month-status') === 'ready', 'historical month');
  page.dom.window.__qdApp.renderDayModal(30);
  const startDay = page.dom.window.document.querySelector('[data-start-day="30"]');
  if (!startDay) throw new Error('historical start action missing');
  startDay.click();
  await waitFor(() => page.dom.window.__qdTrainingState.today().key === '2026-09-30', 'historical selection');
  page.dom.window.document.getElementById('startTodayBtn').click();
  await waitFor(() => {
    const state = page.dom.window.__qdApp.getTodayExecutionState();
    return state.started && state.setIndex === 1 && state.actionElapsedSeconds === 21;
  }, 'resumed partial session');
  const state = page.dom.window.__qdApp.getTodayExecutionState();
  const summary = page.dom.window.document.getElementById('todaySummary').textContent;
  const button = page.dom.window.document.getElementById('startTodayBtn').textContent;
  if (state.done || state.records[0].setsCompleted !== 1 || state.records[0].durationSeconds !== 21 || !summary.includes('实际执行 21 秒') || !button.includes('第 2 组')) {
    throw new Error(JSON.stringify({ state, summary, button }));
  }
  page.dom.window.close();
  console.log(JSON.stringify({ PASS: true, date: '2026-09-30', sets: state.records[0].setsCompleted, duration: state.records[0].durationSeconds, button }));
})().catch((error) => { console.error(error.stack || error); process.exit(1); });
