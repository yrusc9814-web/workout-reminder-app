const apiCalls = new Set();
let todayPlan = null;

const $ = (id) => document.getElementById(id);
const today = new Date();
const isoToday = today.toISOString().slice(0, 10);
const year = today.getFullYear();
const month = today.getMonth() + 1;

function recordApi(path) {
  apiCalls.add(path.replace(/([?&](date|year|month)=)[^&]+/g, '$1…'));
  $('apiCalls').textContent = Array.from(apiCalls).sort().join(' | ');
}

async function api(path, options = {}) {
  recordApi(path);
  const response = await fetch(path, {
    headers: { 'Content-Type': 'application/json', ...(options.headers || {}) },
    ...options,
  });
  const text = await response.text();
  const data = text ? JSON.parse(text) : null;
  if (!response.ok) {
    throw new Error(`${response.status} ${response.statusText}: ${text}`);
  }
  return data;
}

function escapeHtml(value) {
  return String(value ?? '').replace(/[&<>'"]/g, (ch) => ({
    '&': '&amp;', '<': '&lt;', '>': '&gt;', "'": '&#39;', '"': '&quot;'
  }[ch]));
}

function planClass(day) {
  return day?.is_training ? 'training' : 'rest';
}

function renderPlan(day) {
  if (!day || !day.id) {
    return `<div class="item rest"><strong>${escapeHtml(day?.date || '')}</strong> 休息日 / 暂无计划</div>`;
  }
  const items = (day.items || []).map((item) => {
    const detail = item.duration_seconds
      ? `${item.duration_seconds} 秒`
      : `${item.sets || '-'} 组 × ${item.reps || '-'} 次`;
    return `<li>${escapeHtml(item.name)}：${escapeHtml(detail)} <span class="muted-text">${escapeHtml(item.instructions || '')}</span></li>`;
  }).join('');
  return `<div class="item ${planClass(day)}">
    <strong>${escapeHtml(day.date)}｜${escapeHtml(day.title || '训练')}</strong>
    <div>${escapeHtml(day.theme || day.type || '')}</div>
    ${day.notes ? `<div>${escapeHtml(day.notes)}</div>` : ''}
    ${items ? `<ul>${items}</ul>` : ''}
  </div>`;
}

async function loadHealth() {
  const target = $('health');
  target.className = 'status pending';
  target.textContent = '检测中...';
  try {
    const data = await api('/api/health');
    target.className = 'status ok';
    target.textContent = `正常：${data.status}`;
  } catch (error) {
    target.className = 'status error';
    target.textContent = `异常：${error.message}`;
    throw error;
  }
}

async function loadToday() {
  todayPlan = await api('/api/today');
  $('todayDate').textContent = todayPlan.date || isoToday;
  $('todayPlan').innerHTML = renderPlan(todayPlan);
  const enabled = Boolean(todayPlan && todayPlan.id);
  ['completeBtn', 'skipBtn', 'postponeBtn'].forEach((id) => { $(id).disabled = !enabled; });
}

async function loadWeek() {
  const data = await api(`/api/plans/week?date=${isoToday}`);
  $('weekPlan').innerHTML = (data.days || []).map(renderPlan).join('');
}

async function loadMonth() {
  const data = await api(`/api/plans/month?year=${year}&month=${month}`);
  $('monthPlan').innerHTML = (data.days || []).map((day) => {
    const label = day.id ? `${day.title || day.type}` : '无计划';
    return `<div class="item ${planClass(day)}"><strong>${escapeHtml(day.date)}</strong> ${escapeHtml(label)}</div>`;
  }).join('');
}

async function loadCalendar() {
  const data = await api(`/api/calendar?year=${year}&month=${month}`);
  $('calendar').innerHTML = (data.days || []).map((day) => `
    <div class="day ${planClass(day)}">
      <strong>${escapeHtml(String(day.date).slice(-2))}</strong>
      <div>${escapeHtml(day.title || (day.is_training ? '训练' : '休息'))}</div>
    </div>
  `).join('');
}

async function loadStats() {
  const data = await api('/api/stats');
  $('stats').innerHTML = Object.entries(data).map(([key, value]) => (
    `<div><strong>${escapeHtml(key)}</strong>：${escapeHtml(value)}</div>`
  )).join('');
}

async function loadSettings() {
  const data = await api('/api/settings');
  const settings = data.settings || {};
  const reminders = data.reminders || [];
  $('settings').innerHTML = `
    <strong>settings</strong>
    ${Object.keys(settings).length ? Object.entries(settings).map(([k, v]) => `<div>${escapeHtml(k)} = ${escapeHtml(v)}</div>`).join('') : '<div>暂无设置</div>'}
    <strong>reminders</strong>
    ${reminders.length ? reminders.map((r) => `<div>#${r.id} ${escapeHtml(r.reminder_date)} ${escapeHtml(r.message)} enabled=${r.enabled}</div>`).join('') : '<div>暂无提醒</div>'}
  `;
}

async function loadLogs() {
  const data = await api('/api/logs');
  $('logs').innerHTML = (data.logs || []).slice(0, 20).map((log) => (
    `<div class="item"><strong>#${log.id}</strong> plan=${log.plan_id} ${escapeHtml(log.status)} ${escapeHtml(log.created_at || '')} ${escapeHtml(log.notes || '')}</div>`
  )).join('') || '<div class="item">暂无日志</div>';
}

async function refreshAll() {
  const results = await Promise.allSettled([
    loadHealth(), loadToday(), loadWeek(), loadMonth(), loadCalendar(), loadStats(), loadSettings(), loadLogs(),
  ]);
  const failed = results.filter((r) => r.status === 'rejected');
  if (failed.length) {
    console.error('部分模块加载失败', failed.map((r) => r.reason));
  }
}

async function postAction(action) {
  if (!todayPlan?.id) return;
  const notes = $('actionNotes').value || null;
  await api(`/api/logs/${action}`, {
    method: 'POST',
    body: JSON.stringify({ plan_id: todayPlan.id, notes }),
  });
  await Promise.all([loadStats(), loadLogs(), loadToday()]);
}

$('refreshAll').addEventListener('click', refreshAll);
$('completeBtn').addEventListener('click', () => postAction('complete').catch(console.error));
$('skipBtn').addEventListener('click', () => postAction('skip').catch(console.error));
$('postponeBtn').addEventListener('click', () => postAction('postpone').catch(console.error));
$('saveSetting').addEventListener('click', async () => {
  const key = $('settingKey').value.trim();
  if (!key) return alert('请输入 setting key');
  await api('/api/settings', {
    method: 'POST',
    body: JSON.stringify({ key, value: $('settingValue').value }),
  });
  await loadSettings();
});
$('testReminder').addEventListener('click', async () => {
  const data = await api('/api/reminders/test', {
    method: 'POST',
    body: JSON.stringify({ title: $('reminderTitle').value, message: $('reminderMessage').value }),
  });
  $('reminderResult').textContent = JSON.stringify({ note: 'mock/disabled，未真实发送', ...data }, null, 2);
});

refreshAll().catch((error) => console.error('初始化失败', error));
