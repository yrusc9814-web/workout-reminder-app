'use strict';

const { createPage, response, waitFor, tick } = require('./f01_real_dom_behavior');

const todayPlan = { id: 41, date: '2026-10-03', title: '今日计划', isTrainingDay: true, is_training: true, items: [{ id: 1, exercise_id: 9, name: '今日动作', sets: 1, reps: 8 }] };
const futurePlan = { id: 42, date: '2026-10-04', title: '未来计划', isTrainingDay: true, is_training: true, items: [{ id: 2, exercise_id: 9, name: '未来动作', sets: 1, reps: 8 }] };

function fixture(pathname) {
  if (pathname === '/api/plans/today') return response(todayPlan);
  if (pathname.startsWith('/api/session/current?date=')) return response({ session: null });
  if (pathname === '/api/session/current?include_completed=true') return response({ session: null });
  if (pathname.startsWith('/api/plans/month?month=')) return response({ days: [todayPlan, futurePlan] });
  if (pathname.startsWith('/api/calendar?month=')) return response({ days: [] });
  if (pathname.startsWith('/api/stats/month/detail?month=')) return response({ days: [{ date: todayPlan.date, status: 'planned', is_training: true }, { date: futurePlan.date, status: 'planned', is_training: true }], training_days: 2, completed_days: 0 });
  if (pathname.startsWith('/api/stats/month?month=')) return response({ month: '2026-10', training_days: 2, completed_days: 0, completed: 0, completion_rate: 0, duration_seconds: 0 });
  if (pathname.startsWith('/api/stats/week/detail?date=')) return response({ days: [], training_days: 0, completed_days: 0 });
  if (pathname === '/api/exercises') return response({ exercises: [{ id: 9, name: '今日动作' }, { id: 9, name: '未来动作' }] });
  if (pathname === '/api/templates') return response({ templates: [] });
  if (pathname === '/api/favorites') return response({ favorites: [] });
  if (pathname === '/api/ai/provider') return response({ provider: 'local-demo', model: '' });
  if (pathname === '/api/ai/models') return response({ models: [] });
  throw new Error(`unexpected API path: ${pathname}`);
}

(async () => {
  const page = createPage({ date: [2026, 9, 3], seedOldState: false, fetchOverride: (pathname) => Promise.resolve(fixture(pathname)) });
  await waitFor(() => page.dom.window.__qdApp.getTodayPlan().length === 1, 'today plan');
  let releaseSave = null;
  page.dom.window.fetch = (pathname, options = {}) => {
    if (pathname === '/api/plans/by-date/2026-10-03') {
      return new Promise((resolve) => { releaseSave = () => resolve(response({ status: 'saved', plan: { id: 41, date: todayPlan.date, title: '保存中的旧日期方案', isTrainingDay: true, items: [{ id: 9, exercise_id: 9, name: '保存中的旧动作', sets: 1, reps: 8 }] } })); });
    }
    return Promise.resolve(fixture(pathname));
  };
  page.dom.window.__qdApp.startPlan({ remote: false, title: '保存中的旧日期方案', time: 5, items: ['保存中的旧动作 · 1 组 · 8 次'] }, todayPlan.date);
  await waitFor(() => releaseSave !== null, 'held plan save');
  page.dom.window.__qdApp.renderDayModal(4);
  const futureStart = page.dom.window.document.querySelector('[data-start-day="4"]');
  if (!futureStart) throw new Error('future plan action missing');
  futureStart.click();
  await tick();
  releaseSave();
  await tick();
  await tick();
  const state = page.dom.window.__qdTrainingState.today();
  const title = page.dom.window.document.getElementById('todayTitle').textContent;
  if (state.key !== futurePlan.date || !title.includes('未来计划') || title.includes('保存中的旧日期方案')) {
    throw new Error(JSON.stringify({ state, title }));
  }
  page.dom.window.close();
  console.log(JSON.stringify({ PASS: true, selected_date: state.key, title }));
})().catch((error) => { console.error(error.stack || error); process.exit(1); });
