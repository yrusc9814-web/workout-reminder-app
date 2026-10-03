'use strict';

const { createPage, response, waitFor, tick } = require('./f01_real_dom_behavior');

const training = { id: 8, date: '2026-10-04', title: '训练', isTrainingDay: true, is_training: true, items: [{ id: 1, exercise_id: 1, name: '动作', sets: 1, reps: 8 }] };
const rest = { id: 8, date: '2026-10-04', title: '恢复日', isTrainingDay: false, is_training: false, items: [] };

function makePage(mode) {
  let readbackFail = false;
  let phase = 'training';
  const fixture = (pathname) => {
    if (pathname === '/api/plans/today') return response(phase === 'rest' ? rest : training);
    if (pathname.startsWith('/api/session/current?date=')) return response({ session: null });
    if (pathname === '/api/session/current?include_completed=true') return response({ session: null });
    if (pathname.startsWith('/api/plans/month?month=') && readbackFail) return response({ detail: 'range readback unavailable' }, 503);
    if (pathname.startsWith('/api/plans/month?month=')) return response({ days: [phase === 'rest' ? rest : training] });
    if (pathname.startsWith('/api/calendar?month=')) return response({ days: [] });
    if (pathname.startsWith('/api/stats/month/detail?month=')) return response({ days: [{ date: training.date, status: phase === 'rest' ? 'rest' : 'planned', is_training: phase !== 'rest' }], training_days: phase === 'rest' ? 0 : 1, completed_days: 0 });
    if (pathname.startsWith('/api/stats/month?month=')) return response({ month: '2026-10', training_days: phase === 'rest' ? 0 : 1, completed_days: 0, completed: 0, completion_rate: 0, duration_seconds: 0 });
    if (pathname.startsWith('/api/stats/week/detail?date=')) return response({ days: [], training_days: 0, completed_days: 0 });
    if (pathname === '/api/exercises') return response({ exercises: [{ id: 1, name: '动作' }] });
    if (pathname === '/api/templates') return response({ templates: [] });
    if (pathname === '/api/favorites') return response({ favorites: [] });
    if (pathname === '/api/ai/provider') return response({ provider: 'local-demo', model: '' });
    if (pathname === '/api/ai/models') return response({ models: [] });
    throw new Error(`unexpected API path: ${pathname}`);
  };
  const page = createPage({ date: [2026, 9, 4], seedOldState: false, fetchOverride: (pathname) => Promise.resolve(fixture(pathname)) });
  return { page, setReadbackFail: (value) => { readbackFail = value; }, shouldFail: () => readbackFail, setRest: () => { phase = 'rest'; }, mode };
}

async function runMutation(mode) {
  const env = makePage(mode);
  const page = env.page;
  await waitFor(() => page.dom.window.__qdApp.getTodayPlan().length === 1, `${mode} initial plan`);
  page.dom.window.fetch = (pathname, options = {}) => {
    if (mode === 'postpone' && pathname === '/api/plans/postpone') {
      env.setRest();
      return Promise.resolve(response({ status: 'saved', source: rest, target: training }));
    }
    if (mode === 'import' && pathname === '/api/plans/import') {
      env.setRest();
      return Promise.resolve(response({ status: 'saved', plans: [rest] }));
    }
    return Promise.resolve((() => {
      // The page's original fixture closure is not exposed; use the stable
      // route payloads needed by the retry boot below.
      if (pathname === '/api/plans/today') return response(env.mode === 'postpone' || env.mode === 'import' ? rest : training);
      if (pathname.startsWith('/api/plans/month?month=')) return env.shouldFail() ? response({ detail: 'range readback unavailable' }, 503) : response({ days: [rest] });
      if (pathname.startsWith('/api/calendar?month=')) return response({ days: [] });
      if (pathname.startsWith('/api/stats/month/detail?month=')) return response({ days: [{ date: training.date, status: 'rest', is_training: false }], training_days: 0, completed_days: 0 });
      if (pathname.startsWith('/api/stats/month?month=')) return response({ month: '2026-10', training_days: 0, completed_days: 0, completed: 0, completion_rate: 0, duration_seconds: 0 });
      if (pathname.startsWith('/api/stats/week/detail?date=')) return response({ days: [], training_days: 0, completed_days: 0 });
      if (pathname.startsWith('/api/session/current?')) return response({ session: null });
      if (pathname === '/api/exercises') return response({ exercises: [{ id: 1, name: '动作' }] });
      if (pathname === '/api/templates') return response({ templates: [] });
      if (pathname === '/api/favorites') return response({ favorites: [] });
      if (pathname === '/api/ai/provider') return response({ provider: 'local-demo', model: '' });
      if (pathname === '/api/ai/models') return response({ models: [] });
      throw new Error(`unexpected ${pathname}`);
    })());
  };
  env.setReadbackFail(true);
  const payload = mode === 'postpone'
    ? page.dom.window.__qdApp.postponeCanonical('2026-10-04', '2026-10-05')
    : page.dom.window.__qdApp.importCanonical([{ date: '2026-10-05', title: '其他日期计划', is_training_day: true, focus: '训练', notes: '', items: [{ exercise_id: 1, name: '动作', sets: 1 }] }]);
  await payload.catch(() => {});
  await waitFor(() => page.dom.window.document.getElementById('dayHero').getAttribute('data-today-state') === 'error', `${mode} readback error`);
  if (!page.dom.window.document.querySelector('[data-v25-retry-today]')) throw new Error(`${mode} retry missing`);
  env.setReadbackFail(false);
  page.dom.window.document.querySelector('[data-v25-retry-today]').click();
  await waitFor(() => page.dom.window.document.getElementById('dayHero').getAttribute('data-today-state') === 'empty', `${mode} retry empty`);
  page.dom.window.close();
  return { mode, state: 'empty' };
}

async function runOldDateReadbackDoesNotPolluteNewSelection() {
  const env = makePage('old-date');
  const page = env.page;
  await waitFor(() => page.dom.window.__qdApp.getTodayPlan().length === 1, 'old-date initial plan');
  page.dom.window.fetch = (pathname) => {
    if (pathname === '/api/plans/postpone') return Promise.resolve(response({ status: 'saved' }));
    if (pathname.startsWith('/api/plans/month?month=')) return Promise.resolve(response({ detail: 'old range unavailable' }, 503));
    return Promise.resolve(response(pathname === '/api/plans/today' ? training : { days: [] }));
  };
  env.setReadbackFail(true);
  await page.dom.window.__qdApp.postponeCanonical('2026-10-03', '2026-10-05').catch(() => {});
  await tick();
  const state = page.dom.window.__qdTrainingState.today();
  const heroState = page.dom.window.document.getElementById('dayHero').getAttribute('data-today-state');
  if (state.key !== '2026-10-04' || heroState === 'error') throw new Error(JSON.stringify({ state, heroState }));
  page.dom.window.close();
  return { mode: 'old-date-no-pollution', state: state.key, heroState };
}

(async () => {
  const results = [await runMutation('postpone'), await runMutation('import'), await runOldDateReadbackDoesNotPolluteNewSelection()];
  console.log(JSON.stringify({ PASS: true, results }));
})().catch((error) => { console.error(error.stack || error); process.exit(1); });
