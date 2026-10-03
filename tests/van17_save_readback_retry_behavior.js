'use strict';

const { createPage, response, waitFor, tick } = require('./f01_real_dom_behavior');

const trainingPlan = { id: 41, date: '2026-10-03', title: '今日计划', isTrainingDay: true, is_training: true, items: [{ id: 1, exercise_id: 9, name: '动作', sets: 1, reps: 8 }] };
const restPlan = { id: 41, date: '2026-10-03', title: '恢复日', isTrainingDay: false, is_training: false, items: [] };
let saved = false;
let rangeFail = false;
function fixture(pathname) {
  if (pathname === '/api/plans/today') return response(saved ? restPlan : trainingPlan);
  if (pathname.startsWith('/api/session/current?date=')) return response({ session: null });
  if (pathname === '/api/session/current?include_completed=true') return response({ session: null });
  if (pathname.startsWith('/api/plans/month?month=') && rangeFail) return response({ detail: 'readback unavailable' }, 503);
  if (pathname.startsWith('/api/plans/month?month=')) return response({ days: [saved ? restPlan : trainingPlan] });
  if (pathname.startsWith('/api/calendar?month=')) return response({ days: [] });
  if (pathname.startsWith('/api/stats/month/detail?month=')) return response({ days: [{ date: '2026-10-03', status: saved ? 'rest' : 'planned', is_training: !saved }], training_days: saved ? 0 : 1, completed_days: 0 });
  if (pathname.startsWith('/api/stats/month?month=')) return response({ month: '2026-10', training_days: saved ? 0 : 1, completed_days: 0, completed: 0, completion_rate: 0, duration_seconds: 0 });
  if (pathname.startsWith('/api/stats/week/detail?date=')) return response({ days: [], training_days: 0, completed_days: 0 });
  if (pathname === '/api/exercises') return response({ exercises: [{ id: 9, name: '动作' }] });
  if (pathname === '/api/templates') return response({ templates: [] });
  if (pathname === '/api/favorites') return response({ favorites: [] });
  if (pathname === '/api/ai/provider') return response({ provider: 'local-demo', model: '' });
  if (pathname === '/api/ai/models') return response({ models: [] });
  throw new Error(`unexpected API path: ${pathname}`);
}

(async () => {
  const page = createPage({ date: [2026, 9, 3], seedOldState: false, fetchOverride: (pathname) => Promise.resolve(fixture(pathname)) });
  await waitFor(() => page.dom.window.__qdApp.getTodayPlan().length === 1, 'today plan');
  rangeFail = true;
  page.dom.window.fetch = (pathname, options = {}) => {
    if (pathname === '/api/plans/by-date/2026-10-03') {
      saved = true;
      return Promise.resolve(response({ status: 'saved', plan: restPlan }));
    }
    return Promise.resolve(fixture(pathname));
  };
  page.dom.window.document.getElementById('clearTodayBtn').click();
  await waitFor(() => page.dom.window.document.getElementById('dayHero').getAttribute('data-today-state') === 'error', 'readback error');
  const errorTitle = page.dom.window.document.getElementById('todayTitle').textContent;
  if (!page.dom.window.document.querySelector('[data-v25-retry-today]') || !errorTitle.includes('今日计划读取失败')) throw new Error(errorTitle);
  rangeFail = false;
  page.dom.window.document.querySelector('[data-v25-retry-today]').click();
  await waitFor(() => page.dom.window.document.getElementById('dayHero').getAttribute('data-today-state') === 'empty', 'retry empty');
  if (page.dom.window.document.getElementById('dayHero').getAttribute('data-today-state') === 'loading') throw new Error('stuck loading');
  page.dom.window.close();
  console.log(JSON.stringify({ PASS: true, errorTitle, retryState: 'empty', saved }));
})().catch((error) => { console.error(error.stack || error); process.exit(1); });
