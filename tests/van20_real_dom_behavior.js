'use strict';

/* Formal full-page JSDOM coverage for VAN-20.  The harness drives the real
 * static/index.html DOM and keeps a separate localStorage snapshot per page. */
const fs = require('fs');
const path = require('path');
const assert = require('assert');
const { JSDOM, VirtualConsole } = require(path.join(
  process.env.VAN16_DOM_DEPS || '/private/tmp/van13-jsdom-deps/node_modules',
  'jsdom'
));

const SOURCE_PATH = process.env.VAN20_SOURCE || path.join(__dirname, '..', 'static', 'index.html');
const SOURCE = fs.readFileSync(SOURCE_PATH, 'utf8');
const WORKSPACE_KEY = 'qd-ai-workspace-v2';

function response(body, status = 200) {
  return {
    ok: status >= 200 && status < 300,
    status,
    text: async () => JSON.stringify(body),
    json: async () => body,
  };
}

function bootPayload(url) {
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
  if (url === '/api/ai/provider') return { provider: 'local-demo', base_url: '', model: '', key_configured: false };
  if (url === '/api/ai/models') return { provider: 'local-demo', models: [], active_model: null };
  return {};
}

function workspaceWith(sessions, currentSessionId, extraProjects = []) {
  return {
    version: 2,
    projects: [
      { id: 'unclassified', name: '未分类', system: true, collapsed: false },
      { id: 'archived', name: '已归档', system: true, collapsed: false },
    ].concat(extraProjects),
    sessions,
    currentSessionId,
    migratedFromV1: false,
  };
}

function session(id, { title = id, archived = false, projectId = 'unclassified', messages = [] } = {}) {
  return { id, title, created: 1728000000000, projectId, archived, messages };
}

function createPage({ storage, rawStorage, legacyStorage, legacyCurrent, chatPlans = [] } = {}) {
  const state = { calls: [], chatRequests: [], errors: [], chatPlans: chatPlans.slice() };
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
      window.addEventListener('error', (event) => {
        if (event.error && event.error.stack) state.errors.push(event.error.stack);
      });
      if (rawStorage !== undefined) window.localStorage.setItem(WORKSPACE_KEY, String(rawStorage));
      else if (storage) window.localStorage.setItem(WORKSPACE_KEY, JSON.stringify(storage));
      if (legacyStorage !== undefined) window.localStorage.setItem('qd-sessions-v1', JSON.stringify(legacyStorage));
      if (legacyCurrent !== undefined) window.localStorage.setItem('qd-current-session', String(legacyCurrent));
      window.fetch = function fetchMock(url, options = {}) {
        const pathname = String(url);
        const method = (options.method || 'GET').toUpperCase();
        let body = null;
        try { body = options.body ? JSON.parse(options.body) : null; } catch (_) { body = options.body; }
        state.calls.push({ url: pathname, method, body });
        if (pathname === '/api/ai/chat' && method === 'POST') {
          const plan = state.chatPlans.shift() || { body: { message: { role: 'assistant', content: '默认回复' }, source: 'fake' } };
          const request = { body, plan, resolve: null };
          state.chatRequests.push(request);
          return new Promise((resolve) => {
            request.resolve = () => resolve(plan.error ? response(plan.body || { detail: plan.error }, plan.status || 500) : response(plan.body, plan.status || 200));
          });
        }
        return Promise.resolve(response(bootPayload(pathname)));
      };
    },
  });
  return { dom, state };
}

function tick() {
  return new Promise((resolve) => setImmediate(resolve));
}

async function waitFor(predicate, label) {
  for (let i = 0; i < 240; i += 1) {
    if (predicate()) return;
    await tick();
  }
  throw new Error(`timed out waiting for ${label}`);
}

function pageWorkspace(page) {
  // Reparse across the JSDOM realm so Node's deep assertions compare the
  // actual persisted snapshot rather than a foreign Array prototype.
  const value = JSON.parse(JSON.stringify(page.dom.window.__qdApp.getAiWorkspace()));
  assert(value && Array.isArray(value.sessions), 'read-only AI workspace hook returned a valid snapshot');
  return value;
}

function pagePending(page) {
  return JSON.parse(JSON.stringify(page.dom.window.__qdApp.getAiPending()));
}

