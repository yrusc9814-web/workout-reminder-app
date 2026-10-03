'use strict';

const { createPage, response, waitFor, tick } = require('./f01_real_dom_behavior');

const todayPlan = { id: 41, date: '2026-10-03', title: '今日真实计划', isTrainingDay: true, is_training: true, items: [{ id: 1, exercise_id: 9, name: '今日动作', sets: 2, reps: 8 }] };
const selectedDate = '2026-09-30';

function fixture(pathname) {
  if (pathname === '/api/plans/today') return Promise.resolve(response(todayPlan));
  if (pathname.startsWith('/api/session/current?date=')) return Promise.resolve(response({ session: null }));
  if (pathname === '/api/session/current?include_completed=true') return Promise.resolve(response({
    session: { id: 10, plan_id: 6, status: 'in_progress', date: '2026-09-30', records: [{ exercise_id: 9, status: 'pending', sets_completed: 1, duration_seconds: 21 }] },
    plan: { id: 6, date: '2026-09-30', title: '旧日期活动计划', isTrainingDay: true, items: [{ id: 6, exercise_id: 9, name: '旧日期动作', sets: 3 }] },
  }));
  if (pathname.includes('month=2026-09')) return Promise.resolve(response({ detail: 'selected range unavailable' }, 503));
  if (pathname.startsWith('/api/plans/month?month=2026-10')) return Promise.resolve(response({ days: [todayPlan] }));
  if (pathname.startsWith('/api/calendar?month=2026-10')) return Promise.resolve(response({ days: [] }));
  if (pathname.startsWith('/api/stats/month/detail?month=2026-10')) return Promise.resolve(response({ days: [{ date: todayPlan.date, status: 'planned', is_training: true }], training_days: 1, completed_days: 0 }));
  if (pathname.startsWith('/api/stats/month?month=2026-10')) return Promise.resolve(response({ month: '2026-10', training_days: 1, completed_days: 0, completed: 0, completion_rate: 0, duration_seconds: 0 }));
  if (pathname.startsWith('/api/stats/week/detail?date=')) return Promise.resolve(response({ days: [], training_days: 0, completed_days: 0 }));
  if (pathname === '/api/exercises') return Promise.resolve(response({ exercises: [{ id: 9, name: '今日动作' }] }));
  if (pathname === '/api/templates') return Promise.resolve(response({ templates: [] }));
  if (pathname === '/api/favorites') return Promise.resolve(response({ favorites: [] }));
  if (pathname === '/api/ai/provider') return Promise.resolve(response({ provider: 'local-demo', model: '' }));
  if (pathname === '/api/ai/models') return Promise.resolve(response({ models: [] }));
  throw new Error(`unexpected API path: ${pathname}`);
}

(async () => {
  const trainingState = {
    version: 1,
    updatedAt: '',
    data: {
      activeDateKey: selectedDate,
      calendarPlans: {},
      customTrainingPlans: {},
      dailySessions: {
        [selectedDate]: {
          items: [{ id: 6, name: '旧日期动作', exerciseId: 9, sets: 3, reps: 8, duration_seconds: 30, time: 1 }],
          source: '旧日期计划', stepIndex: 0, setIndex: 0, actionElapsedSeconds: 0, actionStartedAt: null,
          skipped: [], records: [], pending: null, started: false, done: false, rest: false, updatedAt: '',
        },
      },
    },
  };
  const page = createPage({ date: [2026, 9, 3], seedOldState: false, trainingState, fetchOverride: fixture });
  await waitFor(() => page.dom.window.__qdTrainingState.today().key === selectedDate, 'selected date');
  await tick();
  const state = page.dom.window.__qdTrainingState.today();
  const heroState = page.dom.window.document.getElementById('dayHero').getAttribute('data-today-state');
  const title = page.dom.window.document.getElementById('todayTitle').textContent;
  if (state.items !== 0 || heroState !== 'error' || title.includes('今日真实计划')) {
    throw new Error(JSON.stringify({ state, heroState, title }));
  }
  page.dom.window.close();
  console.log(JSON.stringify({ PASS: true, selectedDate, heroState, title }));
})().catch((error) => { console.error(error.stack || error); process.exit(1); });
