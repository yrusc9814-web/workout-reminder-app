'use strict';

const { createPage, response, waitFor, tick } = require('./f01_real_dom_behavior');

const TODAY = '2026-10-08';
const savedState = {
  version: 1,
  updatedAt: '',
  data: {
    calendarPlans: {},
    customTrainingPlans: {
      saved_scheme: {
        id: 'saved_scheme',
        title: '用户已保存的数字方案',
        time: 5,
        intensity: '低强度',
        scene: '自定义',
        reason: '已有数据',
        items: ['saved E1 · 做-8次'],
      },
    },
    dailySessions: {},
  },
};

function payload(pathname) {
  if (pathname === '/api/plans/today') return { date: TODAY, is_training: false, isTrainingDay: false, items: [] };
  if (pathname.startsWith('/api/plans/month?')) return { days: [] };
  if (pathname.startsWith('/api/calendar?')) return { days: [] };
  if (pathname.startsWith('/api/stats/month')) return { days: [], training_days: 0, completed_days: 0, completion_rate: 0, duration_seconds: 0 };
  if (pathname.startsWith('/api/stats/week')) return { days: [], training_days: 0, completed_days: 0 };
  if (pathname === '/api/exercises') return { exercises: [{ id: 1, name: 'saved E1', default_sets: 1, default_reps: '8' }] };
  if (pathname === '/api/templates') return { templates: [] };
  if (pathname === '/api/favorites') return { favorites: [] };
  if (pathname === '/api/ai/provider') return { provider: 'local-demo', model: '' };
  if (pathname === '/api/ai/models') return { models: [] };
  if (pathname.startsWith('/api/session/current?')) return { session: null };
  return {};
}

(async () => {
  const page = createPage({
    date: [2026, 9, 8],
    seedOldState: false,
    trainingState: savedState,
    fetchOverride: (pathname) => Promise.resolve(response(payload(String(pathname)))),
  });
  const calls = [];
  page.dom.window.fetch = function (pathname, options = {}) {
    let body = null;
    try { body = options.body ? JSON.parse(options.body) : null; } catch (_) { body = options.body; }
    calls.push({ pathname: String(pathname), body });
    return Promise.resolve(response(payload(String(pathname))));
  };
  await page.dom.window.__qdApp.bootCanonical();
  await waitFor(() => page.dom.window.document.querySelector('[data-start-plan="saved_scheme"]'), 'saved scheme button');
  const button = page.dom.window.document.querySelector('[data-start-plan="saved_scheme"]');
  button.click();
  await tick();
  await tick();
  const writes = calls.filter((call) => call.pathname === '/api/plans/by-date/' + TODAY);
  if (writes.length) throw new Error(`invalid saved scheme was written: ${JSON.stringify(writes)}`);
  page.dom.window.close();
  console.log(JSON.stringify({ PASS: true, writes: writes.length, invalid_spec: '做-8次' }));
})().catch((error) => { console.error(error.stack || error); process.exit(1); });