function assertSurface(page, activeId, pendingIds = []) {
  const snapshot = pageWorkspace(page);
  const stored = JSON.parse(page.dom.window.localStorage.getItem(WORKSPACE_KEY));
  assert.deepStrictEqual(snapshot, stored, 'AI workspace memory equals localStorage');
  snapshot.sessions.forEach((item) => assert(!Object.prototype.hasOwnProperty.call(item, 'pending'), 'pending state is not persisted in a session'));
  assert.strictEqual(snapshot.currentSessionId, activeId, `current session is ${activeId}`);
  assert.deepStrictEqual(Object.keys(pagePending(page)).sort(), pendingIds.slice().sort(), 'runtime pending map matches expected session ids');
  const activeButton = activeId && sessionButton(page, activeId);
  if (activeId) assert(activeButton && activeButton.classList.contains('active'), 'active session is highlighted in the normal list');
  const button = page.dom.window.document.getElementById('chatSendBtn');
  assert.strictEqual(button.disabled, !!(activeId && pendingIds.includes(activeId)), 'send button reflects the active session pending state');
  const active = activeId && snapshot.sessions.find((item) => item.id === activeId);
  if (active && active.messages.length) {
    const visible = page.dom.window.document.getElementById('chatLog').textContent;
    active.messages.forEach((item) => assert(visible.includes(String(item.content)), `active chat DOM contains ${item.role} content`));
  }
}

function findSession(page, id) {
  return pageWorkspace(page).sessions.find((item) => item.id === id) || null;
}

function sessionButton(page, id) {
  return [...page.dom.window.document.querySelectorAll('[data-session-id]')].find((item) => item.getAttribute('data-session-id') === id);
}

function selectSession(page, id) {
  const button = sessionButton(page, id);
  assert(button, `session ${id} is visible in the normal list`);
  button.click();
}

function sendByButton(page, text) {
  const input = page.dom.window.document.getElementById('chatInput');
  input.value = text;
  page.dom.window.document.getElementById('chatSendBtn').click();
}

function sendByEnter(page, text) {
  const input = page.dom.window.document.getElementById('chatInput');
  input.value = text;
  input.dispatchEvent(new page.dom.window.KeyboardEvent('keydown', { key: 'Enter', bubbles: true }));
}

function sendByShortcut(page, text) {
  const button = page.dom.window.document.createElement('button');
  button.type = 'button';
  button.setAttribute('data-chat-q', text);
  page.dom.window.document.body.appendChild(button);
  button.click();
  button.remove();
}

function openSessionMenu(page, id) {
  const button = [...page.dom.window.document.querySelectorAll('[data-session-menu]')].find((item) => item.getAttribute('data-session-menu') === id);
  assert(button, `session ${id} has a menu button`);
  button.click();
}

async function booted(page) {
  await waitFor(() => !!page.dom.window.__qdApp || page.state.errors.length, 'production app hook');
  assert(page.dom.window.__qdApp, `production app hook initialized: ${page.state.errors.join('\n')}`);
  await tick();
  assert.deepStrictEqual(page.state.errors, [], `production page has no JSDOM errors: ${page.state.errors.join('\n')}`);
}

