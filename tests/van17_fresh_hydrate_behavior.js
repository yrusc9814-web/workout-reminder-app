'use strict';

// Full-page JSDOM regression.  This intentionally loads the complete tracked
// page through createPage; only the API boundary is mocked.
const { createPage, response, waitFor, tick } = require('./f01_real_dom_behavior');

const activeDate = '2030-11-02';
const activePlan = {
  id: 99,
  date: activeDate,
  title: '未来三组计划',
  isTrainingDay: true,
  is_training: true,
  items: [{ id: 21, exercise_id: 21, name: '未来三组动作', sets: 3, reps: 8, duration_seconds: 30, spec: '3 组 · 8 次' }],
};
const activeSession = {
  id: 8,
  plan_id: 99,
  status: 'completed',
  records: [{ exercise_id: 21, status: 'completed', sets_completed: 3, duration_seconds: 90 }],
};

function trainingState() {
  return {
    version: 1,
    updatedAt: '',
    data: {
      activeDateKey: activeDate,
      calendarPlans: {},
      customTrainingPlans: {},
      dailySessions: {
        [activeDate]: {
          items: activePlan.items,
          source: activePlan.title,
          stepIndex: 0,
          setIndex: 0,
          actionElapsedSeconds: 0,
          actionStartedAt: null,
          skipped: [],
          records: [],
          pending: null,
          started: true,
          done: false,
          rest: false,
          updatedAt: '',
        },
      },
    },
  };
}

function apiFixture({ dateSessionFails = false, dateSession = null, globalSession = null, todaySets = 1 } = {}) {
  return (pathname) => {
    if (pathname === '/api/plans/today') {
      return Promise.resolve(response({ id: 1, date: '2026-10-03', title: '今日计划', isTrainingDay: true, is_training: true, items: [{ id: 1, exercise_id: 11, name: '今日动作', sets: todaySets, reps: 8 }] }));
    }
    if (pathname.startsWith('/api/session/current?date=')) {
      return dateSessionFails
        ? Promise.resolve(response({ detail: 'date session unavailable' }, 503))
        : Promise.resolve(response(dateSession || { session: activeSession, plan: activePlan }));
    }
    if (pathname === '/api/session/current?include_completed=true') return Promise.resolve(response(globalSession || { session: null }));
    if (pathname.startsWith('/api/plans/month?month=2030-11')) return Promise.resolve(response({ days: [activePlan] }));
    if (pathname.startsWith('/api/stats/month/detail?month=2030-11')) return Promise.resolve(response({ days: [{ date: activeDate, status: 'completed', is_training: true }], completed: 1, completed_days: 1 }));
    if (pathname.startsWith('/api/stats/month?month=2030-11')) return Promise.resolve(response({ month: '2030-11', training_days: 1, completed: 1, completed_days: 1, completion_rate: 100, duration_seconds: 90 }));
    if (pathname.startsWith('/api/calendar?month=') || pathname.startsWith('/api/plans/month?month=')) return Promise.resolve(response({ days: [] }));
    if (pathname.startsWith('/api/stats/month/detail?month=') || pathname.startsWith('/api/stats/month?month=')) return Promise.resolve(response({ days: [], training_days: 0, completed: 0, completed_days: 0, completion_rate: 0, duration_seconds: 0 }));
    if (pathname.startsWith('/api/stats/week/detail?date=')) return Promise.resolve(response({ days: [], training_days: 0, completed: 0, completed_days: 0 }));
    if (pathname === '/api/exercises') return Promise.resolve(response({ exercises: [] }));
    if (pathname === '/api/templates') return Promise.resolve(response({ templates: [] }));
    if (pathname === '/api/favorites') return Promise.resolve(response({ favorites: [] }));
    if (pathname === '/api/ai/provider') return Promise.resolve(response({ provider: 'local-demo', model: '' }));
    if (pathname === '/api/ai/models') return Promise.resolve(response({ models: [] }));
    throw new Error(`unexpected API path: ${pathname}`);
  };
}

async function settle(page) {
  await waitFor(() => page.dom.window.__qdTrainingState.today().key === activeDate, 'active date selection');
  await waitFor(() => page.dom.window.__qdTrainingState.today().done === true, 'completed records hydration');
}

