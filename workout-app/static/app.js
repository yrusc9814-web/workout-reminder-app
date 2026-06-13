const apiCalls = new Set();
let todayPlan = null;
let latestLogByPlanId = new Map();

const $ = (id) => document.getElementById(id);
const today = new Date();
const isoToday = today.toISOString().slice(0, 10);
const year = today.getFullYear();
const month = today.getMonth() + 1;

const statusText = {
  training: '训练日',
  rest: '恢复日',
  completed: '已完成',
  done: '已完成',
  skipped: '已跳过',
  postponed: '已延期',
  sent: '已发送',
  not_configured: '未配置',
  failed: '失败',
  todo_unavailable_due_to_permission: '待办权限不可用',
};

const statLabels = {
  total_plans: '计划总数',
  training_days: '训练日',
  rest_days: '恢复日',
  completed: '已完成',
  skipped: '已跳过',
  postponed: '已延期',
  completion_rate: '完成率',
};

function recordApi(path) {
  apiCalls.add(path.replace(/([?&](date|year|month)=)[^&]+/g, '$1…'));
  $('apiCalls').textContent = Array.from(apiCalls).sort().join(' ｜ ');
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
    const detail = data?.detail || text || response.statusText;
    throw new Error(`请求失败（${response.status}）：${detail}`);
  }
  return data;
}

function escapeHtml(value) {
  return String(value ?? '').replace(/[&<>'"]/g, (ch) => ({
    '&': '&amp;', '<': '&lt;', '>': '&gt;', "'": '&#39;', '"': '&quot;'
  }[ch]));
}

function planBaseClass(day) {
  return day?.is_training ? 'training' : 'rest';
}

function latestStatusForPlan(day) {
  if (!day?.id) return planBaseClass(day);
  return latestLogByPlanId.get(day.id)?.status || planBaseClass(day);
}

function badge(status) {
  const text = statusText[status] || statusText[planBaseClass({ is_training: status === 'training' })] || status;
  return `<span class="status-badge ${escapeHtml(status)}">${escapeHtml(text)}</span>`;
}

function exerciseDetail(item) {
  if (item.duration_seconds) return `${item.sets || 1} 组 · 每组 ${item.duration_seconds} 秒`;
  return `${item.sets || '-'} 组 × ${item.reps || '-'} 次`;
}

function videoHost(url) {
  if (!url) return '';
  if (url.includes('bilibili.com')) return 'Bilibili';
  if (url.includes('b23.tv')) return 'B23';
  return '视频';
}

function renderPlan(day) {
  if (!day || !day.id) {
    return `<article class="plan-card rest">
      <div class="plan-top"><span class="status-badge rest">恢复日</span></div>
      <h3 class="plan-title">${escapeHtml(day?.date || isoToday)} 暂无训练安排</h3>
      <p class="plan-meta">今天不做正式训练，保持散步、拉伸或轻量活动即可。</p>
    </article>`;
  }
  const status = latestStatusForPlan(day);
  const items = (day.items || []).map((item, index) => `
    <li class="exercise-item">
      <span class="exercise-index">${String(index + 1).padStart(2, '0')}</span>
      <div class="exercise-main">
        <strong class="exercise-name">${escapeHtml(item.name)}</strong>
        <span class="exercise-instructions">${escapeHtml(item.instructions || '')}</span>
      </div>
      <span class="exercise-dose">${escapeHtml(exerciseDetail(item))}</span>
      ${item.video_url ? `<a class="exercise-video" href="${escapeHtml(item.video_url)}" target="_blank" rel="noopener noreferrer">打开${escapeHtml(videoHost(item.video_url))}</a>` : ''}
    </li>
  `).join('');
  return `<article class="plan-card ${planBaseClass(day)} ${status}">
    <div class="plan-top">
      ${badge(status)}
      <span class="pill neutral">${escapeHtml(day.date)}</span>
    </div>
    <h3 class="plan-title">${escapeHtml(day.title || (day.is_training ? '今日训练' : '恢复日'))}</h3>
    <div class="plan-meta">${escapeHtml(day.theme || day.type || '')}</div>
    ${day.notes ? `<p class="plan-meta">${escapeHtml(day.notes)}</p>` : ''}
    ${items ? `<ul class="exercise-list">${items}</ul>` : '<p class="plan-meta">暂无动作清单，按恢复日处理。</p>'}
  </article>`;
}

function renderWeekDay(day) {
  const status = latestStatusForPlan(day);
  const itemCount = (day.items || []).length;
  const actionPreview = day.is_training ? (day.items || []).slice(0, 3).map((item) => `
    <div class="week-action">
      <span>${escapeHtml(item.name)}</span>
      ${item.video_url ? `<a href="${escapeHtml(item.video_url)}" target="_blank" rel="noopener noreferrer">Bilibili</a>` : ''}
    </div>
  `).join('') : '';
  return `<article class="week-day ${planBaseClass(day)} ${status}">
    <div class="week-date">${escapeHtml(day.date)}</div>
    ${badge(status)}
    <div class="week-title">${escapeHtml(day.title || (day.is_training ? '训练日' : '恢复日'))}</div>
    <div class="week-items">${day.is_training ? `${itemCount} 个动作 · 视频已配齐` : '恢复 / 轻量活动'}</div>
    ${actionPreview ? `<div class="week-actions">${actionPreview}</div>` : ''}
  </article>`;
}

