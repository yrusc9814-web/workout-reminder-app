'use strict';

const fs = require('fs');
const path = require('path');
const { JSDOM, VirtualConsole } = require(path.join(
  process.env.VAN16_DOM_DEPS || '/private/tmp/van13-jsdom-deps/node_modules',
  'jsdom'
));

const SOURCE = fs.readFileSync(path.join(__dirname, '..', 'static', 'index.html'), 'utf8');

function response(body, status = 200) {
  return {
    ok: status >= 200 && status < 300,
    status,
    text: async () => JSON.stringify(body),
    json: async () => body,
  };
}

function bootPayloads(url) {
  if (url === '/api/plans/today') return { date: '2026-10-04', is_training: false, isTrainingDay: false, items: [] };
  if (url.startsWith('/api/calendar?month=')) return { days: [] };
  if (url.startsWith('/api/stats/month/detail?month=')) return { days: [], completed: 0 };
  if (url.startsWith('/api/stats/month?month=')) return { month: '2026-10', training_days: 0, completed: 0, completion_rate: 0, duration_seconds: 0 };
  if (url.startsWith('/api/stats/week/detail?date=')) return { days: [], training_days: 0, completed: 0 };
  if (url === '/api/exercises') return { exercises: [] };
  if (url === '/api/templates') return { templates: [] };
  if (url === '/api/favorites') return { favorites: [] };
  if (url.startsWith('/api/plans/month?month=')) return { days: [] };
  if (url.startsWith('/api/session/current?')) return { session: null };
  return null;
}

function createPage({ provider = 'local-demo', baseUrl = '', model = '', keyConfigured = false, getModels = [], preview = { body: { models: [] } }, save = { body: { provider, base_url: baseUrl, model, key_configured: keyConfigured } }, previewDelay = 0, saveDelay = 0 } = {}) {
  const state = { calls: [], provider, baseUrl, model, keyConfigured, getModels, preview, save, previewDelay, saveDelay, previewResolve: null, saveResolve: null, errors: [] };
  const virtualConsole = new VirtualConsole();
  virtualConsole.on('jsdomError', (error) => state.errors.push(error.stack || error.message || String(error)));
  const dom = new JSDOM(SOURCE, {
    url: 'http://127.0.0.1:3000/',
    runScripts: 'dangerously',
    pretendToBeVisual: true,
    virtualConsole,
    beforeParse(window) {
      const RealDate = window.Date;
      const fixedMs = new RealDate(2026, 9, 4, 12, 0, 0).getTime();
      function FixedDate(...args) {
        if (!(this instanceof FixedDate)) return RealDate(...args);
        return args.length ? new RealDate(...args) : new RealDate(fixedMs);
      }
      FixedDate.now = () => fixedMs;
      FixedDate.parse = RealDate.parse;
      FixedDate.UTC = RealDate.UTC;
      FixedDate.prototype = RealDate.prototype;
      window.Date = FixedDate;
      window.matchMedia = () => ({ matches: false, addListener() {}, removeListener() {}, addEventListener() {}, removeEventListener() {} });
      window.confirm = () => true;
      window.prompt = () => null;
      window.alert = () => {};
      window.innerWidth = 1280;
      window.innerHeight = 800;
      window.scrollTo = () => {};
      window.scrollBy = () => {};
      window.requestAnimationFrame = (callback) => setTimeout(callback, 0);
      window.cancelAnimationFrame = (id) => clearTimeout(id);
      window.fetch = function fetchMock(url, options = {}) {
        const pathname = String(url);
        const method = (options.method || 'GET').toUpperCase();
        let body = null;
        try { body = options.body ? JSON.parse(options.body) : null; } catch (_) { body = options.body; }
        state.calls.push({ url: pathname, method, body, headers: options.headers || {} });
        if (pathname === '/api/ai/provider' && method === 'GET') {
          return Promise.resolve(response({ provider: state.provider, base_url: state.baseUrl, model: state.model, key_configured: state.keyConfigured }));
        }
        if (pathname === '/api/ai/models' && method === 'GET') {
          return Promise.resolve(response({ provider: state.provider, source: state.provider === 'local-demo' ? 'local-demo' : 'api', models: state.getModels, active_model: state.model || null }));
        }
        if (pathname === '/api/ai/models' && method === 'POST') {
          if (state.previewDelay) {
            return new Promise((resolve) => { state.previewResolve = () => resolve(response(state.preview.body, state.preview.status || 200)); });
          }
          return Promise.resolve(response(state.preview.body || {}, state.preview.status || 200));
        }
        if (pathname === '/api/ai/provider' && method === 'PUT') {
          if (state.saveDelay) return new Promise((resolve) => { state.saveResolve = () => resolve(response(state.save.body || {}, state.save.status || 200)); });
          return Promise.resolve(response(state.save.body || {}, state.save.status || 200));
        }
        const payload = bootPayloads(pathname);
        return Promise.resolve(response(payload || {}));
      };
    },
  });
  return { dom, state };
}

