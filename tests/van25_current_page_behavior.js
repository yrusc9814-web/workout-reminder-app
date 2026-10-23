'use strict';
const assert = require('node:assert/strict');
const { createPage, response, payloadFor, waitFor, tick } = require('./f01_real_dom_behavior');
const scenario = process.argv[2];
const date = '2026-10-02';
const calls = [];
let updateFails = false, completeFails = false, holdUpdate = false, releaseUpdate;
let remote = null;
const items = [
  { id: 11, exercise_id: 9, name: '第一动作', sets: 1, reps: 8, sort_order: 1 },
  { id: 12, exercise_id: 10, name: '第二动作', sets: 1, reps: 8, sort_order: 2 },
];
const plan = { id: 41, date, title: '后端计划', is_training: true, isTrainingDay: true, template_id: 8, items };
const nullTemplatePlan = { ...plan, id: 42, date: '2026-10-03', template_id: null };
const missingTemplatePlan = { ...plan, id: 43, date: '2026-10-04' };
delete missingTemplatePlan.template_id;
const templatePlans = [plan, nullTemplatePlan, missingTemplatePlan];
function fixture(url, options = {}) {
  const body = options.body ? JSON.parse(options.body) : null;
  calls.push({ url, body, method: options.method || 'GET' });
  if (url === '/api/session/start') {
    remote = { id: 7, plan_id: 41, status: 'in_progress', records: items.map((item, i) => ({ id: 501 + i, record_id: 501 + i, exercise_id: item.exercise_id, plan_item_order: i + 1, status: 'pending', sets_completed: 0 })) };
    return Promise.resolve(response({ status: 'started', session: remote }));
  }
  if (url === '/api/session/update') {
    const reply = () => {
      if (updateFails) return response({ detail: 'update unavailable' }, 503);
      const record = remote.records.find(r => r.id === body.record_id);
      assert.ok(record, 'payload must identify a real record');
      Object.assign(record, body);
      return response({ status: 'updated', record });
    };
    if (holdUpdate) return new Promise(resolve => { releaseUpdate = () => resolve(reply()); });
    return Promise.resolve(reply());
  }
  if (url === '/api/session/complete') {
    if (completeFails) return Promise.resolve(response({ detail: 'complete unavailable' }, 503));
    remote.status = 'completed';
    return Promise.resolve(response({ status: 'completed', session: remote }));
  }
  if (url.startsWith('/api/session/current')) return Promise.resolve(response({ session: remote }));
  if (url === '/api/plans/today') return Promise.resolve(response(scenario === 'empty' ? { date, items: [], is_training: false, isTrainingDay: false } : plan));
  if (url.startsWith('/api/plans/month?')) return Promise.resolve(response({ days: scenario === 'empty' ? [] : (scenario === 'template-binding' ? templatePlans : [plan]) }));
  if (url === '/api/templates' && scenario === 'template-binding') {
    // Matching exercise lists are deliberate bait: only the backend template_id may bind a plan.
    return Promise.resolve(response({ templates: [
      { id: 9, name: '同动作的其他模板', exercises: items.map(i => ({ id: i.exercise_id, name: i.name })) },
      { id: 8, name: '后端指定模板', exercises: items.map(i => ({ id: i.exercise_id, name: i.name })) },
    ] }));
  }
  if (url === '/api/exercises') return Promise.resolve(response({ exercises: scenario === 'empty' ? [] : items.map(i => ({ id: i.exercise_id, name: i.name, default_sets: 1, default_reps: '8' })) }));
  return Promise.resolve(response(payloadFor(url, scenario === 'empty' ? 'empty' : 'data')));
}
(async () => {
  const page = createPage({ seedOldState: false, fetchOverride: (url) => fixture(url) });
  try {
    const app = page.dom.window.__qdApp;
    await app.bootCanonical();
    await tick();
    page.dom.window.fetch = fixture;
    const doc = page.dom.window.document;
    const start = () => doc.getElementById('startTodayBtn').click();
    const skip = () => doc.getElementById('skipTodayBtn').click();
    const state = () => app.getTodayExecutionState();
    const updates = () => calls.filter(c => c.url === '/api/session/update');
    if (scenario === 'empty') {
      assert.equal(app.getTodayPlan().length, 0);
      assert.equal(doc.getElementById('dayHero').dataset.todayState, 'empty');
      assert.equal(calls.filter(c => c.method !== 'GET').length, 0);
    } else if (scenario === 'template-binding') {
      await waitFor(() => app.getCalendarPlan('2026-10-04') && app.getTrainingPlans().remote_8, 'month plans and competing templates');
      assert.ok(app.getTrainingPlans().remote_9, 'competing template must be hydrated');
      assert.equal(app.getCalendarPlan(date).id, 41);
      assert.equal(app.getCalendarPlan(date).templateId, '8', 'preserve explicit backend binding, not first matching template');
      assert.equal(app.getCalendarPlan('2026-10-03').id, 42);
      assert.equal(app.getCalendarPlan('2026-10-03').templateId, null, 'explicit null must remain unbound');
      assert.equal(app.getCalendarPlan('2026-10-04').id, 43);
      assert.equal(app.getCalendarPlan('2026-10-04').templateId, null, 'missing template_id must remain unbound');
      assert.equal(calls.filter(c => c.method !== 'GET').length, 0, 'hydration must not write an inferred binding');
    } else {
      await waitFor(() => app.getTodayPlan().length === 2, 'backend plan hydration');
      start();
      await waitFor(() => state().started, 'start');
      calls.length = 0;
      if (scenario === 'skip-failure') {
        updateFails = true;
        skip();
        await waitFor(() => state().pending && updates().length === 1, 'failed skip payload');
        await tick();
        assert.equal(state().stepIndex, 0);
        assert.equal(state().done, false);
        assert.equal(state().skipped.length, 0);
        assert.equal(calls.some(c => c.url === '/api/session/complete'), false);
        const frozen = JSON.stringify(updates()[0].body);
        updateFails = false;
        skip();
        await waitFor(() => state().stepIndex === 1, 'skip retry');
        assert.equal(JSON.stringify(updates()[1].body), frozen);
        assert.equal(state().records[0].status, 'skipped');
      } else if (scenario === 'double-click') {
        holdUpdate = true;
        start(); start();
        await waitFor(() => !!releaseUpdate, 'held update');
        assert.equal(updates().length, 1);
        assert.equal(state().stepIndex, 0);
        releaseUpdate();
        await waitFor(() => state().stepIndex === 1, 'confirmed advance');
        assert.equal(state().records[0].setsCompleted, 1);
      } else {
        skip();
        await waitFor(() => state().stepIndex === 1, 'first skip');
        calls.length = 0;
        completeFails = scenario === 'complete-retry';
        skip();
        await waitFor(() => calls.some(c => c.url === '/api/session/complete'), 'terminal complete');
        await tick(); await tick();
        assert.equal(updates().length, 1);
        assert.equal(updates()[0].body.status, 'skipped');
        assert.equal(updates()[0].body.record_id, 502);
        assert.ok(calls.findIndex(c => c.url === '/api/session/update') < calls.findIndex(c => c.url === '/api/session/complete'));
        if (scenario === 'complete-retry') {
          assert.equal(state().done, false);
          assert.equal(state().started, true);
          assert.ok(state().pending);
          calls.length = 0;
          completeFails = false;
          skip();
          await waitFor(() => state().done, 'complete retry');
          assert.equal(updates().length, 0, 'retry must not duplicate confirmed update');
          assert.equal(calls.filter(c => c.url === '/api/session/complete').length, 1);
        } else {
          await waitFor(() => state().done, 'done');
          assert.equal(state().records[1].status, 'skipped');
        }
      }
    }
    console.log(JSON.stringify({ PASS: true, scenario, source: 'static/index.html', input: 'production button clicks' }));
  } finally { page.dom.window.close(); }
})().catch(error => { console.error(error.stack || error); process.exitCode = 1; });
