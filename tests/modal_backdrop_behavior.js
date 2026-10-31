'use strict';

const fs = require('fs');
const path = require('path');
const cp = require('child_process');
const { JSDOM, VirtualConsole } = require('./dom_dependencies');

const APP_DIR = path.join(__dirname, '..');
const CURRENT_SOURCE = fs.readFileSync(path.join(APP_DIR, 'static', 'index.html'), 'utf8');
const BASELINE = '9227107c50dbd7ec4c81ca0d8acd3a53170bb7a8';
let assertions = 0;
function ok(condition, message) { assertions += 1; if (!condition) throw new Error(message); }
function response(body) { return { ok: true, status: 200, json: async () => body, text: async () => JSON.stringify(body) }; }
function boot(url) {
  if (url === '/api/ai/provider') return { provider: 'local-demo', base_url: '', model: '', key_configured: false };
  if (url === '/api/ai/models') return { provider: 'local-demo', source: 'local-demo', models: [], active_model: null };
  if (url === '/api/plans/today') return { date: '2026-10-04', is_training: false, isTrainingDay: false, items: [] };
  if (url.startsWith('/api/calendar?')) return { days: [] };
  if (url.startsWith('/api/stats/month/detail?') || url.startsWith('/api/stats/week/detail?')) return { days: [], training_days: 0, completed: 0 };
  if (url.startsWith('/api/stats/month?')) return { month: '2026-10', training_days: 0, completed: 0, completion_rate: 0, duration_seconds: 0 };
  if (url.startsWith('/api/plans/month?')) return { days: [] };
  if (url === '/api/exercises' || url === '/api/templates' || url === '/api/favorites') return { exercises: [], templates: [], favorites: [] };
  if (url.startsWith('/api/session/current?')) return { session: null };
  return {};
}
function page(source) {
  const errors = [];
  const vc = new VirtualConsole();
  vc.on('jsdomError', e => errors.push(e.stack || e.message || String(e)));
  const dom = new JSDOM(source, {
    url: 'http://127.0.0.1:3000/', runScripts: 'dangerously', pretendToBeVisual: true, virtualConsole: vc,
    beforeParse(window) {
      window.addEventListener('error', event => errors.push(event.error && event.error.stack || event.message || String(event.error || event)));
      window.matchMedia = () => ({ matches: false, addListener() {}, removeListener() {}, addEventListener() {}, removeEventListener() {} });
      window.confirm = () => true; window.prompt = () => null; window.alert = () => {};
      window.requestAnimationFrame = cb => setTimeout(cb, 0); window.cancelAnimationFrame = id => clearTimeout(id);
      window.fetch = (url) => Promise.resolve(response(boot(String(url))));
    },
  });
  return { dom, errors };
}
function prop(event, name, value) { Object.defineProperty(event, name, { configurable: true, value }); return event; }
function dispatch(target, type, values = {}) {
  const event = new target.ownerDocument.defaultView.Event(type, { bubbles: true, cancelable: true });
  Object.entries(values).forEach(([name, value]) => prop(event, name, value));
  target.dispatchEvent(event); return event;
}
function open(pageState) {
  const { dom, errors } = pageState; const doc = dom.window.document; const layer = doc.getElementById('appModalLayer');
  doc.querySelector('[data-open-settings-modal="api"]').click();
  ok(layer.classList.contains('show'), 'modal did not open'); ok(!errors.length, errors.join('\n'));
  return { doc, layer, card: doc.getElementById('appModalCard'), input: doc.getElementById('settingsApiBaseInput') };
}
function closed(layer) { return !layer.classList.contains('show') && layer.getAttribute('aria-hidden') === 'true'; }
function reopen(ctx) {
  ctx.doc.querySelector('[data-open-settings-modal="api"]').click();
  ok(ctx.layer.classList.contains('show'), 'modal did not reopen');
  ctx.input = ctx.doc.getElementById('settingsApiBaseInput');
}
function closeByBackdrop(ctx, id = 1) {
  dispatch(ctx.layer, 'pointerdown', { pointerId: id, button: 0, isPrimary: true });
  dispatch(ctx.layer, 'pointerup', { pointerId: id, button: 0, isPrimary: true });
  dispatch(ctx.layer, 'click', { pointerId: id, button: 0, isPrimary: true });
}
function inputDragOut(ctx, id) {
  ok(ctx.input && ctx.input.isConnected, 'settings input is not connected to the current modal');
  dispatch(ctx.input, 'pointerdown', { pointerId: id, button: 0, isPrimary: true });
  dispatch(ctx.layer, 'pointerup', { pointerId: id, button: 0, isPrimary: true });
  dispatch(ctx.layer, 'click', { pointerId: id, button: 0, isPrimary: true });
  ok(!closed(ctx.layer), 'input pointerdown followed by backdrop release/click closed modal');
}
function runCurrent() {
  const p = page(CURRENT_SOURCE); const ctx = open(p);
  for (let round = 1; round <= 3; round += 1) {
    inputDragOut(ctx, 100 + round);
    closeByBackdrop(ctx, 110 + round); ok(closed(ctx.layer), `valid backdrop click failed in round ${round}`);
    if (round < 3) reopen(ctx);
  }
  reopen(ctx);
  dispatch(ctx.card, 'pointerdown', { pointerId: 11, button: 0, isPrimary: true }); dispatch(ctx.card, 'pointerup', { pointerId: 11, button: 0, isPrimary: true }); dispatch(ctx.card, 'click', { pointerId: 11, button: 0, isPrimary: true }); ok(!closed(ctx.layer), 'internal click closed modal');
  dispatch(ctx.layer, 'pointerdown', { pointerId: 12, button: 0, isPrimary: true }); dispatch(ctx.card, 'pointerup', { pointerId: 12, button: 0, isPrimary: true }); dispatch(ctx.layer, 'click', { pointerId: 12, button: 0, isPrimary: true }); ok(!closed(ctx.layer), 'inside release after outside press closed modal');
  dispatch(ctx.layer, 'pointerdown', { pointerId: 14, button: 0, isPrimary: true }); dispatch(ctx.layer, 'pointercancel', { pointerId: 14, button: 0, isPrimary: true }); dispatch(ctx.layer, 'click', { pointerId: 14, button: 0, isPrimary: true }); ok(!closed(ctx.layer), 'cancel did not clear backdrop state');
  dispatch(ctx.layer, 'pointerdown', { pointerId: 15, button: 0, isPrimary: true }); dispatch(ctx.layer, 'pointerup', { pointerId: 16, button: 0, isPrimary: true }); dispatch(ctx.layer, 'click', { pointerId: 15, button: 0, isPrimary: true }); ok(!closed(ctx.layer), 'mismatched pointerup closed modal');
  closeByBackdrop(ctx, 17); ok(closed(ctx.layer), 'subsequent valid click failed after mismatch');
  reopen(ctx); dispatch(ctx.layer, 'pointerdown', { pointerId: 18, button: 0, isPrimary: true }); dispatch(ctx.layer, 'pointerup', { pointerId: 18, button: 0, isPrimary: true }); dispatch(ctx.layer, 'click', { pointerId: 19, button: 0, isPrimary: true }); ok(!closed(ctx.layer), 'mismatched click pointer id closed modal');
  dispatch(ctx.layer, 'click', { pointerId: 18, button: 0, isPrimary: true }); ok(!closed(ctx.layer), 'stale click state survived mismatched click');
  dispatch(ctx.layer, 'pointerdown', { pointerId: 20, button: 0, isPrimary: false }); dispatch(ctx.layer, 'pointerup', { pointerId: 20, button: 0, isPrimary: false }); dispatch(ctx.layer, 'click', { pointerId: 20, button: 0, isPrimary: false }); ok(!closed(ctx.layer), 'non-primary pointer closed modal');
  dispatch(ctx.layer, 'pointerdown', { pointerId: 21, button: 2, isPrimary: true }); dispatch(ctx.layer, 'pointerup', { pointerId: 21, button: 2, isPrimary: true }); dispatch(ctx.layer, 'click', { pointerId: 21, button: 2, isPrimary: true }); ok(!closed(ctx.layer), 'non-left pointer closed modal');
  dispatch(ctx.layer, 'pointerdown', { pointerId: 22, button: 0, isPrimary: true }); ctx.doc.querySelector('.modal-close').click(); ok(closed(ctx.layer), 'close button failed');
  reopen(ctx); dispatch(ctx.layer, 'click', { pointerId: 22, button: 0, isPrimary: true }); ok(!closed(ctx.layer), 'reopen reused stale pointer state');
  ctx.doc.dispatchEvent(new ctx.doc.defaultView.KeyboardEvent('keydown', { key: 'Escape', bubbles: true })); ok(closed(ctx.layer), 'Escape failed to close');
  p.dom.window.close();
}
function runBaselineNegativeControl() {
  const baselineSource = cp.execFileSync('git', ['show', `${BASELINE}:static/index.html`], { cwd: APP_DIR, encoding: 'utf8' });
  const p = page(baselineSource); const ctx = open(p);
  let expectedFailure = null;
  try {
    inputDragOut(ctx, 90);
  } catch (error) {
    if (error && error.message === 'input pointerdown followed by backdrop release/click closed modal') {
      expectedFailure = error;
    } else {
      throw error;
    }
  }
  ok(expectedFailure, 'negative control did not fail on baseline: old HTML incorrectly passed input drag-out invariant');
  ok(closed(ctx.layer), 'negative control expected baseline to close on input drag-out');
  p.dom.window.close();
}

try { runCurrent(); runBaselineNegativeControl(); console.log(`PASS modal backdrop behavior (${assertions} assertions)`); process.exit(0); }
catch (error) { console.error(error.stack || error); process.exit(1); }