async function run() {
  const initial = workspaceWith([
    session('A', { title: '会话 A' }),
    session('B', { title: '会话 B' }),
  ], 'A');
  const page = createPage({
    storage: initial,
    chatPlans: [
      { body: { message: { role: 'assistant', content: '回复 A' }, source: 'fake' } },
      { body: { message: { role: 'assistant', content: '回复 B' }, source: 'fake' } },
    ],
  });
  await booted(page);
  assert.strictEqual(pageWorkspace(page).currentSessionId, 'A', 'initial current session is A');
  assertSurface(page, 'A', []);

  // Same-session button/Enter/shortcut guards share the real request pending map.
  sendByButton(page, '问题 A');
  await waitFor(() => page.state.chatRequests.length === 1, 'A request');
  assert(pagePending(page).A, 'A has a runtime pending token');
  assert.strictEqual(page.dom.window.document.getElementById('chatSendBtn').disabled, true, 'A send button is disabled while A is pending');
  assertSurface(page, 'A', ['A']);
  page.dom.window.document.getElementById('chatSendBtn').click();
  sendByEnter(page, '重复 Enter');
  sendByShortcut(page, '重复快捷问题');
  await tick();
  assert.strictEqual(page.state.chatRequests.length, 1, 'Enter and shortcut cannot create a second A request');
  assert.deepStrictEqual(findSession(page, 'A').messages.map((item) => item.content), ['问题 A'], 'same-session guard also prevents duplicate user messages');

  // A -> B, then B -> A response order: each body and response stays with its origin.
  selectSession(page, 'B');
  assert.strictEqual(page.dom.window.document.getElementById('chatSendBtn').disabled, false, 'B send button is enabled while A is pending');
  assertSurface(page, 'B', ['A']);
  sendByButton(page, '问题 B');
  await waitFor(() => page.state.chatRequests.length === 2, 'B request');
  assert(pagePending(page).A && pagePending(page).B, 'A and B have independent pending tokens');
  assertSurface(page, 'B', ['A', 'B']);
  const requestA = page.state.chatRequests[0];
  const requestB = page.state.chatRequests[1];
  assert(requestA.body.messages.some((item) => item.content === '问题 A'), 'A request history belongs to A');
  assert(!requestA.body.messages.some((item) => item.content === '问题 B'), 'A request history excludes B');
  assert(requestB.body.messages.some((item) => item.content === '问题 B'), 'B request history belongs to B');
  assert(!requestB.body.messages.some((item) => item.content === '问题 A'), 'B request history excludes A');
  requestB.resolve();
  await waitFor(() => !pagePending(page).B, 'B completion');
  assert.deepStrictEqual(findSession(page, 'B').messages.map((item) => item.content), ['问题 B', '回复 B'], 'B receives its out-of-order response');
  assert.deepStrictEqual(findSession(page, 'A').messages.map((item) => item.content), ['问题 A'], 'A has no B response');
  assert.strictEqual(page.dom.window.document.getElementById('chatSendBtn').disabled, false, 'B button is re-enabled without changing A pending');
  assertSurface(page, 'B', ['A']);
  selectSession(page, 'A');
  assert.strictEqual(page.dom.window.document.getElementById('chatSendBtn').disabled, true, 'switching back to A shows A pending state');
  assertSurface(page, 'A', ['A']);
  requestA.resolve();
  await waitFor(() => !pagePending(page).A, 'A completion');
  assert.deepStrictEqual(findSession(page, 'A').messages.map((item) => item.content), ['问题 A', '回复 A'], 'A receives its response after B');
  assert.deepStrictEqual(findSession(page, 'B').messages.map((item) => item.content), ['问题 B', '回复 B'], 'B remains isolated after A completes');
  assertSurface(page, 'A', []);
  const storedAfterReplies = JSON.parse(page.dom.window.localStorage.getItem(WORKSPACE_KEY));
  assert.deepStrictEqual(storedAfterReplies.sessions.find((item) => item.id === 'A').messages.map((item) => item.content), ['问题 A', '回复 A'], 'localStorage stores A reply in A');
  assert.deepStrictEqual(storedAfterReplies.sessions.find((item) => item.id === 'B').messages.map((item) => item.content), ['问题 B', '回复 B'], 'localStorage stores B reply in B');

  const reverse = createPage({
    storage: workspaceWith([session('A'), session('B')], 'A'),
    chatPlans: [
      { body: { message: { role: 'assistant', content: 'A先完成' }, source: 'api' } },
      { body: { message: { role: 'assistant', content: 'B后完成' }, source: 'api' } },
    ],
  });
  await booted(reverse);
  sendByButton(reverse, 'A先发');
  await waitFor(() => reverse.state.chatRequests.length === 1, 'reverse A request');
  selectSession(reverse, 'B');
  sendByButton(reverse, 'B后发');
  await waitFor(() => reverse.state.chatRequests.length === 2, 'reverse B request');
  reverse.state.chatRequests[0].resolve();
  await waitFor(() => !pagePending(reverse).A, 'A first completion while B is active');
  assert.strictEqual(pageWorkspace(reverse).currentSessionId, 'B', 'A completion does not change the active B session');
  assert.strictEqual(reverse.dom.window.document.getElementById('chatSendBtn').disabled, true, 'A finally cannot re-enable the still-pending B button');
  assert.deepStrictEqual(findSession(reverse, 'B').messages.map((item) => item.content), ['B后发'], 'B DOM/state remains unchanged while A completes');
  assertSurface(reverse, 'B', ['B']);
  reverse.state.chatRequests[1].resolve();
  await waitFor(() => Object.keys(pagePending(reverse)).length === 0, 'reverse B completion');
  assert.deepStrictEqual(findSession(reverse, 'A').messages.map((item) => item.content), ['A先发', 'A先完成'], 'A first response uses API source and original session');
  assert.strictEqual(findSession(reverse, 'A').messages[1].source, 'api', 'successful response keeps source api');
  assert.deepStrictEqual(findSession(reverse, 'B').messages.map((item) => item.content), ['B后发', 'B后完成'], 'B later response remains in B');
  assertSurface(reverse, 'B', []);
  reverse.dom.window.close();

  const singleSwitch = createPage({
    storage: workspaceWith([session('A'), session('B')], 'A'),
    chatPlans: [{ body: { message: { role: 'assistant', content: 'A only reply' }, source: 'api' } }],
  });
  await booted(singleSwitch);
  sendByButton(singleSwitch, 'A only question');
  await waitFor(() => singleSwitch.state.chatRequests.length === 1, 'single A request');
  selectSession(singleSwitch, 'B');
  assertSurface(singleSwitch, 'B', ['A']);
  singleSwitch.state.chatRequests[0].resolve();
  await waitFor(() => Object.keys(pagePending(singleSwitch)).length === 0, 'single A response while B is active');
  assert.strictEqual(pageWorkspace(singleSwitch).currentSessionId, 'B', 'single A response leaves B active');
  assert.strictEqual(singleSwitch.dom.window.document.getElementById('chatLog').textContent.includes('A only reply'), false, 'B chat DOM does not show A response');
  assert.strictEqual(singleSwitch.dom.window.document.getElementById('chatSendBtn').disabled, false, 'B button is available after A completes');
  assertSurface(singleSwitch, 'B', []);
  singleSwitch.dom.window.close();

  const resend = createPage({
    storage: workspaceWith([session('A')], 'A'),
    chatPlans: [
      { body: { message: { role: 'assistant', content: '首次 assistant' }, source: 'api' } },
      { body: { message: { role: 'assistant', content: '第二次 assistant' }, source: 'api' } },
    ],
  });
  await booted(resend);
  sendByButton(resend, '首次问题');
  await waitFor(() => resend.state.chatRequests.length === 1, 'first resend request');
  resend.state.chatRequests[0].resolve();
  await waitFor(() => Object.keys(pagePending(resend)).length === 0, 'first resend response');
  assert.strictEqual(findSession(resend, 'A').messages[1].source, 'api', 'ordinary successful response is stored as api');
  sendByButton(resend, '第二次问题');
  await waitFor(() => resend.state.chatRequests.length === 2, 'second resend request');
  const secondRequestMessages = resend.state.chatRequests[1].body.messages;
  assert(secondRequestMessages.some((item) => item.role === 'assistant' && item.content === '首次 assistant'), 'next request history includes the prior assistant response');
  resend.state.chatRequests[1].resolve();
  await waitFor(() => Object.keys(pagePending(resend)).length === 0, 'second resend response');
  assert.deepStrictEqual(findSession(resend, 'A').messages.map((item) => item.content), ['首次问题', '首次 assistant', '第二次问题', '第二次 assistant'], 'ordinary session supports a second message round');
  assertSurface(resend, 'A', []);
  const resendStorage = JSON.parse(resend.dom.window.localStorage.getItem(WORKSPACE_KEY));
  const resendRefresh = createPage({ storage: resendStorage });
  await booted(resendRefresh);
  assert.deepStrictEqual(findSession(resendRefresh, 'A').messages.map((item) => item.content), ['首次问题', '首次 assistant', '第二次问题', '第二次 assistant'], 'second-round messages survive refresh');
  assert.deepStrictEqual(pagePending(resendRefresh), {}, 'a fresh DOM has no persisted pending request');
  resendRefresh.dom.window.close();
  resend.dom.window.close();

  const creation = createPage({ storage: workspaceWith([session('A')], 'A') });
  await booted(creation);
  creation.dom.window.document.getElementById('sessionNew').click();
  await tick();
  const createdState = pageWorkspace(creation);
  assert.strictEqual(createdState.sessions.length, 2, 'new session creates exactly one persisted session');
  assert(createdState.currentSessionId && createdState.currentSessionId !== 'A', 'new session becomes current');
  assertSurface(creation, createdState.currentSessionId, []);
  selectSession(creation, 'A');
  assertSurface(creation, 'A', []);
  creation.dom.window.close();

  // Failed request ownership follows the same originating session id.
  const failed = createPage({
    storage: workspaceWith([session('A', { title: '失败 A' }), session('B', { title: '失败 B' })], 'A'),
    chatPlans: [
      { error: 'fake provider failure', body: { detail: 'fake provider failure' }, status: 503 },
      { body: { message: { role: 'assistant', content: 'B success' }, source: 'api' } },
    ],
  });
  await booted(failed);
  sendByButton(failed, '失败请求');
  await waitFor(() => failed.state.chatRequests.length === 1, 'failed request');
  assertSurface(failed, 'A', ['A']);
  selectSession(failed, 'B');
  assertSurface(failed, 'B', ['A']);
  sendByButton(failed, 'B pending');
  await waitFor(() => failed.state.chatRequests.length === 2, 'B request while A is pending');
  assertSurface(failed, 'B', ['A', 'B']);
  failed.state.chatRequests[0].resolve();
  await waitFor(() => !pagePending(failed).A, 'failed A completion');
  const failedA = findSession(failed, 'A');
  assert(failedA.messages[1].content.includes('后端 AI 暂不可用'), 'failure fallback is recorded');
  assert(failedA.messages[1].content.includes('fake provider failure'), 'failure detail is recorded in A');
  assert.deepStrictEqual(findSession(failed, 'B').messages.map((item) => item.content), ['B pending'], 'B remains without A failure content');
  assert.strictEqual(failed.dom.window.document.getElementById('chatSendBtn').disabled, true, 'A finally cannot re-enable B while B is pending');
  assertSurface(failed, 'B', ['B']);
  failed.state.chatRequests[1].resolve();
  await waitFor(() => Object.keys(pagePending(failed)).length === 0, 'B completion after A failure');
  assert.deepStrictEqual(findSession(failed, 'B').messages.map((item) => item.content), ['B pending', 'B success'], 'B completes independently after A failure');
  assertSurface(failed, 'B', []);
  failed.dom.window.close();

  // Pending + archive keeps the original session and allows restoration by identity.
  const archived = createPage({
    storage: workspaceWith([session('A', { title: '<A> 历史' }), session('B', { title: '保留 B' })], 'A'),
    chatPlans: [{ body: { message: { role: 'assistant', content: '归档后回复' }, source: 'fake' } }],
  });
  await booted(archived);
  sendByButton(archived, '归档前问题');
  await waitFor(() => archived.state.chatRequests.length === 1, 'pending archive request');
  assertSurface(archived, 'A', ['A']);
  const archivedSessionIdentity = findSession(archived, 'A');
  const archivedSessionFields = { id: archivedSessionIdentity.id, title: archivedSessionIdentity.title, created: archivedSessionIdentity.created };
  selectSession(archived, 'B');
  assertSurface(archived, 'B', ['A']);
  openSessionMenu(archived, 'A');
  archived.dom.window.document.querySelector('[data-session-archive="A"]').click();
  const archivedState = pageWorkspace(archived);
  assert.strictEqual(archivedState.currentSessionId, 'B', 'archiving inactive A keeps active B');
  assert.strictEqual(findSession(archived, 'A').archived, true, 'A is archived without deletion');
  assert(pagePending(archived).A, 'pending A survives archive');
  assertSurface(archived, 'B', ['A']);
  archived.state.chatRequests[0].resolve();
  await waitFor(() => !pagePending(archived).A, 'archived A completion');
  assert.deepStrictEqual(findSession(archived, 'A').messages.map((item) => item.content), ['归档前问题', '归档后回复'], 'late response remains in archived A');
  assert.deepStrictEqual(findSession(archived, 'B').messages, [], 'late response does not enter B');
  assertSurface(archived, 'B', []);
  archived.dom.window.document.querySelector('[data-open-settings-modal="archive"]').click();
  await tick();
  const restoreButton = archived.dom.window.document.querySelector('[data-settings-session-restore="A"]');
  assert(restoreButton, 'archived session is discoverable in settings');
  assert(archived.dom.window.document.querySelector('.settings-modal-body').innerHTML.includes('&lt;A&gt; 历史'), 'archived session title is HTML-escaped');
  assert(archived.dom.window.document.querySelector('.settings-modal-body').textContent.includes('归档会话'), 'archive entry explicitly labels archived sessions');
  restoreButton.click();
  await tick();
  const restoredA = findSession(archived, 'A');
  assert(restoredA && !restoredA.archived && restoredA.projectId === 'unclassified', 'restore keeps A identity and returns it to unclassified');
  assert.strictEqual(pageWorkspace(archived).sessions.length, 2, 'session restore does not duplicate the session');
  assert.strictEqual(restoredA.id, archivedSessionFields.id, 'restore preserves session id');
  assert.strictEqual(restoredA.title, archivedSessionFields.title, 'restore preserves session title');
  assert.strictEqual(restoredA.created, archivedSessionFields.created, 'restore preserves session created timestamp');
  assert.deepStrictEqual(restoredA.messages.map((item) => item.content), ['归档前问题', '归档后回复'], 'restore keeps archived messages');
  assert(sessionButton(archived, 'A'), 'restored A returns to the normal session list');
  const restoredStorage = JSON.parse(archived.dom.window.localStorage.getItem(WORKSPACE_KEY));
  assert.strictEqual(restoredStorage.sessions.find((item) => item.id === 'A').archived, false, 'restore is immediately persisted');
  assertSurface(archived, 'B', []);
  archived.dom.window.close();
  const refreshed = createPage({ storage: restoredStorage });
  await booted(refreshed);
  assert.strictEqual(findSession(refreshed, 'A').archived, false, 'refresh reads restored archive state');
  assert.deepStrictEqual(findSession(refreshed, 'A').messages.map((item) => item.content), ['归档前问题', '归档后回复'], 'refresh reads restored messages');
  assert.strictEqual(pageWorkspace(refreshed).currentSessionId, 'B', 'refresh preserves the active session round-trip');
  selectSession(refreshed, 'A');
  assert.strictEqual(pageWorkspace(refreshed).currentSessionId, 'A', 'refreshed DOM can select the restored session');
  assert(refreshed.dom.window.document.getElementById('chatLog').textContent.includes('归档后回复'), 'refreshed DOM renders the restored assistant message');
  assertSurface(refreshed, 'A', []);
  refreshed.dom.window.close();

  // Active archive: current moves to another valid session, or creates an empty one
  // when the archived session was the only visible session.
  const activeArchive = createPage({ storage: workspaceWith([session('A'), session('B')], 'A') });
  await booted(activeArchive);
  openSessionMenu(activeArchive, 'A');
  activeArchive.dom.window.document.querySelector('[data-session-archive="A"]').click();
  assert.strictEqual(pageWorkspace(activeArchive).currentSessionId, 'B', 'active archive selects the first other valid session');
  assert.strictEqual(findSession(activeArchive, 'A').archived, true, 'active A remains stored as archived');
  assertSurface(activeArchive, 'B', []);
  activeArchive.dom.window.close();

  const onlyArchive = createPage({ storage: workspaceWith([session('only', { title: '唯一会话' })], 'only') });
  await booted(onlyArchive);
  openSessionMenu(onlyArchive, 'only');
  onlyArchive.dom.window.document.querySelector('[data-session-archive="only"]').click();
  const onlyState = pageWorkspace(onlyArchive);
  assert.strictEqual(findSession(onlyArchive, 'only').archived, true, 'only active session can be archived');
  assert(onlyState.currentSessionId && onlyState.currentSessionId !== 'only', 'only-session archive creates a new active empty session');
  assert(sessionButton(onlyArchive, onlyState.currentSessionId), 'new active session is visible after only-session archive');
  assertSurface(onlyArchive, onlyState.currentSessionId, []);
  sendByButton(onlyArchive, '替代会话下一条');
  await waitFor(() => onlyArchive.state.chatRequests.length === 1, 'next message after only-session archive');
  onlyArchive.state.chatRequests[0].resolve();
  await waitFor(() => Object.keys(pagePending(onlyArchive)).length === 0, 'next message completion after only-session archive');
  assert(findSession(onlyArchive, onlyState.currentSessionId).messages.some((item) => item.content === '替代会话下一条'), 'next message enters the replacement session');
  assertSurface(onlyArchive, onlyState.currentSessionId, []);
  onlyArchive.dom.window.close();

  const malformedRaw = '{"version":1,"keep":"original"}';
  const recovery = createPage({
    rawStorage: malformedRaw,
    chatPlans: [{ body: { message: { role: 'assistant', content: '空工作区后的回复' }, source: 'fake' } }],
  });
  await booted(recovery);
  assert.strictEqual(recovery.dom.window.localStorage.getItem(WORKSPACE_KEY), malformedRaw, 'migration failure leaves the original workspace storage untouched');
  assert.strictEqual(pageWorkspace(recovery).currentSessionId, null, 'migration failure has no active session before an explicit choice');
  recovery.dom.window.document.querySelector('[data-workspace-empty]').click();
  await tick();
  const emptyWorkspace = pageWorkspace(recovery);
  assert(emptyWorkspace.currentSessionId && findSession(recovery, emptyWorkspace.currentSessionId), 'explicit empty-workspace recovery creates a valid active session');
  assertSurface(recovery, emptyWorkspace.currentSessionId, []);
  sendByButton(recovery, '恢复后发送');
  await waitFor(() => recovery.state.chatRequests.length === 1, 'post-recovery request');
  assertSurface(recovery, emptyWorkspace.currentSessionId, [emptyWorkspace.currentSessionId]);
  const recoveryBeforeArchive = pageWorkspace(recovery);
  const recoveryActiveId = recoveryBeforeArchive.currentSessionId;
  openSessionMenu(recovery, recoveryActiveId);
  recovery.dom.window.document.querySelector(`[data-session-archive="${recoveryActiveId}"]`).click();
  const replacementId = pageWorkspace(recovery).currentSessionId;
  assert(replacementId && replacementId !== recoveryActiveId, 'recovery flag does not block replacement session after archiving the only session');
  assertSurface(recovery, replacementId, [recoveryActiveId]);
  recovery.state.chatRequests[0].resolve();
  await waitFor(() => Object.keys(pagePending(recovery)).length === 0, 'post-recovery response');
  assertSurface(recovery, replacementId, []);
  sendByButton(recovery, '替代会话消息');
  await waitFor(() => recovery.state.chatRequests.length === 2, 'replacement session request');
  recovery.state.chatRequests[1].resolve();
  await waitFor(() => Object.keys(pagePending(recovery)).length === 0, 'replacement response');
  assert(findSession(recovery, replacementId).messages.some((item) => item.content === '替代会话消息'), 'next message enters the replacement session after recovery');
  assertSurface(recovery, replacementId, []);
  const recoveryStorage = JSON.parse(recovery.dom.window.localStorage.getItem(WORKSPACE_KEY));
  assert.deepStrictEqual(recoveryStorage, pageWorkspace(recovery), 'recovery workspace snapshot equals localStorage');
  const recoveryRefresh = createPage({ storage: recoveryStorage });
  await booted(recoveryRefresh);
  assert.strictEqual(pageWorkspace(recoveryRefresh).currentSessionId, replacementId, 'replacement current session survives refresh');
  assertSurface(recoveryRefresh, replacementId, []);
  recoveryRefresh.dom.window.close();
  recovery.dom.window.close();

  const legacySessions = [{
    id: 'legacy-1',
    title: '旧会话',
    created: 1728000000000,
    messages: [{ role: 'bot', content: '旧消息', html: '<p>旧消息</p>' }],
  }];
  const retryMigration = createPage({ rawStorage: '{"version":1}', legacyStorage: legacySessions, legacyCurrent: 'legacy-1' });
  await booted(retryMigration);
  retryMigration.dom.window.document.querySelector('[data-workspace-retry]').click();
  await tick();
  assert.strictEqual(pageWorkspace(retryMigration).currentSessionId, 'legacy-1', 'successful retry restores the legacy current session');
  assert.deepStrictEqual(findSession(retryMigration, 'legacy-1').messages.map((item) => item.content), ['旧消息'], 'v1 migration preserves legacy messages');
  assert.strictEqual(retryMigration.dom.window.localStorage.getItem('qd-sessions-v1'), JSON.stringify(legacySessions), 'v1 source key is preserved');
  retryMigration.dom.window.close();

  const projectArchive = createPage({
    storage: workspaceWith(
      [session('project-session', { title: '项目会话', projectId: 'project-1' }), session('unclassified-session', { title: '未分类会话' })],
      'project-session',
      [{ id: 'project-1', name: '<项目 1>', collapsed: false, archived: false }],
    ),
    chatPlans: [{ body: { message: { role: 'assistant', content: '项目 A 回复' }, source: 'fake' } }],
  });
  await booted(projectArchive);
  sendByButton(projectArchive, '项目 A 问题');
  await waitFor(() => projectArchive.state.chatRequests.length === 1, 'active project pending request');
  const projectSessionBeforeArchive = findSession(projectArchive, 'project-session');
  const projectSessionIdentity = { id: projectSessionBeforeArchive.id, title: projectSessionBeforeArchive.title, created: projectSessionBeforeArchive.created };
  assertSurface(projectArchive, 'project-session', ['project-session']);
  projectArchive.dom.window.document.querySelector('[data-project-archive="project-1"]').click();
  assert.strictEqual(pageWorkspace(projectArchive).currentSessionId, 'unclassified-session', 'archiving the active project selects a visible session');
  assert.strictEqual(pageWorkspace(projectArchive).projects.find((item) => item.id === 'project-1').archived, true, 'project archive persists');
  assert.strictEqual(findSession(projectArchive, 'project-session').archived, false, 'project archive preserves child session data');
  assert.strictEqual(projectArchive.dom.window.document.getElementById('chatLog').textContent.includes('项目 A 问题'), false, 'project archive redraws chat to the replacement session');
  assert.strictEqual(projectArchive.dom.window.document.getElementById('chatSendBtn').disabled, false, 'replacement session is sendable while hidden project request is pending');
  assertSurface(projectArchive, 'unclassified-session', ['project-session']);
  projectArchive.state.chatRequests[0].resolve();
  await waitFor(() => Object.keys(pagePending(projectArchive)).length === 0, 'active project response');
  assert.deepStrictEqual(findSession(projectArchive, 'project-session').messages.map((item) => item.content), ['项目 A 问题', '项目 A 回复'], 'hidden project keeps the pending response in its original session');
  assertSurface(projectArchive, 'unclassified-session', []);
  projectArchive.dom.window.document.querySelector('[data-open-settings-modal="archive"]').click();
  const escapedProjectRestore = projectArchive.dom.window.document.querySelector('[data-settings-arch-restore="project-1"]');
  assert(escapedProjectRestore, 'archived project remains discoverable');
  assert(projectArchive.dom.window.document.querySelector('.settings-modal-body').innerHTML.includes('&lt;项目 1&gt;'), 'archived project title is HTML-escaped');
  escapedProjectRestore.click();
  assert.strictEqual(pageWorkspace(projectArchive).projects.find((item) => item.id === 'project-1').archived, false, 'project restore persists');
  assertSurface(projectArchive, 'unclassified-session', []);
  const restoredProjectSession = findSession(projectArchive, 'project-session');
  assert.strictEqual(pageWorkspace(projectArchive).sessions.length, 2, 'project restore does not duplicate sessions');
  assert.strictEqual(restoredProjectSession.id, projectSessionIdentity.id, 'project restore preserves session id');
  assert.strictEqual(restoredProjectSession.title, projectSessionIdentity.title, 'project restore preserves session title');
  assert.strictEqual(restoredProjectSession.created, projectSessionIdentity.created, 'project restore preserves session created timestamp');
  assert.deepStrictEqual(restoredProjectSession.messages.map((item) => item.content), ['项目 A 问题', '项目 A 回复'], 'project restore preserves complete messages');
  selectSession(projectArchive, 'project-session');
  assertSurface(projectArchive, 'project-session', []);
  assert(projectArchive.dom.window.document.getElementById('chatLog').textContent.includes('项目 A 回复'), 'restored project session is rendered in chat');
  projectArchive.dom.window.document.querySelector('[data-project-delete="project-1"]').click();
  projectArchive.dom.window.document.querySelector('[data-project-delete-confirm="project-1"][data-disposition="archive"]').click();
  assert(!pageWorkspace(projectArchive).projects.some((item) => item.id === 'project-1'), 'project delete removes the project');
  assert.strictEqual(findSession(projectArchive, 'project-session').archived, true, 'project delete archive disposition archives child sessions');
  assert.strictEqual(pageWorkspace(projectArchive).currentSessionId, 'unclassified-session', 'project delete keeps a valid active session');
  assertSurface(projectArchive, 'unclassified-session', []);
  projectArchive.dom.window.close();

  // Startup normalization repairs an archived current id and a deleted late response
  // cannot resurrect or contaminate another session.
  const startup = createPage({ storage: workspaceWith([session('old', { archived: true, projectId: 'archived' }), session('live')], 'old') });
  await booted(startup);
  assert.strictEqual(pageWorkspace(startup).currentSessionId, 'live', 'startup replaces an archived current id with a valid session');
  assertSurface(startup, 'live', []);
  startup.dom.window.close();

  const missingCurrent = createPage({ storage: workspaceWith([session('live')], 'missing') });
  await booted(missingCurrent);
  assert.strictEqual(pageWorkspace(missingCurrent).currentSessionId, 'live', 'startup replaces a missing current id with the first valid session');
  assertSurface(missingCurrent, 'live', []);
  missingCurrent.dom.window.close();

  const noVisible = createPage({
    storage: workspaceWith(
      [session('hidden', { projectId: 'archived-project' })],
      'hidden',
      [{ id: 'archived-project', name: '归档项目', collapsed: false, archived: true }],
    ),
  });
  await booted(noVisible);
  const noVisibleState = pageWorkspace(noVisible);
  assert(noVisibleState.currentSessionId && noVisibleState.currentSessionId !== 'hidden', 'startup creates an empty session when only an archived project is visible');
  assertSurface(noVisible, noVisibleState.currentSessionId, []);
  noVisible.dom.window.close();

  const deleted = createPage({
    storage: workspaceWith([session('A'), session('B')], 'A'),
    chatPlans: [{ body: { message: { role: 'assistant', content: '应被丢弃' }, source: 'fake' } }],
  });
  await booted(deleted);
  sendByButton(deleted, '删除前请求');
  await waitFor(() => deleted.state.chatRequests.length === 1, 'request before deletion');
  assertSurface(deleted, 'A', ['A']);
  openSessionMenu(deleted, 'A');
  deleted.dom.window.document.querySelector('[data-session-delete="A"]').click();
  deleted.dom.window.document.querySelector('[data-session-delete-confirm="A"]').click();
  assert(!findSession(deleted, 'A'), 'deleted session is removed immediately');
  assertSurface(deleted, 'B', ['A']);
  deleted.state.chatRequests[0].resolve();
  await waitFor(() => Object.keys(pagePending(deleted)).length === 0, 'deleted request completion');
  assert.deepStrictEqual(findSession(deleted, 'B').messages, [], 'late response for deleted A does not fall back into B');
  assert(!JSON.parse(deleted.dom.window.localStorage.getItem(WORKSPACE_KEY)).sessions.some((item) => item.id === 'A'), 'deleted A stays absent from localStorage');
  assertSurface(deleted, 'B', []);
  deleted.dom.window.close();

  const scenarioPasses = [
    'request ownership and same-session button/Enter/shortcut guard',
    'cross-session out-of-order replies and button isolation',
    'A-first completion while B remains active and pending',
    'single A request returns while B remains active',
    'ordinary success, api source, resend history, and refresh',
    'new session creation, switching, and storage/UI coherence',
    'failed request ownership and fallback',
    'pending response retained through archive',
    'archived session discovery, restore, storage round-trip, refresh',
    'active archive and only-session archive normalization',
    'project archive, project restore, and project-delete disposition',
    'migration failure empty recovery and v1 migration retry',
    'startup archived/missing current and hidden-project normalization',
    'deleted-origin late response is ignored',
  ];
  scenarioPasses.forEach((scenario) => console.log(`PASS VAN20 scenario: ${scenario}`));
  console.log(`PASS VAN20 scenario count: ${scenarioPasses.length}`);
  console.log('PASS VAN20 formal production DOM');
}

run().catch((error) => {
  console.error(error.stack || error);
  process.exitCode = 1;
});