function tick() {
  return new Promise((resolve) => setImmediate(resolve));
}

async function waitFor(predicate, label) {
  for (let i = 0; i < 120; i += 1) {
    if (predicate()) return;
    await tick();
  }
  throw new Error(`timed out waiting for ${label}`);
}

async function openApiSettings(page) {
  await waitFor(() => !!page.dom.window.__qdApp, 'production app hook');
  await waitFor(() => page.state.calls.some((call) => call.url === '/api/ai/provider' && call.method === 'GET') && apiSettingsState(page).provider === page.state.provider, 'provider boot state');
  page.dom.window.document.querySelector('[data-open-settings-modal="api"]').click();
  await tick();
}

function apiSettingsState(page) {
  if (page.state.errors.length) throw new Error(page.state.errors.join('\n'));
  return page.dom.window.__qdApp.getAiSettings();
}

function fillApiForm(page, { provider = 'openai', baseUrl, key }) {
  const doc = page.dom.window.document;
  doc.getElementById('settingsApiProviderSelect').value = provider;
  doc.getElementById('settingsApiBaseInput').value = baseUrl;
  doc.getElementById('settingsApiKeyInput').value = key;
}

async function clickDiscover(page) {
  page.dom.window.document.querySelector('[data-settings-api-models]').click();
  await waitFor(() => page.state.calls.some((call) => call.url === '/api/ai/models' && call.method === 'POST') && !page.state.previewDelay || !!page.state.previewResolve, 'draft model request');
  if (page.state.previewDelay) page.state.previewResolve();
  await tick();
}