function renderMonthRow(day) {
  const status = latestStatusForPlan(day);
  return `<div class="month-row ${planBaseClass(day)} ${status}">
    <strong>${escapeHtml(day.date)}</strong>
    ${badge(status)}
    <span>${escapeHtml(day.title || (day.is_training ? '训练日' : '恢复日'))}</span>
  </div>`;
}

function renderCalendarDay(day) {
  const status = latestStatusForPlan(day);
  return `<div class="day ${planBaseClass(day)} ${status}">
    <span class="day-num">${escapeHtml(String(day.date).slice(-2))}</span>
    ${badge(status)}
    <span class="day-label">${escapeHtml(day.title || (day.is_training ? '训练' : '恢复'))}</span>
  </div>`;
}

function buildLatestLogMap(logs) {
  latestLogByPlanId = new Map();
  (logs || []).forEach((log) => {
    if (!log.plan_id || !log.status) return;
    if (!latestLogByPlanId.has(log.plan_id)) {
      latestLogByPlanId.set(log.plan_id, log);
    }
  });
}

async function loadHealth() {
  const target = $('health');
  target.className = 'status pending';
  target.textContent = '正在检测';
  try {
    await api('/api/health');
    target.className = 'status ok';
    target.textContent = '后端正常';
  } catch (error) {
    target.className = 'status error';
    target.textContent = `后端异常：${error.message}`;
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
  $('weekPlan').innerHTML = (data.days || []).map(renderWeekDay).join('') || '<div class="empty-state">暂无本周计划</div>';
}

async function loadMonth() {
  const data = await api(`/api/plans/month?year=${year}&month=${month}`);
  $('monthPlan').innerHTML = (data.days || []).map(renderMonthRow).join('') || '<div class="empty-state">暂无本月计划</div>';
}

async function loadCalendar() {
  const data = await api(`/api/calendar?year=${year}&month=${month}`);
  $('calendar').innerHTML = (data.days || []).map(renderCalendarDay).join('') || '<div class="empty-state">暂无月历</div>';
}

async function loadStats() {
  const data = await api('/api/stats');
  $('stats').innerHTML = Object.entries(data).map(([key, value]) => (
    `<div class="metric"><span>${escapeHtml(statLabels[key] || key)}</span><strong>${escapeHtml(value)}</strong></div>`
  )).join('') || '<div class="empty-state">暂无统计</div>';
}

async function loadSettings() {
  const data = await api('/api/settings');
  const settings = data.settings || {};
  const reminders = data.reminders || [];
  $('settings').innerHTML = `
    <strong>设置项</strong>
    ${Object.keys(settings).length ? Object.entries(settings).map(([k, v]) => `<div>${escapeHtml(k)} = ${escapeHtml(v)}</div>`).join('') : '<div>暂无设置</div>'}
    <strong>本地提醒</strong>
    ${reminders.length ? reminders.map((r) => `<div>#${r.id} ${escapeHtml(r.reminder_date)} ${escapeHtml(r.message)} 状态=${r.enabled ? '启用' : '停用'}</div>`).join('') : '<div>暂无提醒</div>'}
  `;
}

async function loadLogs() {
  const data = await api('/api/logs');
  const logs = data.logs || [];
  buildLatestLogMap(logs);
  $('logs').innerHTML = logs.slice(0, 20).map((log) => (
    `<div class="log-row ${escapeHtml(log.status || '')}">
      <strong>记录 #${log.id}</strong>
      <span>${badge(log.status || 'rest')}</span>
      <span>计划 ${log.plan_id} · ${escapeHtml(log.created_at || '')} ${escapeHtml(log.notes || '')}</span>
    </div>`
  )).join('') || '<div class="empty-state">暂无日志</div>';
}

async function refreshAll() {
  const firstResults = await Promise.allSettled([loadHealth(), loadLogs(), loadStats(), loadSettings()]);
  const secondResults = await Promise.allSettled([loadToday(), loadWeek(), loadMonth(), loadCalendar()]);
  const failed = [...firstResults, ...secondResults].filter((r) => r.status === 'rejected');
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
  await Promise.all([loadLogs(), loadStats()]);
  await Promise.all([loadToday(), loadWeek(), loadMonth(), loadCalendar()]);
}

$('refreshAll').addEventListener('click', refreshAll);
$('completeBtn').addEventListener('click', () => postAction('complete').catch(console.error));
$('skipBtn').addEventListener('click', () => postAction('skip').catch(console.error));
$('postponeBtn').addEventListener('click', () => postAction('postpone').catch(console.error));
$('saveSetting').addEventListener('click', async () => {
  const key = $('settingKey').value.trim();
  if (!key) return alert('请输入设置项名称');
  await api('/api/settings', {
    method: 'POST',
    body: JSON.stringify({ key, value: $('settingValue').value }),
  });
  await loadSettings();
});
$('testReminder').addEventListener('click', async () => {
  if (!todayPlan?.id || !todayPlan?.is_training) {
    $('reminderResult').textContent = '今天不是训练日或没有计划，不创建钉钉提醒。';
    return;
  }
  const [reminder, todo] = await Promise.all([
    api('/api/reminders/dingtalk/send', {
      method: 'POST',
      body: JSON.stringify({ plan_id: todayPlan.id, title: $('reminderTitle').value, message: $('reminderMessage').value }),
    }),
    api('/api/todos/dingtalk/create', {
      method: 'POST',
      body: JSON.stringify({ plan_id: todayPlan.id }),
    }),
  ]);
  $('reminderResult').textContent = JSON.stringify({ 钉钉群消息: reminder, 钉钉个人待办: todo }, null, 2);
});

refreshAll().catch((error) => console.error('初始化失败', error));