(async () => {
  const first = createPage({ date: [2026, 9, 3], seedOldState: false, trainingState: trainingState(), fetchOverride: apiFixture() });
  await settle(first);
  first.dom.window.document.getElementById('todayDetailBtn').click();
  const firstState = first.dom.window.__qdApp.getTodayExecutionState();
  if (first.dom.window.__qdApp.getTodayPlan()[0].name !== '未来三组动作' || firstState.records[0].setsCompleted !== 3 || firstState.records[0].durationSeconds !== 90) {
    throw new Error(JSON.stringify({ plan: first.dom.window.__qdApp.getTodayPlan(), state: firstState, calls: first.control.calls }));
  }
  const persisted = JSON.parse(first.dom.window.localStorage.getItem('qd-training-state-v1'));
  first.dom.window.close();

  const second = createPage({ date: [2026, 9, 3], seedOldState: false, trainingState: persisted, fetchOverride: apiFixture() });
  await settle(second);
  const secondState = second.dom.window.__qdApp.getTodayExecutionState();
  if (second.dom.window.__qdApp.getTodayPlan()[0].name !== '未来三组动作' || secondState.records[0].setsCompleted !== 3 || secondState.records[0].durationSeconds !== 90) {
    throw new Error(JSON.stringify({ plan: second.dom.window.__qdApp.getTodayPlan(), state: secondState }));
  }
  second.dom.window.close();

  const coldToday = createPage({
    date: [2026, 9, 3],
    seedOldState: false,
    trainingState: null,
    fetchOverride: apiFixture({
      todaySets: 3,
      dateSession: {
        session: { id: 5, plan_id: 1, status: 'completed', records: [{ exercise_id: 11, status: 'completed', sets_completed: 3, duration_seconds: 90 }] },
        plan: { id: 1, date: '2026-10-03', title: '今日计划', isTrainingDay: true, items: [{ id: 1, exercise_id: 11, name: '今日动作', sets: 3, reps: 8 }] }
      },
      globalSession: {
        session: { id: 9, plan_id: 99, status: 'completed', records: [{ exercise_id: 21, status: 'completed', sets_completed: 3, duration_seconds: 90 }] },
        plan: activePlan
      }
    })
  });
  await waitFor(() => coldToday.dom.window.__qdTrainingState.today().done === true, 'cold today completed facts');
  const coldTodayState = coldToday.dom.window.__qdApp.getTodayExecutionState();
  if (coldToday.dom.window.__qdApp.getTodayPlan()[0].name !== '今日动作' || coldTodayState.records[0].setsCompleted !== 3 || coldTodayState.records[0].durationSeconds !== 90) {
    throw new Error(JSON.stringify({ plan: coldToday.dom.window.__qdApp.getTodayPlan(), state: coldTodayState }));
  }
  coldToday.dom.window.close();

  const coldHistory = createPage({
    date: [2026, 9, 3],
    seedOldState: false,
    trainingState: null,
    fetchOverride: apiFixture({
      todaySets: 3,
      dateSession: {
        session: { id: 5, plan_id: 1, status: 'completed', records: [{ exercise_id: 11, status: 'completed', sets_completed: 3, duration_seconds: 90 }] },
        plan: { id: 1, date: '2026-10-03', title: '今日计划', isTrainingDay: true, items: [{ id: 1, exercise_id: 11, name: '今日动作', sets: 3, reps: 8 }] }
      },
      globalSession: {
        session: { id: 7, plan_id: 77, status: 'in_progress', records: [{ exercise_id: 31, status: 'pending', sets_completed: 1, duration_seconds: 25 }] },
        plan: { id: 77, date: '2030-09-30', title: '历史三组计划', isTrainingDay: true, items: [{ id: 31, exercise_id: 31, name: '历史三组动作', sets: 3, reps: 8 }] }
      }
    })
  });
  await waitFor(() => coldHistory.dom.window.__qdTrainingState.today().key === '2030-09-30', 'cold historical active date');
  const coldHistoryState = coldHistory.dom.window.__qdApp.getTodayExecutionState();
  if (coldHistory.dom.window.__qdApp.getTodayPlan()[0].name !== '历史三组动作' || coldHistoryState.done || coldHistoryState.records[0].setsCompleted !== 1) {
    throw new Error(JSON.stringify({ plan: coldHistory.dom.window.__qdApp.getTodayPlan(), state: coldHistoryState }));
  }
  coldHistory.dom.window.close();

  const failed = createPage({ date: [2026, 9, 3], seedOldState: false, trainingState: persisted, fetchOverride: apiFixture({ dateSessionFails: true }) });
  await tick();
  const failedState = failed.dom.window.__qdApp.getTodayExecutionState();
  if (failedState.done || failedState.records.length) {
    throw new Error(JSON.stringify({ plan: failed.dom.window.__qdApp.getTodayPlan(), state: failedState }));
  }
  failed.dom.window.close();
  console.log(JSON.stringify({ PASS: true, date: activeDate, sets: 3, duration: 90, freshHydrate: true, dateBoundFailureNoFakeDone: true }));
})().catch((error) => { console.error(error.stack || error); process.exit(1); });