async function run() {
  const fresh = createPage({ preview: { body: { provider: 'openai', source: 'draft', models: ['fresh-a', 'fresh-b'], active_model: null, status: 'ok' } }, save: { body: { provider: 'openai', base_url: 'http://fake.test/v1', model: 'fresh-a', key_configured: true } } });
  await openApiSettings(fresh);
  fillApiForm(fresh, { baseUrl: 'http://fake.test/v1/', key: 'fresh-form-key' });
  const before = { provider: apiSettingsState(fresh).provider, model: apiSettingsState(fresh).model, baseUrl: apiSettingsState(fresh).baseUrl };
  await clickDiscover(fresh);
  const post = fresh.state.calls.find((call) => call.url === '/api/ai/models' && call.method === 'POST');
  if (!post || post.body.provider !== 'openai' || post.body.api_key !== 'fresh-form-key' || post.body.base_url !== 'http://fake.test/v1') throw new Error(`form draft was not submitted: ${JSON.stringify(post)}`);
  if (apiSettingsState(fresh).provider !== before.provider || apiSettingsState(fresh).model !== before.model || apiSettingsState(fresh).baseUrl !== before.baseUrl) throw new Error('draft discovery changed formal apiSettings');
  const options = [...fresh.dom.window.document.getElementById('settingsApiModelSelect').options].map((option) => option.value).filter(Boolean);
  if (options.join(',') !== 'fresh-a,fresh-b') throw new Error(`model options mismatch: ${options.join(',')}`);
  fresh.dom.window.document.getElementById('settingsApiModelSelect').value = 'fresh-a';
  fresh.dom.window.document.querySelector('[data-settings-api-save]').click();
  await waitFor(() => fresh.state.calls.some((call) => call.url === '/api/ai/provider' && call.method === 'PUT') && apiSettingsState(fresh).model === 'fresh-a', 'fresh save');
  const save = fresh.state.calls.find((call) => call.url === '/api/ai/provider' && call.method === 'PUT');
  if (save.body.provider !== 'openai' || save.body.api_key !== 'fresh-form-key' || save.body.base_url !== 'http://fake.test/v1' || save.body.model !== 'fresh-a') throw new Error(`save payload mismatch: ${JSON.stringify(save.body)}`);
  if (apiSettingsState(fresh).model !== 'fresh-a' || apiSettingsState(fresh).keyConfigured !== true) throw new Error('save did not update formal state');
  if (fresh.dom.window.document.getElementById('settingsApiKeyInput').value !== '') throw new Error('saved API key remained in the DOM');
  if (!fresh.dom.window.document.getElementById('settingsApiStatus').textContent.includes('已保存')) throw new Error('save success status missing');
  fresh.dom.window.close();

  const changed = createPage({ preview: { body: { provider: 'openai', source: 'draft', models: ['old-a'], active_model: null, status: 'ok' } } });
  await openApiSettings(changed);
  fillApiForm(changed, { baseUrl: 'http://old-connection.test/v1', key: 'old-form-key' });
  await clickDiscover(changed);
  changed.dom.window.document.getElementById('settingsApiProviderSelect').value = 'deepseek';
  changed.dom.window.document.getElementById('settingsApiProviderSelect').dispatchEvent(new changed.dom.window.Event('change', { bubbles: true }));
  changed.dom.window.document.getElementById('settingsApiBaseInput').value = 'http://new-connection.test/v1';
  changed.dom.window.document.getElementById('settingsApiBaseInput').dispatchEvent(new changed.dom.window.Event('input', { bubbles: true }));
  changed.dom.window.document.getElementById('settingsApiKeyInput').value = 'new-form-key';
  changed.dom.window.document.getElementById('settingsApiKeyInput').dispatchEvent(new changed.dom.window.Event('input', { bubbles: true }));
  if (!changed.dom.window.document.getElementById('settingsApiModelSelect').disabled) throw new Error('changed connection kept old model options enabled');
  changed.dom.window.document.querySelector('[data-settings-api-save]').click();
  await tick();
  if (changed.state.calls.some((call) => call.url === '/api/ai/provider' && call.method === 'PUT')) throw new Error('changed connection saved stale model list');
  changed.dom.window.close();

  const existing = createPage({ provider: 'openai', baseUrl: 'http://saved.test/v1', model: 'saved-a', keyConfigured: true, getModels: ['saved-a'], preview: { body: { provider: 'openai', source: 'draft', models: ['saved-a', 'saved-b'], active_model: null, status: 'ok' } } });
  await openApiSettings(existing);
  fillApiForm(existing, { baseUrl: 'http://saved.test/v1', key: '' });
  await clickDiscover(existing);
  const reused = existing.state.calls.find((call) => call.url === '/api/ai/models' && call.method === 'POST');
  if (!reused || reused.body.api_key !== '' || reused.body.provider !== 'openai' || reused.body.base_url !== 'http://saved.test/v1') throw new Error(`same-connection blank-key draft mismatch: ${JSON.stringify(reused)}`);
  if (apiSettingsState(existing).model !== 'saved-a' || apiSettingsState(existing).baseUrl !== 'http://saved.test/v1') throw new Error('existing formal state changed during rediscovery');
  existing.dom.window.close();

  const empty = createPage({ preview: { body: { provider: 'openai', source: 'draft', models: [], active_model: null, status: 'empty' } } });
  await openApiSettings(empty);
  fillApiForm(empty, { baseUrl: 'http://empty.test/v1', key: 'empty-key' });
  await clickDiscover(empty);
  if (!empty.dom.window.document.getElementById('settingsApiStatus').textContent.includes('空列表')) throw new Error('empty model status missing');
  if (!empty.dom.window.document.getElementById('settingsApiModelSelect').disabled) throw new Error('empty model selector should be disabled');
  empty.dom.window.close();

  const failed = createPage({ preview: { status: 401, body: { detail: 'API Key 无效或未授权。' } } });
  await openApiSettings(failed);
  fillApiForm(failed, { baseUrl: 'http://failure.test/v1', key: 'bad-key' });
  await clickDiscover(failed);
  if (!failed.dom.window.document.getElementById('settingsApiStatus').textContent.includes('无效或未授权')) throw new Error('failure status missing');
  if (apiSettingsState(failed).provider !== 'local-demo' || apiSettingsState(failed).model !== '') throw new Error('failed discovery changed formal state');
  failed.dom.window.close();

  const saveFailed = createPage({ preview: { body: { provider: 'openai', source: 'draft', models: ['save-a'], active_model: null, status: 'ok' } }, save: { status: 503, body: { detail: 'AI provider 保存失败：key store unavailable' } } });
  await openApiSettings(saveFailed);
  fillApiForm(saveFailed, { baseUrl: 'http://save-failure.test/v1', key: 'save-key' });
  await clickDiscover(saveFailed);
  saveFailed.dom.window.document.getElementById('settingsApiModelSelect').value = 'save-a';
  saveFailed.dom.window.document.querySelector('[data-settings-api-save]').click();
  await waitFor(() => saveFailed.state.calls.some((call) => call.url === '/api/ai/provider' && call.method === 'PUT') && saveFailed.dom.window.document.getElementById('settingsApiStatus').textContent.includes('保存失败'), 'failed save');
  if (!saveFailed.dom.window.document.getElementById('settingsApiStatus').textContent.includes('保存失败')) throw new Error('save failure status missing');
  if (apiSettingsState(saveFailed).provider !== 'local-demo' || apiSettingsState(saveFailed).model !== '') throw new Error('failed save changed formal state');
  saveFailed.dom.window.close();

  const saveChanged = createPage({ preview: { body: { provider: 'openai', source: 'draft', models: ['save-old'], active_model: null, status: 'ok' } }, saveDelay: 1, save: { body: { provider: 'openai', base_url: 'http://save-change.test/v1', model: 'save-old', key_configured: true } } });
  await openApiSettings(saveChanged);
  fillApiForm(saveChanged, { baseUrl: 'http://save-change.test/v1', key: 'save-change-key' });
  await clickDiscover(saveChanged);
  saveChanged.dom.window.document.getElementById('settingsApiModelSelect').value = 'save-old';
  saveChanged.dom.window.document.querySelector('[data-settings-api-save]').click();
  await waitFor(() => !!saveChanged.state.saveResolve, 'save changed request');
  saveChanged.dom.window.document.getElementById('settingsApiBaseInput').value = 'http://edited-during-save.test/v1';
  saveChanged.dom.window.document.getElementById('settingsApiBaseInput').dispatchEvent(new saveChanged.dom.window.Event('input', { bubbles: true }));
  saveChanged.state.saveResolve();
  await waitFor(() => saveChanged.dom.window.document.getElementById('settingsApiStatus').textContent.includes('保存已完成'), 'save changed result');
  if (saveChanged.dom.window.document.getElementById('settingsApiBaseInput').value !== 'http://edited-during-save.test/v1') throw new Error('save response overwrote edited form');
  saveChanged.dom.window.close();

  const closedSave = createPage({ preview: { body: { provider: 'openai', source: 'draft', models: ['closed-save-model'], active_model: null, status: 'ok' } }, saveDelay: 1, save: { body: { provider: 'openai', base_url: 'http://closed-save.test/v1', model: 'closed-save-model', key_configured: true } } });
  await openApiSettings(closedSave);
  fillApiForm(closedSave, { baseUrl: 'http://closed-save.test/v1', key: 'closed-save-key' });
  await clickDiscover(closedSave);
  closedSave.dom.window.document.getElementById('settingsApiModelSelect').value = 'closed-save-model';
  closedSave.dom.window.document.querySelector('[data-settings-api-save]').click();
  await waitFor(() => !!closedSave.state.saveResolve, 'closed save request');
  closedSave.dom.window.document.querySelector('.modal-close').click();
  if (apiSettingsState(closedSave).model !== '') throw new Error('closed save updated formal state before PUT response');
  closedSave.state.saveResolve();
  await waitFor(() => apiSettingsState(closedSave).model === 'closed-save-model', 'closed save response');
  if (apiSettingsState(closedSave).provider !== 'openai' || apiSettingsState(closedSave).baseUrl !== 'http://closed-save.test/v1' || apiSettingsState(closedSave).keyConfigured !== true) throw new Error('closed save response was discarded');
  if (closedSave.dom.window.document.getElementById('settingsApiProviderSelect')) throw new Error('closed save response reopened modal');
  closedSave.dom.window.close();

  const blockedSave = createPage({ preview: { body: { provider: 'openai', source: 'draft', models: ['blocked-model'], active_model: null, status: 'ok' } }, saveDelay: 1, save: { body: { provider: 'openai', base_url: 'http://blocked-save.test/v1', model: 'blocked-model', key_configured: true } } });
  await openApiSettings(blockedSave);
  fillApiForm(blockedSave, { baseUrl: 'http://blocked-save.test/v1', key: 'blocked-key' });
  await clickDiscover(blockedSave);
  blockedSave.dom.window.document.getElementById('settingsApiModelSelect').value = 'blocked-model';
  blockedSave.dom.window.document.querySelector('[data-settings-api-save]').click();
  await waitFor(() => !!blockedSave.state.saveResolve, 'blocked save request');
  blockedSave.dom.window.document.querySelector('.modal-close').click();
  await openApiSettings(blockedSave);
  blockedSave.dom.window.document.querySelector('[data-settings-api-save]').click();
  await tick();
  if (blockedSave.state.calls.filter((call) => call.url === '/api/ai/provider' && call.method === 'PUT').length !== 1) throw new Error('unfinished closed save allowed a concurrent PUT');
  blockedSave.state.saveResolve();
  await waitFor(() => apiSettingsState(blockedSave).model === 'blocked-model', 'blocked save response');
  blockedSave.dom.window.close();

  const stale = createPage({ previewDelay: 1, preview: { body: { provider: 'openai', source: 'draft', models: ['stale-a'], active_model: null, status: 'ok' } } });
  await openApiSettings(stale);
  fillApiForm(stale, { baseUrl: 'http://stale-a.test/v1', key: 'stale-key' });
  const pending = clickDiscover(stale);
  await waitFor(() => !!stale.state.previewResolve, 'stale request');
  stale.dom.window.document.getElementById('settingsApiBaseInput').value = 'http://stale-b.test/v1';
  stale.state.previewResolve();
  await pending;
  if (!stale.dom.window.document.getElementById('settingsApiStatus').textContent.includes('表单已修改')) throw new Error('stale response was applied');
  stale.dom.window.close();

  const closed = createPage({ previewDelay: 1, preview: { body: { provider: 'openai', source: 'draft', models: ['closed-a'], active_model: null, status: 'ok' } } });
  await openApiSettings(closed);
  fillApiForm(closed, { baseUrl: 'http://closed.test/v1', key: 'closed-key' });
  const closedPending = clickDiscover(closed);
  await waitFor(() => !!closed.state.previewResolve, 'closed request');
  closed.dom.window.document.querySelector('.modal-close').click();
  closed.state.previewResolve();
  await closedPending;
  if (closed.dom.window.document.getElementById('settingsApiModelSelect')) throw new Error('closed modal was reopened by stale discovery');
  closed.dom.window.close();

  const refreshed = createPage({ provider: 'openai', baseUrl: 'http://refresh.test/v1', model: 'refresh-a', keyConfigured: true, getModels: ['refresh-a'] });
  await openApiSettings(refreshed);
  if (apiSettingsState(refreshed).provider !== 'openai' || apiSettingsState(refreshed).baseUrl !== 'http://refresh.test/v1' || apiSettingsState(refreshed).model !== 'refresh-a' || apiSettingsState(refreshed).keyConfigured !== true) throw new Error('refresh state mismatch');
  if (refreshed.dom.window.document.getElementById('settingsApiBaseInput').value !== 'http://refresh.test/v1') throw new Error('saved base URL was not shown after refresh');
  if (refreshed.dom.window.document.getElementById('settingsApiModelSelect').value !== 'refresh-a') throw new Error('saved model was not selected after refresh');
  if (!refreshed.dom.window.document.getElementById('settingsApiStatus').textContent.includes('当前模型：refresh-a')) throw new Error('saved model was not shown after refresh');
  refreshed.dom.window.close();

  console.log('PASS VAN19 formal production DOM');
}

run().catch((error) => {
  console.error(error.stack || error);
  process.exitCode = 1;
});
