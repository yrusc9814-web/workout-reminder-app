const STORAGE_KEY = 'workout_planner_data_v1';
const BACKEND_ENDPOINT_CONTRACT = [
  '/api/health',
  '/api/ai/health',
  '/api/ai/import-plan',
  '/api/ai/suggest-bilibili-video',
  '/api/ai/analyze',
  '/api/ai/feedback',
  '/api/today',
  '/api/plans',
  '/api/plans/generate',
  '/api/session/start',
  '/api/session/update',
  '/api/session/complete',
  '/api/plans/week?date=${isoToday}',
  '/api/plans/month?year=${year}&month=${month}',
  '/api/calendar?year=${year}&month=${month}',
  '/api/stats',
  '/api/settings',
  '/api/logs',
  '/api/logs/${action}',
  '/api/reminders/dingtalk/send',
  '/api/todos/dingtalk/create',
  '/api/exercises',
  '/api/exercises/${exercise_id}',
  '/api/templates',
  '/api/templates/${template_id}',
  '/api/training/complete',
  '/api/plans/${plan_id}',
];const $ = (id) => document.getElementById(id);
const $$ = (selector, root = document) => Array.from(root.querySelectorAll(selector));
const today = new Date();
const isoToday = today.toISOString().slice(0, 10);
let currentPage = 'dashboard';
let visibleMonth = new Date(today.getFullYear(), today.getMonth(), 1);
let startupState = 'loading';
let state = loadData();
let session = null;

function escapeHtml(value) {
  return String(value ?? '').replace(/[&<>'"]/g, (ch) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', "'": '&#39;', '"': '&quot;' }[ch]));
}

function uid(prefix) {
  return `${prefix}_${Date.now().toString(36)}_${Math.random().toString(36).slice(2, 7)}`;
}

function addDays(date, days) {
  const next = new Date(date);
  next.setDate(next.getDate() + days);
  return next;
}

function toIso(date) {
  return date.toISOString().slice(0, 10);
}

function defaultData() {
  const monday = addDays(today, -today.getDay() + 1);
  const exerciseIds = ['pelvic_tilt', 'dead_bug', 'glute_bridge', 'bird_dog', 'plank'];
  const schedule = {};
  for (let i = 0; i < 7; i += 1) {
    const day = addDays(monday, i);
    const iso = toIso(day);
    if ([0, 2, 4].includes(day.getDay())) {
      schedule[iso] = { type: 'training', templateId: 'core_stability', status: iso === isoToday ? 'pending' : 'pending', note: '重点保持腰背稳定，动作慢一点。' };
    } else {
      schedule[iso] = { type: 'rest', status: 'pending', note: '散步 20 分钟，拉伸 10 分钟。' };
    }
  }
  schedule[isoToday] = schedule[isoToday] || { type: 'training', templateId: 'core_stability', status: 'pending', note: '今日补充核心控制训练。' };
  if (schedule[isoToday].type === 'training') schedule[isoToday].templateId = 'core_stability';
  return {
    version: '1.0',
    updatedAt: new Date().toISOString(),
    exercises: [
      { id: 'pelvic_tilt', name: '仰卧骨盆后倾', category: '核心控制', bodyParts: ['核心', '腰腹'], difficulty: '低', defaultSets: 3, defaultReps: '12次', durationSeconds: null, notes: '适合核心激活和骨盆控制。', tips: ['仰卧屈膝，双脚踩稳', '腰背轻轻贴向地面', '动作慢，不要憋气'], videos: [{ id: 'video_pelvic_tilt_001', title: '仰卧骨盆后倾教学', platform: 'bilibili', url: 'https://www.bilibili.com/video/BV1X625B5EWd/', isDefault: true, remark: '适合初学者' }] },
      { id: 'dead_bug', name: '死虫 Dead Bug', category: '核心控制', bodyParts: ['核心', '腰腹'], difficulty: '低', defaultSets: 3, defaultReps: '10次', durationSeconds: null, notes: '保持腰背贴地，动作慢一点。', tips: ['腰背贴地', '手脚交替伸展', '动作放慢，不要借力', '保持核心收紧，均匀呼吸'], videos: [{ id: 'video_dead_bug_001', title: '死虫核心训练教学', platform: 'bilibili', url: 'https://www.bilibili.com/video/BV1Bu411V7rW/', isDefault: true, remark: '核心控制入门' }, { id: 'video_dead_bug_002', title: '死虫动作细节讲解', platform: 'bilibili', url: 'https://www.bilibili.com/video/BV1y5411L7Yx/', isDefault: false, remark: '备用视频' }] },
      { id: 'glute_bridge', name: '臀桥', category: '髋部稳定', bodyParts: ['臀部', '核心'], difficulty: '低', defaultSets: 3, defaultReps: '15次', durationSeconds: null, notes: '发力时收紧臀部，避免腰部代偿。', tips: ['双脚踩稳', '发力时收紧臀部', '不要用腰顶起来'], videos: [{ id: 'video_glute_bridge_001', title: '臀桥标准动作教学', platform: 'bilibili', url: 'https://www.bilibili.com/video/BV1Jg4y1z7Nm/', isDefault: true, remark: '臀部激活' }] },
      { id: 'bird_dog', name: 'Bird Dog', category: '核心控制', bodyParts: ['核心', '背部'], difficulty: '低', defaultSets: 3, defaultReps: '10次/侧', durationSeconds: null, notes: '保持骨盆稳定，手脚慢慢伸展。', tips: ['四点支撑', '不要塌腰', '左右交替伸展'], videos: [{ id: 'video_bird_dog_001', title: 'Bird Dog 动作教学', platform: 'bilibili', url: 'https://www.bilibili.com/video/BV1No4y1h7NH/', isDefault: true, remark: '核心稳定' }] },
      { id: 'plank', name: '平板支撑', category: '核心控制', bodyParts: ['核心', '肩部'], difficulty: '中', defaultSets: 3, defaultReps: null, durationSeconds: 30, notes: '计时型动作，保持身体一条直线。', tips: ['肘在肩下', '核心收紧', '不憋气'], videos: [{ id: 'video_plank_001', title: '平板支撑入门', platform: 'bilibili', url: 'https://www.bilibili.com/video/BV1Rv4y1d7XM/', isDefault: true, remark: '计时型动作' }] },
    ],
    templates: [{ id: 'core_stability', name: '核心控制 + 髋部稳定训练', description: '专注核心稳定与髋部控制，适合日常训练与康复巩固。', exerciseIds, difficulty: '低强度', estimatedMinutes: 35 }],
    schedule,
    logs: [],
  };
}

function normalizeData(data) {
  const fallback = defaultData();
  return {
    version: data?.version || '1.0',
    updatedAt: data?.updatedAt || new Date().toISOString(),
    exercises: Array.isArray(data?.exercises) ? data.exercises : fallback.exercises,
    templates: Array.isArray(data?.templates) ? data.templates : fallback.templates,
    schedule: data?.schedule && typeof data.schedule === 'object' ? data.schedule : fallback.schedule,
    logs: Array.isArray(data?.logs) ? data.logs : [],
  };
}

function loadData() {
  const fallback = defaultData();
  return normalizeData(fallback);
}

function saveData() {
  state.updatedAt = new Date().toISOString();
  updateStorageUsage();
}

function exerciseById(id) { return state.exercises.find((item) => item.id === id); }
function templateById(id) { return state.templates.find((item) => item.id === id); }
function defaultVideo(exercise) { return exercise?.videos?.find((video) => video.isDefault) || exercise?.videos?.[0] || null; }
function doseText(exercise) { return exercise?.durationSeconds ? `${exercise.defaultSets} 组 × ${exercise.durationSeconds} 秒` : `${exercise?.defaultSets ?? '-'} 组 × ${exercise?.defaultReps ?? '-'} `; }
function planFor(date) { return state.schedule[date] || null; }
function templateExercises(template) { return (template?.exerciseIds || []).map(exerciseById).filter(Boolean); }
function todayPlan() { return planFor(isoToday); }
function todayTemplate() { const plan = todayPlan(); return plan?.type === 'training' ? templateById(plan.templateId) : null; }
function statusText(status) { return { pending: '待开始', done: '已完成', skipped: '已跳过', partial: '未完成', rest: '休息日' }[status] || status || '待开始'; }

function validateBilibiliUrl(url) {
  if (!url || typeof url !== 'string') return { valid: false, error: '请输入视频链接' };
  const trimmed = url.trim();
  if (/^https?:\/\/(www\.)?bilibili\.com\/video\//.test(trimmed)) return { valid: true, error: null };
  if (/^https?:\/\/b23\.tv\//.test(trimmed)) return { valid: true, error: null };
  if (/^https?:\/\/(www\.)?(youtube\.com|youtu\.be)\//.test(trimmed)) return { valid: false, error: '不支持 YouTube 链接，请使用 Bilibili 链接' };
  return { valid: false, error: '仅支持 Bilibili 链接（bilibili.com/video/ 或 b23.tv）' };
}

function updateStorageUsage() {
  const payload = JSON.stringify(state || {});
  const bytes = new Blob([payload]).size;
  $('storageUsage').textContent = `API 缓存 ${(bytes / 1024).toFixed(1)} KB`;
}

async function loadHealth() {
  startupState = 'loading';
  try {
    const [healthResponse, todayResponse] = await Promise.all([
      fetch('/api/health'),
      fetch('/api/today'),
    ]);
    if (!healthResponse.ok) throw new Error(String(healthResponse.status));
    if (!todayResponse.ok) throw new Error(String(todayResponse.status));
    const todayPayload = await todayResponse.json();
    const nextState = defaultData();
    if (todayPayload?.date) {
      nextState.schedule[todayPayload.date] = {
        type: todayPayload.is_training ? 'training' : 'rest',
        templateId: todayPayload.is_training ? 'core_stability' : undefined,
        status: 'pending',
        note: todayPayload.notes || '',
      };
    }
    state = normalizeData(nextState);
    startupState = 'api_ready';
    $('health').className = 'status-pill ok';
    $('health').textContent = '后端正常';
    startupState = 'ready';
  } catch (error) {
    startupState = 'ready';
    $('health').className = 'status-pill warn';
    $('health').textContent = '后端未就绪';
  }
  updateStorageUsage();
}

function updateApp(reason, options = {}) {
  const page = options.page || currentPage;
  if (page === 'trainingSession') {
    renderTrainingSession();
  } else if (page === 'dashboard') {
    renderDashboard();
  } else {
    render();
  }
}

function renderDashboard() {
  renderTodayCard('dashboardToday');
  renderStats();
  renderTodayVideos();
  renderWeek();
  renderCalendar('monthCalendar');
  renderExercises();
  renderTemplates();
}

function dispatchSession(action, payload) {
  if (!session && action !== 'END_SESSION') return;
  switch (action) {
    case 'COMPLETE_SET': completeSet(payload); break;
    case 'NEXT_EXERCISE': nextExercise(); break;
    case 'PREV_EXERCISE': prevExercise(); break;
    case 'SKIP_EXERCISE': skipExercise(); break;
    case 'END_SESSION': finishTraining('partial'); break;
  }
}

function switchPage(page) {
  currentPage = page;
  $$('.nav-item').forEach((item) => item.classList.toggle('active', item.dataset.page === page));
  $$('.page').forEach((panel) => panel.classList.toggle('active', panel.dataset.pagePanel === page));
  if (page === 'trainingSession' && !session) startTrainingSession();
  render();
}

function renderTodayCard(targetId, full = false) {
  const plan = todayPlan();
  const template = todayTemplate();
  const exercises = templateExercises(template);
  const target = $(targetId);
  if (!plan) {
    target.innerHTML = `<p class="eyebrow">今日重点</p><h2>今日暂无计划</h2><p>你还没有为今天安排训练或休息。</p><div class="button-row"><button class="btn primary" data-edit-plan="${isoToday}" type="button">编辑今日计划</button><button class="btn disabled" data-ai-disabled type="button">生成本周计划 · 第二阶段开放</button></div>`;
    return;
  }
  if (plan.type === 'rest') {
    target.innerHTML = `<p class="eyebrow">今日重点</p><h2>今天是休息日</h2><p>${escapeHtml(plan.note || '建议散步 20 分钟，拉伸 10 分钟，保持恢复。')}</p><div class="rest-suggestions"><span>散步 20 分钟</span><span>拉伸 10 分钟</span><span>保持恢复</span></div><button class="btn secondary" data-page-link="dashboard" type="button">返回仪表盘</button>`;
    return;
  }
  const visible = full ? exercises : exercises.slice(0, 3);
  target.innerHTML = `<p class="eyebrow">今日训练</p><h2>${escapeHtml(template?.name || '当前计划引用的训练模板不存在')}</h2><div class="hero-meta"><span>训练时长：${template?.estimatedMinutes || 35} 分钟</span><span>难度：${escapeHtml(template?.difficulty || '低强度')}</span><span>状态：${statusText(plan.status)}</span><span>完成进度：${plan.status === 'done' ? '100%' : '0%'}</span></div><ol class="mini-actions">${visible.map((exercise) => `<li><strong>${escapeHtml(exercise.name)}</strong><span>${escapeHtml(doseText(exercise))}</span>${defaultVideo(exercise) ? `<a href="${escapeHtml(defaultVideo(exercise).url)}" target="_blank" rel="noopener noreferrer">B站直达</a>` : '<button data-add-video="'+escapeHtml(exercise.id)+'" type="button">添加视频</button>'}</li>`).join('')}</ol>${exercises.length > 3 && !full ? '<button class="text-btn" data-expand-today type="button">展开全部动作</button>' : ''}<div class="button-row"><button class="btn secondary" data-show-detail type="button">查看动作详情</button><button class="btn primary" data-start-training type="button">开始训练</button></div>`;
}

function renderStats() {
  const monthKey = `${visibleMonth.getFullYear()}-${String(visibleMonth.getMonth() + 1).padStart(2, '0')}`;
  const entries = Object.entries(state.schedule).filter(([date]) => date.startsWith(monthKey));
  const training = entries.filter(([, plan]) => plan.type === 'training');
  const rest = entries.filter(([, plan]) => plan.type === 'rest');
  const done = training.filter(([, plan]) => plan.status === 'done');
  const rate = training.length ? Math.round((done.length / training.length) * 100) : 0;
  $('monthLabel').textContent = monthKey;
  $('stats').innerHTML = [['训练天数', `${training.length} 天`], ['休息天数', `${rest.length} 天`], ['完成率', `${rate}%`]].map(([k, v]) => `<div class="metric"><span>${k}</span><strong>${v}</strong></div>`).join('');
  $('monthStats').innerHTML = $('stats').innerHTML;
}

function renderTodayVideos() {
  const template = todayTemplate();
  const exercises = templateExercises(template);
  const content = exercises.length ? exercises.map((exercise) => {
    const video = defaultVideo(exercise);
    return `<article class="video-row"><div><strong>${escapeHtml(exercise.name)}</strong><span>${video ? escapeHtml(video.url) : '暂无视频链接'}</span></div>${video ? `<a class="btn mini" href="${escapeHtml(video.url)}" target="_blank" rel="noopener noreferrer">打开视频</a>` : `<button class="btn mini" data-add-video="${escapeHtml(exercise.id)}" type="button">添加视频</button>`}</article>`;
  }).join('') : '<div class="empty-state">今天是休息日或暂无计划，暂无相关视频</div>';
  $('todayVideos').innerHTML = content;
  $('todayVideoDetail').innerHTML = content;
}

function renderWeek() {
  const monday = addDays(today, -today.getDay() + 1);
  const days = Array.from({ length: 7 }, (_, i) => toIso(addDays(monday, i)));
  const html = days.map((date) => {
    const plan = planFor(date) || { type: 'rest', status: 'pending', note: '休息恢复' };
    const template = templateById(plan.templateId);
    const isToday = date === isoToday;
    return `<article class="week-card ${plan.type} ${plan.status === 'done' ? 'completed' : ''} ${isToday ? 'today' : ''}" data-edit-plan="${date}"><span>${date}</span><strong>${isToday ? '今日 · ' : ''}${plan.type === 'training' ? escapeHtml(template?.name || '模板丢失') : '休息恢复'}</strong><em>${plan.type === 'training' ? '训练' : '休息'} · ${statusText(plan.status)}</em></article>`;
  }).join('');
  $('weekRoute').innerHTML = html;
  $('weekPlan').innerHTML = html;
}

function renderCalendar(targetId) {
  const year = visibleMonth.getFullYear();
  const month = visibleMonth.getMonth();
  const first = new Date(year, month, 1);
  const startOffset = (first.getDay() + 6) % 7;
  const daysInMonth = new Date(year, month + 1, 0).getDate();
  const cells = ['周一', '周二', '周三', '周四', '周五', '周六', '周日'].map((d) => `<b>${d}</b>`);
  for (let i = 0; i < startOffset; i += 1) cells.push('<div class="calendar-empty"></div>');
  for (let day = 1; day <= daysInMonth; day += 1) {
    const date = `${year}-${String(month + 1).padStart(2, '0')}-${String(day).padStart(2, '0')}`;
    const plan = planFor(date) || { type: 'rest', status: 'pending' };
    const template = templateById(plan.templateId);
    const extraClass = plan.status === 'done' ? ' completed' : '';
    cells.push(`<button class="calendar-day ${plan.type}${extraClass} ${date === isoToday ? 'today' : ''}" data-edit-plan="${date}" type="button"><span>${day}</span><i>${plan.type === 'training' ? escapeHtml(template?.name || '训练') : '休息'}</i><em>${statusText(plan.status)}</em></button>`);
  }
  $(targetId).innerHTML = cells.join('');
}

function renderExercises() {
  const keyword = $('exerciseSearch')?.value.trim().toLowerCase() || '';
  const category = $('exerciseFilter')?.value || 'all';
  const categories = Array.from(new Set(state.exercises.map((item) => item.category))).sort();
  $('exerciseFilter').innerHTML = '<option value="all">全部</option>' + categories.map((item) => `<option value="${escapeHtml(item)}" ${category === item ? 'selected' : ''}>${escapeHtml(item)}</option>`).join('');
  const items = state.exercises.filter((exercise) => (category === 'all' || exercise.category === category) && (!keyword || exercise.name.toLowerCase().includes(keyword) || exercise.category.toLowerCase().includes(keyword)));
  $('exerciseList').innerHTML = items.map((exercise) => {
    const video = defaultVideo(exercise);
    return `<article class="data-card"><div><h3>${escapeHtml(exercise.name)}</h3><p>${escapeHtml(exercise.category)} / ${escapeHtml((exercise.bodyParts || []).join('、'))} / ${escapeHtml(exercise.difficulty)}</p><p>默认组次：${escapeHtml(doseText(exercise))}</p><p>默认 B站视频：${video ? escapeHtml(video.title) : '暂无视频链接'}</p></div><div class="card-actions">${video ? `<a class="btn mini" href="${escapeHtml(video.url)}" target="_blank" rel="noopener noreferrer">打开Bilibili</a>` : ''}<button class="btn mini" data-edit-exercise="${escapeHtml(exercise.id)}" type="button">编辑</button><button class="btn mini" data-add-video="${escapeHtml(exercise.id)}" type="button">添加视频</button><button class="btn mini secondary" data-ai-search-video="${escapeHtml(exercise.id)}" type="button">AI搜索</button><button class="btn danger mini" data-delete-exercise="${escapeHtml(exercise.id)}" type="button">删除</button></div></article>`;
  }).join('') || '<div class="empty-state">动作库为空，点击新增动作开始维护。</div>';
}

function renderTemplates() {
  $('templateList').innerHTML = state.templates.map((template) => {
    const exercises = templateExercises(template);
    return `<article class="template-card"><h3>${escapeHtml(template.name)}</h3><p>${escapeHtml(template.description || '')}</p><div class="hero-meta"><span>${exercises.length} 个动作</span><span>约 ${template.estimatedMinutes || 30} 分钟</span><span>${escapeHtml(template.difficulty || '低强度')}</span></div><ol>${exercises.map((exercise) => `<li>${escapeHtml(exercise.name)} · ${escapeHtml(doseText(exercise))}</li>`).join('')}</ol><div class="card-actions"><button class="btn mini" data-edit-template="${escapeHtml(template.id)}" type="button">编辑模板</button><button class="btn danger mini" data-delete-template="${escapeHtml(template.id)}" type="button">删除模板</button></div></article>`;
  }).join('') || '<div class="empty-state">模板为空，请新建训练模板。</div>';
}

function renderVideoLinks() {
  $('videoLinkList').innerHTML = state.exercises.map((exercise) => {
    const videos = exercise.videos || [];
    return `<article class="video-group"><h3>${escapeHtml(exercise.name)}</h3>${videos.length ? videos.map((video) => `<div class="video-row"><div><strong>${escapeHtml(video.title)} ${video.isDefault ? '· 默认' : ''}</strong><span>${escapeHtml(video.url)}</span></div><div><button class="btn mini" data-default-video="${escapeHtml(exercise.id)}::${escapeHtml(video.id)}" type="button">设为默认</button><a class="btn mini" href="${escapeHtml(video.url)}" target="_blank" rel="noopener noreferrer">打开Bilibili</a></div></div>`).join('') : '<p>暂无视频链接</p>'}<button class="btn mini" data-add-video="${escapeHtml(exercise.id)}" type="button">添加B站视频</button><button class="btn mini secondary" data-ai-search-video="${escapeHtml(exercise.id)}" type="button">AI搜索</button></article>`;
  }).join('');
}

function renderDashboardManagement() {
  const target = $('dashboardManagement');
  if (!target) return;
  target.innerHTML = `<article class="manage-card" data-page-link="exerciseLibrary"><div class="manage-icon">动</div><div><h3>动作库管理</h3><p>新增、编辑、删除训练动作，管理 Bilibili 视频链接</p><span class="manage-stat">${state.exercises.length} 个动作</span></div></article><article class="manage-card" data-page-link="templateManager"><div class="manage-icon">模</div><div><h3>训练模板管理</h3><p>创建、编辑、删除训练模板，组合动作序列</p><span class="manage-stat">${state.templates.length} 个模板</span></div></article><article class="manage-card" data-page-link="week"><div class="manage-icon">计</div><div><h3>训练计划管理</h3><p>编辑每日计划类型、模板和状态</p><span class="manage-stat">${Object.keys(state.schedule).length} 天计划</span></div></article><article class="manage-card" data-page-link="settings"><div class="manage-icon">导</div><div><h3>导入 / 导出数据</h3><p>JSON 导入导出、AI 辅助导入训练计划</p></div></article>`;
}

function renderSettings() {
  $('jsonBox').value = $('jsonBox').value || '';
  $('importPreview').innerHTML = `<strong>本地数据状态</strong><p>动作 ${state.exercises.length} 个，模板 ${state.templates.length} 个，计划 ${Object.keys(state.schedule).length} 天，训练记录 ${state.logs.length} 条。</p>`;
}

function renderTrainingSession() {
  const target = $('trainingSession');
  if (!target) return;
  if (!session) {
    target.innerHTML = '<div class="empty-state">尚未开始训练。</div>';
    return;
  }
  const template = templateById(session.templateId);
  const exercises = templateExercises(template);
  const exercise = exercises[session.currentExerciseIndex];
  const video = defaultVideo(exercise);
  if (!exercise) {
    target.innerHTML = '<div class="empty-state">当前计划引用的动作已不存在。</div>';
    return;
  }
  const progress = Math.round((session.currentExerciseIndex / Math.max(exercises.length, 1)) * 100);
  target.innerHTML = `
    <div class="session-head">
      <button class="ghost-btn" data-page-link="dashboard" type="button">返回</button>
      <div>
        <h2>${escapeHtml(template.name)}</h2>
        <p>本地训练模式 · 第 ${session.currentExerciseIndex + 1} / ${exercises.length} 个动作 · 状态：${escapeHtml(statusText(session.status))}</p>
      </div>
      <button class="btn danger" data-end-session type="button">结束训练</button>
    </div>
    <div class="progress-track">
      <div class="progress-fill" style="width:${progress}%"></div>
      <span class="progress-label">${progress}%</span>
    </div>
    <div class="session-grid">
      <article class="current-exercise" id="currentExerciseCard">
        <p class="eyebrow">当前动作卡片</p>
        <h3>${escapeHtml(exercise.name)}</h3>
        <p>目标：${escapeHtml(exercise.category)} · ${escapeHtml(doseText(exercise))} · 当前第 ${session.currentSetIndex + 1} / ${exercise.defaultSets} 组</p>
        <ul>${(exercise.tips || []).map((tip) => `<li>${escapeHtml(tip)}</li>`).join('')}</ul>
        <div class="button-row">
          <button class="btn primary" id="completeExerciseButton" data-complete-set type="button">完成按钮</button>
          <button class="btn secondary" data-rest type="button">进入休息</button>
          <button class="btn warning" data-skip-exercise type="button">跳过动作</button>
        </div>
        <div class="set-badges">${Array.from({ length: exercise.defaultSets }, (_, i) => `<span class="set-badge ${i < session.currentSetIndex ? 'set-complete' : i === session.currentSetIndex ? 'set-current' : ''}">第${i + 1}组</span>`).join('')}</div>
      </article>
      <aside class="video-panel">
        <p class="eyebrow">Bilibili 视频 iframe</p>
        ${video ? `<h3>${escapeHtml(video.title)}</h3><p>${escapeHtml(video.remark || '')}</p><a class="btn primary" href="${escapeHtml(video.url)}" target="_blank" rel="noopener noreferrer">打开Bilibili视频</a><button class="btn secondary" data-change-video="${escapeHtml(exercise.id)}" type="button">更换视频</button>` : `<h3>当前动作暂无视频</h3><button class="btn secondary" data-add-video="${escapeHtml(exercise.id)}" type="button">添加视频</button>`}
        <iframe id="bilibiliPlayer" title="Bilibili 视频 iframe" src="about:blank"></iframe>
      </aside>
    </div>
    <div class="session-actions">
      <button class="ghost-btn" data-prev-exercise type="button" ${session.currentExerciseIndex === 0 ? 'disabled' : ''}>上一个动作</button>
      <button class="ghost-btn" id="autoNextExercise" data-next-exercise type="button" ${session.currentExerciseIndex >= exercises.length - 1 ? 'disabled' : ''}>自动切换下一个动作</button>
      <button class="ghost-btn" data-pause-session type="button">${session.status === 'paused' ? '继续训练' : '暂停训练'}</button>
    </div>
    <div id="sessionProgressBar" role="progressbar" aria-label="训练进度" aria-valuemin="0" aria-valuemax="100" aria-valuenow="${progress}"></div>
    <div class="session-summary">
      <strong>完成摘要</strong>
      <span>已完成动作 ${session.completed.length} 个 · 已跳过动作 ${session.skipped.length} 个 · totalSetsDone ${session.totalSetsDone || 0}</span>
    </div>
  `;
}

function render() {
  if (currentPage === 'trainingSession') { renderTrainingSession(); return; }
  updateStorageUsage();
  if ($('health')) $('health').dataset.startupState = startupState;
  renderTodayCard('dashboardToday');
  renderTodayCard('todayDetail', true);
  renderDashboardManagement();
  renderStats();
  renderTodayVideos();
  renderWeek();
  renderCalendar('monthCalendar');
  renderCalendar('monthCalendarPage');
  renderExercises();
  renderTemplates();
  renderVideoLinks();
  renderSettings();
  renderTrainingSession();
}

function openPlanDialog(date) {
  const plan = planFor(date) || { type: 'rest', status: 'pending', note: '' };
  $('planForm').innerHTML = `<h2>编辑每日计划</h2><label>日期<input name="date" value="${escapeHtml(date)}" readonly /></label><label>类型<select name="type"><option value="training" ${plan.type === 'training' ? 'selected' : ''}>训练日</option><option value="rest" ${plan.type === 'rest' ? 'selected' : ''}>休息日</option></select></label><label>训练模板<select name="templateId"><option value="">请选择</option>${state.templates.map((template) => `<option value="${escapeHtml(template.id)}" ${plan.templateId === template.id ? 'selected' : ''}>${escapeHtml(template.name)}</option>`).join('')}</select></label><label>状态<select name="status"><option value="pending" ${plan.status === 'pending' ? 'selected' : ''}>未开始</option><option value="done" ${plan.status === 'done' ? 'selected' : ''}>已完成</option><option value="skipped" ${plan.status === 'skipped' ? 'selected' : ''}>已跳过</option></select></label><label>备注<textarea name="note">${escapeHtml(plan.note || '')}</textarea></label><div class="modal-actions"><button class="btn secondary" value="cancel" type="button" data-close-modal>取消</button><button class="btn primary" value="save" type="submit">保存</button></div>`;
  $('planDialog').showModal();
}

function openExerciseDialog(id = null) {
  const exercise = id ? exerciseById(id) : { id: '', name: '', category: '核心控制', bodyParts: ['核心'], difficulty: '低', defaultSets: 3, defaultReps: '10次', durationSeconds: null, notes: '', tips: [], videos: [] };
  $('exerciseForm').innerHTML = `<h2>${id ? '编辑动作' : '新增动作'}</h2><label>动作 ID<input name="id" value="${escapeHtml(exercise.id)}" ${id ? 'readonly' : ''} required pattern="[A-Za-z0-9_]+" /></label><label>动作名称<input name="name" value="${escapeHtml(exercise.name)}" required /></label><label>分类<input name="category" value="${escapeHtml(exercise.category)}" required /></label><label>训练部位<input name="bodyParts" value="${escapeHtml((exercise.bodyParts || []).join('、'))}" /></label><label>难度<select name="difficulty"><option ${exercise.difficulty === '低' ? 'selected' : ''}>低</option><option ${exercise.difficulty === '中' ? 'selected' : ''}>中</option><option ${exercise.difficulty === '高' ? 'selected' : ''}>高</option></select></label><label>默认组数<input name="defaultSets" type="number" min="1" value="${escapeHtml(exercise.defaultSets)}" /></label><label>动作类型<select name="motionType"><option value="reps" ${exercise.durationSeconds ? '' : 'selected'}>次数型</option><option value="duration" ${exercise.durationSeconds ? 'selected' : ''}>计时型</option></select></label><label>默认次数<input name="defaultReps" value="${escapeHtml(exercise.defaultReps || '')}" /></label><label>默认时长秒数<input name="durationSeconds" type="number" min="1" value="${escapeHtml(exercise.durationSeconds || '')}" /></label><label>动作备注<textarea name="notes">${escapeHtml(exercise.notes || '')}</textarea></label><label>动作要点（每行一条）<textarea name="tips">${escapeHtml((exercise.tips || []).join('\n'))}</textarea></label><div class="modal-actions"><button class="btn secondary" type="button" data-close-modal>取消</button><button class="btn primary" type="submit">保存</button></div>`;

  $('exerciseDialog').showModal();
}

function openTemplateDialog(id = null) {
  const template = id ? templateById(id) : { id: '', name: '', description: '', exerciseIds: [], difficulty: '低强度', estimatedMinutes: 30 };
  $('templateForm').innerHTML = `<h2>${id ? '编辑模板' : '新建模板'}</h2><label>模板 ID<input name="id" value="${escapeHtml(template.id)}" ${id ? 'readonly' : ''} required pattern="[A-Za-z0-9_]+" /></label><label>模板名称<input name="name" value="${escapeHtml(template.name)}" required /></label><label>模板描述<textarea name="description">${escapeHtml(template.description || '')}</textarea></label><label>预计分钟<input name="estimatedMinutes" type="number" min="1" value="${escapeHtml(template.estimatedMinutes || 30)}" /></label><label>难度<input name="difficulty" value="${escapeHtml(template.difficulty || '低强度')}" /></label><div class="checkbox-list">${state.exercises.map((exercise) => `<label><input type="checkbox" name="exerciseIds" value="${escapeHtml(exercise.id)}" ${template.exerciseIds?.includes(exercise.id) ? 'checked' : ''}/> ${escapeHtml(exercise.name)}</label>`).join('')}</div><div class="modal-actions"><button class="btn secondary" type="button" data-close-modal>取消</button><button class="btn primary" type="submit">保存</button></div>`;
  $('templateDialog').dataset.editingId = id || '';
  $('templateDialog').showModal();
}

function openVideoDialog(exerciseId) {
  const exercise = exerciseById(exerciseId);
  $('videoForm').innerHTML = `<h2>添加 / 编辑视频</h2><p>${escapeHtml(exercise?.name || '')}</p><label>视频 ID<input name="id" value="${escapeHtml(uid('video'))}" required /></label><label>视频标题<input name="title" required /></label><label>B站链接<input name="url" required /></label><label>备注<input name="remark" /></label><label class="inline"><input name="isDefault" type="checkbox" checked /> 设为默认</label><div class="modal-actions"><button class="btn secondary" type="button" data-close-modal>取消</button><button class="btn primary" type="submit">保存</button></div>`;
  $('videoDialog').dataset.exerciseId = exerciseId;
  $('videoDialog').showModal();
}

function startTrainingSession() {
  const plan = todayPlan();
  const template = todayTemplate();
  if (!plan) return alert('今日暂无计划，请先编辑今日计划。');
  if (plan.type === 'rest') return alert('今天是休息日，不进入训练执行页。');
  if (!template) return alert('当前计划引用的训练模板不存在，请重新选择模板。');
  session = { templateId: template.id, currentExerciseIndex: 0, currentSetIndex: 0, status: 'in_progress', startedAt: new Date().toISOString(), completed: [], skipped: [], totalSetsDone: 0 };
  currentPage = 'trainingSession';
  switchPage('trainingSession');
}

function finishTraining(status = 'done') {
  const plan = todayPlan();
  if (plan) plan.status = status;
  const summary = {
    templateName: session?.templateId ? (templateById(session.templateId)?.name || '未知模板') : '无模板',
    completed: session?.completed || [],
    skipped: session?.skipped || [],
    totalSetsDone: session?.totalSetsDone || 0,
    status,
    startedAt: session?.startedAt,
  };
  state.logs.unshift({ id: uid('log'), date: isoToday, templateId: session?.templateId, startedAt: session?.startedAt, endedAt: new Date().toISOString(), completed: session?.completed || [], skipped: session?.skipped || [], status });
  fetch('/api/training/complete', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ date: isoToday, template_id: session?.templateId ? session.templateId : undefined, completed: session?.completed || [], skipped: session?.skipped || [], status }),
  }).catch(() => {});
  session = null;
  saveData();
  window.__lastTrainingSummary = summary;
  render();
  switchPage('dashboard');
  const summaryEl = document.getElementById('trainingSummaryBanner');
  if (summaryEl) {
    summaryEl.classList.remove('is-hidden');
    summaryEl.classList.add('is-visible');
    summaryEl.innerHTML = `<div class="summary-banner-inner session-summary"><strong>训练完成摘要</strong><span>模板：${escapeHtml(summary.templateName)} | 完成动作：${summary.completed.length} 个 | 跳过动作：${summary.skipped.length} 个 | 完成组数：${summary.totalSetsDone} | 状态：${statusText(summary.status)}</span><button id="dismissSummaryBanner" class="btn mini secondary" type="button">关闭</button></div>`;
    setTimeout(() => { summaryEl.classList.add('is-hidden'); summaryEl.classList.remove('is-visible'); }, 10000);
  }
}

function dismissTrainingSummary() {
  const el = document.getElementById('trainingSummaryBanner');
  if (el) el.classList.add('is-hidden');
}

function validateImport(data) {
  const errors = [];
  const exerciseIds = new Set();
  (data.exercises || []).forEach((exercise) => {
    if (!exercise.id || !/^[A-Za-z0-9_]+$/.test(exercise.id)) errors.push(`动作 ${exercise.name || '未命名'} ID 不合法`);
    if (exerciseIds.has(exercise.id)) errors.push(`重复动作 ID：${exercise.id}`);
    exerciseIds.add(exercise.id);
    const defaultCount = (exercise.videos || []).filter((video) => video.isDefault).length;
    if (defaultCount > 1) errors.push(`动作 ${exercise.name || exercise.id} 存在多个默认视频`);
  });
  (data.templates || []).forEach((template) => (template.exerciseIds || []).forEach((id) => { if (!exerciseIds.has(id)) errors.push(`模板 ${template.name || template.id} 引用不存在动作：${id}`); }));
  return { errors, counts: { exercises: data.exercises?.length || 0, templates: data.templates?.length || 0, schedule: Object.keys(data.schedule || {}).length } };
}

function attachEvents() {
  $('navList').addEventListener('click', (event) => { const item = event.target.closest('[data-page]'); if (item) switchPage(item.dataset.page); });
  document.body.addEventListener('click', async (event) => {
    const target = event.target;
    const linkEl = target.closest('[data-page-link]'); if (linkEl) switchPage(linkEl.dataset.pageLink);
    const aiDisabledEl = target.closest('[data-ai-disabled]'); if (aiDisabledEl) alert('第二阶段开放');
    const aiImportEl = target.closest('[data-ai-action="import"]'); if (aiImportEl) { switchPage('settings'); const box = $('aiImportPrompt'); if (box) box.scrollIntoView({ behavior: 'smooth' }); }
    const aiSearchEl = target.closest('[data-ai-action="search-video"]'); if (aiSearchEl) openAiVideoSearchDialog(null);
    const aiSearchVideoEl = target.closest('[data-ai-search-video]'); if (aiSearchVideoEl) openAiVideoSearchDialog(aiSearchVideoEl.dataset.aiSearchVideo);
    const startTrainingEl = target.closest('[data-start-training]'); if (startTrainingEl || target.id === 'startTodayTop') startTrainingSession();
    if (target.closest('[data-expand-today]')) renderTodayCard('dashboardToday', true);
    if (target.closest('[data-show-detail]')) switchPage('today');
    const editPlanEl = target.closest('[data-edit-plan]'); if (editPlanEl) openPlanDialog(editPlanEl.dataset.editPlan);
    const editExerciseEl = target.closest('[data-edit-exercise]'); if (editExerciseEl) openExerciseDialog(editExerciseEl.dataset.editExercise);
    if (target.id === 'addExercise') openExerciseDialog();
    const addVideoEl = target.closest('[data-add-video]'); if (addVideoEl) openVideoDialog(addVideoEl.dataset.addVideo);
    const editTemplateEl = target.closest('[data-edit-template]'); if (editTemplateEl) openTemplateDialog(editTemplateEl.dataset.editTemplate);
    if (target.id === 'addTemplate') openTemplateDialog();
    const deleteExerciseEl = target.closest('[data-delete-exercise]'); if (deleteExerciseEl) deleteExercise(deleteExerciseEl.dataset.deleteExercise);
    const deleteTemplateEl = target.closest('[data-delete-template]'); if (deleteTemplateEl) deleteTemplate(deleteTemplateEl.dataset.deleteTemplate);
    const defaultVideoEl = target.closest('[data-default-video]'); if (defaultVideoEl) setDefaultVideo(...defaultVideoEl.dataset.defaultVideo.split('::'));
    const closeModalEl = target.closest('[data-close-modal]'); if (closeModalEl) closeModalEl.closest('dialog').close();
    if (target.id === 'prevMonth' || target.id === 'prevMonthPage') { visibleMonth.setMonth(visibleMonth.getMonth() - 1); render(); }
    if (target.id === 'nextMonth' || target.id === 'nextMonthPage') { visibleMonth.setMonth(visibleMonth.getMonth() + 1); render(); }
    if (target.closest('[data-complete-set]')) dispatchSession('COMPLETE_SET');
    if (target.closest('[data-next-exercise]')) dispatchSession('NEXT_EXERCISE');
    if (target.closest('[data-prev-exercise]')) dispatchSession('PREV_EXERCISE');
    if (target.closest('[data-skip-exercise]')) dispatchSession('SKIP_EXERCISE');
    if (target.closest('[data-rest]')) { session.status = 'resting'; updateApp('session:rest'); }
    if (target.closest('[data-pause-session]')) { session.status = session.status === 'paused' ? 'in_progress' : 'paused'; updateApp('session:pause'); }
    if (target.closest('[data-end-session]') && confirm('确认结束本次训练？当前训练进度会保存为未完成。')) finishTraining('partial');
    const jumpEl = target.closest('[data-jump-exercise]'); if (jumpEl) { session.currentExerciseIndex = Number(jumpEl.dataset.jumpExercise); session.currentSetIndex = 0; session.status = 'in_progress'; updateApp('session:jump'); }
    if (target.id === 'dismissSummaryBanner') dismissTrainingSummary();
  });
  $('exerciseSearch').addEventListener('input', renderExercises);
  $('exerciseFilter').addEventListener('change', renderExercises);
  $('exerciseForm').addEventListener('submit', saveExerciseFromForm);
  $('templateForm').addEventListener('submit', saveTemplateFromForm);
  $('planForm').addEventListener('submit', savePlanFromForm);
  $('videoForm').addEventListener('submit', saveVideoFromForm);
  $('exportJson').addEventListener('click', () => { $('jsonBox').value = JSON.stringify(state, null, 2); });
  $('openImport').addEventListener('click', previewImport);
  $('openImportExport').addEventListener('click', () => switchPage('settings'));
  $('resetLocalData').addEventListener('click', () => { if (confirm('确认重置为默认种子数据？')) { state = defaultData(); saveData(); render(); } });
  $('sendDingTalk').addEventListener('click', sendDingTalk);
  // AI 事件
  $('aiTestConnection').addEventListener('click', checkAiHealth);
  $('aiGenerateDraft').addEventListener('click', generateAiDraft);
  $('aiConfirmImport').addEventListener('click', confirmAiImport);
  $('aiCancelImport').addEventListener('click', cancelAiImport);
  $('aiVideoSearchConfirm').addEventListener('click', confirmAiVideoSearch);
  $('aiVideoSearchRefresh').addEventListener('click', () => {
    const exId = $('aiVideoSearchDialog').dataset.exerciseId || null;
    openAiVideoSearchDialog(exId);
  });
}

function saveExerciseFromForm(event) {
  event.preventDefault();
  const form = new FormData(event.target);
  const id = form.get('id').trim();
  const motionType = form.get('motionType');
  const exercise = { id, name: form.get('name').trim(), category: form.get('category').trim(), bodyParts: form.get('bodyParts').split(/[、,，]/).map((x) => x.trim()).filter(Boolean), difficulty: form.get('difficulty'), defaultSets: Number(form.get('defaultSets') || 1), defaultReps: motionType === 'reps' ? form.get('defaultReps').trim() : null, durationSeconds: motionType === 'duration' ? Number(form.get('durationSeconds') || 30) : null, notes: form.get('notes'), tips: form.get('tips').split('\n').map((x) => x.trim()).filter(Boolean), videos: exerciseById(id)?.videos || [] };
  const existing = state.exercises.findIndex((item) => item.id === id);
  if (existing >= 0) state.exercises[existing] = exercise; else state.exercises.push(exercise);
  saveData(); $('exerciseDialog').close(); render();
}

function saveTemplateFromForm(event) {
  event.preventDefault();
  const form = new FormData(event.target);
  const id = form.get('id').trim();
  const exerciseIds = form.getAll('exerciseIds');
  if (!exerciseIds.length) return alert('训练模板至少选择 1 个动作');
  const template = { id, name: form.get('name').trim(), description: form.get('description'), exerciseIds, estimatedMinutes: Number(form.get('estimatedMinutes') || 30), difficulty: form.get('difficulty') };
  const existing = state.templates.findIndex((item) => item.id === id);
  if (existing >= 0) state.templates[existing] = template; else state.templates.push(template);
  saveData(); $('templateDialog').close(); render();
}

function savePlanFromForm(event) {
  event.preventDefault();
  const form = new FormData(event.target);
  const date = form.get('date');
  const type = form.get('type');
  const templateId = form.get('templateId');
  if (type === 'training' && !templateId) return alert('训练日必须选择训练模板');
  state.schedule[date] = { type, templateId: type === 'training' ? templateId : undefined, status: form.get('status'), note: form.get('note') };
  saveData(); $('planDialog').close(); render();
}

function saveVideoFromForm(event) {
  event.preventDefault();
  const exercise = exerciseById($('videoDialog').dataset.exerciseId);
  if (!exercise) { alert('动作已不存在'); return; }
  const form = new FormData(event.target);
  const rawUrl = form.get('url').trim();
  const validation = validateBilibiliUrl(rawUrl);
  if (!validation.valid) { alert(validation.error); return; }
  const video = { id: form.get('id').trim(), title: form.get('title').trim(), platform: 'bilibili', url: rawUrl, isDefault: form.get('isDefault') === 'on', remark: form.get('remark') };
  exercise.videos = exercise.videos || [];
  if (video.isDefault) exercise.videos.forEach((item) => { item.isDefault = false; });
  exercise.videos.push(video);
  saveData(); $('videoDialog').close(); render();
}

function deleteExercise(id) {
  const exercise = exerciseById(id);
  const refs = state.templates.filter((template) => template.exerciseIds.includes(id));
  const message = refs.length ? `该动作正在被以下模板引用：\n${refs.map((item) => `- ${item.name}`).join('\n')}\n删除后将从这些模板中移除。` : `确认删除动作「${exercise.name}」？`;
  if (!confirm(message)) return;
  state.exercises = state.exercises.filter((item) => item.id !== id);
  state.templates.forEach((template) => { template.exerciseIds = template.exerciseIds.filter((item) => item !== id); });
  saveData(); render();
}

function deleteTemplate(id) {
  const template = templateById(id);
  if (!confirm(`确认删除模板「${template.name}」？如果有计划引用该模板，对应日期将变为“暂无有效模板”。`)) return;
  state.templates = state.templates.filter((item) => item.id !== id);
  saveData(); render();
}

function setDefaultVideo(exerciseId, videoId) {
  const exercise = exerciseById(exerciseId);
  exercise.videos.forEach((video) => { video.isDefault = video.id === videoId; });
  saveData(); render();
}

function completeSet() {
  const template = templateById(session.templateId);
  const exercises = templateExercises(template);
  const exercise = exercises[session.currentExerciseIndex];
  session.totalSetsDone = (session.totalSetsDone || 0) + 1;
  if (session.currentSetIndex < exercise.defaultSets - 1) { session.currentSetIndex += 1; session.status = 'resting'; } else { session.completed.push(exercise.id); if (session.currentExerciseIndex < exercises.length - 1) nextExercise(); else finishTraining('done'); }
  updateApp('session:set-complete');
}
function nextExercise() { const template = templateById(session.templateId); const exercises = templateExercises(template); if (session.currentExerciseIndex < exercises.length - 1) { session.currentExerciseIndex += 1; session.currentSetIndex = 0; session.status = 'in_progress'; updateApp('session:next'); } else finishTraining('done'); }
function prevExercise() { if (session.currentExerciseIndex > 0) { session.currentExerciseIndex -= 1; session.currentSetIndex = 0; session.status = 'in_progress'; updateApp('session:prev'); } }
function skipExercise() { const template = templateById(session.templateId); const exercises = templateExercises(template); session.skipped.push(exercises[session.currentExerciseIndex].id); nextExercise(); }

function previewImport() {
  try {
    const data = normalizeData(JSON.parse($('jsonBox').value));
    const result = validateImport(data);
    const templatePreviews = (data.templates || []).map((t) => {
      const exNames = (t.exerciseIds || []).map((eid) => {
        const ex = data.exercises.find((e) => e.id === eid);
        return ex ? ex.name : eid;
      });
      return `<div class="import-template-preview"><strong>${escapeHtml(t.name)}</strong><span>${escapeHtml(t.description || '暂无描述')}</span><em>${exNames.join('、') || '无动作'}</em></div>`;
    }).join('');
    // 检查是否覆盖已有日期计划
    const existingDates = Object.keys(state.schedule);
    const incomingDates = Object.keys(data.schedule || {});
    const overlap = incomingDates.filter((d) => existingDates.includes(d));
    let overlapWarning = '';
    if (overlap.length) {
      overlapWarning = `<p style="color:var(--orange);margin-top:8px">⚠ 以下日期已有计划，导入将覆盖：${overlap.slice(0, 5).join(', ')}${overlap.length > 5 ? ` 等共 ${overlap.length} 天` : ''}</p>`;
    }
    const hasErrors = result.errors.length > 0;
    $('importPreview').innerHTML = `<strong>导入预览</strong><p>动作数量：${result.counts.exercises} | 模板数量：${result.counts.templates} | 计划数量：${result.counts.schedule} | 错误数量：${result.errors.length}</p>${templatePreviews}${hasErrors ? `<pre>${escapeHtml(result.errors.join('\n'))}</pre>` : '<button id="confirmImport" class="btn primary" type="button">确认导入</button>'}${overlapWarning}`;
    if (hasErrors) return;
    const confirmBtn = $('confirmImport');
    if (confirmBtn) {
      confirmBtn.addEventListener('click', () => {
        if (overlap.length && !confirm(`导入将覆盖 ${overlap.length} 天的已有计划（${overlap.slice(0, 5).join(', ')}${overlap.length > 5 ? ` 等共 ${overlap.length} 天` : ''}），确认继续？`)) return;
        state = data;
        saveData();
        render();
        confirmBtn.textContent = '已导入';
        confirmBtn.disabled = true;
        alert('导入完成');
      });
    }
  } catch (error) { $('importPreview').innerHTML = `<strong>导入失败</strong><p>${escapeHtml(error.message)}</p>`; }
}

async function sendDingTalk() {
  const plan = todayPlan();
  if (!plan || plan.type !== 'training') { $('reminderResult').textContent = '今天不是训练日或没有计划，不创建钉钉提醒。'; return; }
  try {
    const response = await fetch('/api/reminders/dingtalk/send', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ plan_id: 1, title: '运动训练提醒', message: '请查看今日训练动作和视频链接' }) });
    const data = await response.json();
    $('reminderResult').textContent = JSON.stringify(data, null, 2);
  } catch (error) { $('reminderResult').textContent = `发送失败：${error.message}`; }
}

// ── AI 辅助能力 ───────────────────────────────────────────────────────────

async function checkAiHealth() {
  const statusEl = $('aiStatus');
  statusEl.textContent = '检测中...';
  try {
    const response = await fetch('/api/ai/health');
    const data = await response.json();
    if (data.enabled) {
      statusEl.textContent = `AI 服务已配置（${data.model || '未知模型'}）`;
      statusEl.className = 'status-ok';
    } else {
      statusEl.textContent = 'AI 服务未配置';
      statusEl.className = 'status-warn';
    }
  } catch (error) {
    statusEl.textContent = `检测失败：${error.message}`;
    statusEl.className = 'status-error';
  }
}

async function generateAiDraft() {
  const prompt = $('aiImportPrompt').value.trim();
  if (!prompt) { alert('请先输入训练需求描述'); return; }
  const resultEl = $('aiDraftResult');
  const errorEl = $('aiImportError');
  resultEl.classList.add('is-hidden');
  errorEl.classList.add('is-hidden');
  const btn = $('aiGenerateDraft');
  btn.disabled = true;
  btn.textContent = '生成中...';
  try {
    const response = await fetch('/api/ai/import-plan', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ prompt, current_data: state }),
    });
    if (!response.ok) {
      const err = await response.json().catch(() => ({ detail: `HTTP ${response.status}` }));
      throw new Error(err.detail || `请求失败：${response.status}`);
    }
    const data = await response.json();
    // 存为草稿
    window.__aiDraft = data;
    const draft = data.draft;
    const counts = {
      exercises: draft.exercises?.length || 0,
      templates: draft.templates?.length || 0,
      plans: draft.plans?.length || 0,
    };
    $('aiDraftPreview').textContent = JSON.stringify(draft, null, 2);
    $('aiDraftErrors').innerHTML = (data.warnings || []).length
      ? `<strong>警告：</strong><br/>${data.warnings.map((w) => escapeHtml(w)).join('<br/>')}`
      : `<span class="status-ok">校验通过 — ${counts.exercises} 个动作、${counts.templates} 个模板、${counts.plans} 天计划</span>`;
    resultEl.classList.remove('is-hidden');
  } catch (error) {
    errorEl.textContent = `生成失败：${error.message}`;
    errorEl.classList.remove('is-hidden');
  } finally {
    btn.disabled = false;
    btn.textContent = '生成草稿';
  }
}

function confirmAiImport() {
  const data = window.__aiDraft;
  if (!data) return;
  const draft = data.draft;
  // 检查计划日期重叠
  const existingDates = Object.keys(state.schedule);
  const incomingDates = (draft.plans || []).filter((p) => p.date).map((p) => p.date);
  const overlap = incomingDates.filter((d) => existingDates.includes(d));
  if (overlap.length && !confirm(`导入将覆盖 ${overlap.length} 天的已有计划（${overlap.slice(0, 5).join(', ')}${overlap.length > 5 ? ` 等共 ${overlap.length} 天` : ''}），确认继续？`)) {
    return;
  }
  // 合并 exercises
  for (const ex of draft.exercises || []) {
    const idx = state.exercises.findIndex((e) => e.id === ex.id);
    if (idx >= 0) state.exercises[idx] = ex;
    else state.exercises.push(ex);
  }
  // 合并 templates
  for (const tmpl of draft.templates || []) {
    const idx = state.templates.findIndex((t) => t.id === tmpl.id);
    if (idx >= 0) state.templates[idx] = tmpl;
    else state.templates.push(tmpl);
  }
  // 合并 plans
  for (const plan of draft.plans || []) {
    if (plan.date) {
      state.schedule[plan.date] = {
        type: plan.type || 'rest',
        templateId: plan.templateId || undefined,
        status: plan.status || 'pending',
        note: plan.note || '',
      };
    }
  }
  saveData();
  render();
  $('aiDraftResult').classList.add('is-hidden');
  $('aiImportPrompt').value = '';
  window.__aiDraft = null;
  alert('导入完成！');
}

function cancelAiImport() {
  $('aiDraftResult').classList.add('is-hidden');
  $('aiImportError').classList.add('is-hidden');
  window.__aiDraft = null;
}

async function openAiVideoSearchDialog(exerciseId) {
  const dialog = $('aiVideoSearchDialog');
  const nameEl = $('aiVideoSearchExerciseName');
  const suggestionsEl = $('aiVideoSearchSuggestions');
  const urlInput = $('aiVideoSearchFinalUrl');
  dialog.dataset.exerciseId = exerciseId || '';

  if (!exerciseId) {
    // 从侧边栏触发 — 先选动作
    const ids = state.exercises.map((e) => e.id);
    if (!ids.length) { alert('动作库为空，请先添加动作。'); return; }
    const chosen = prompt('为哪个动作搜索视频？输入动作 ID：\n' + ids.join(', '));
    if (!chosen) return;
    exerciseId = chosen.trim();
    dialog.dataset.exerciseId = exerciseId;
  }

  const exercise = exerciseById(exerciseId);
  if (!exercise) { alert('未找到该动作'); return; }
  nameEl.textContent = `动作：${exercise.name}（${exercise.category}）`;
  urlInput.value = '';
  suggestionsEl.innerHTML = '搜索中...';

  try {
    const response = await fetch('/api/ai/suggest-bilibili-video', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        exercise_name: exercise.name,
        description: exercise.notes || '',
        notes: (exercise.tips || []).join('；'),
      }),
    });
    if (!response.ok) {
      const err = await response.json().catch(() => ({ detail: `HTTP ${response.status}` }));
      // 未配置 AI 时，生成默认搜索链接
      if (response.status === 400) {
        const query = encodeURIComponent(exercise.name);
        suggestionsEl.innerHTML = `
          <p>AI 服务未配置，已生成基础搜索链接：</p>
          <a href="https://search.bilibili.com/all?keyword=${query}" target="_blank" rel="noopener noreferrer">B站搜索「${escapeHtml(exercise.name)}」</a>
        `;
        urlInput.value = `https://search.bilibili.com/all?keyword=${query}`;
        dialog.showModal();
        return;
      }
      throw new Error(err.detail || `请求失败：${response.status}`);
    }
    const data = await response.json();
    suggestionsEl.innerHTML = `
      <p>搜索关键词：<strong>${escapeHtml(data.query)}</strong></p>
      <p>B站搜索链接：<a href="${escapeHtml(data.search_url)}" target="_blank" rel="noopener noreferrer">${escapeHtml(data.search_url)}</a></p>
      ${data.candidates?.length ? `<p>建议的视频链接：</p><ul>${data.candidates.map((c) => `<li><a href="${escapeHtml(c)}" target="_blank">${escapeHtml(c)}</a></li>`).join('')}</ul>` : ''}
      <p class="helper-text">请手动确认或修改最终链接后点击「确认使用」。</p>
    `;
    urlInput.value = data.search_url || '';
  } catch (error) {
    suggestionsEl.innerHTML = `<span style="color:var(--red)">搜索失败：${escapeHtml(error.message)}</span>`;
  }
  dialog.showModal();
}

function confirmAiVideoSearch(event) {
  event.preventDefault();
  const dialog = $('aiVideoSearchDialog');
  const exerciseId = dialog.dataset.exerciseId;
  const url = $('aiVideoSearchFinalUrl').value.trim();
  if (!exerciseId || !url) { alert('请填写视频链接'); return; }
  const exercise = exerciseById(exerciseId);
  if (!exercise) { alert('动作已不存在'); return; }
  exercise.videos = exercise.videos || [];
  exercise.videos.push({
    id: uid('vid'),
    title: exercise.name + ' 教学视频',
    platform: 'bilibili',
    url,
    isDefault: !exercise.videos.some((v) => v.isDefault),
    remark: '由 AI 搜索添加',
  });
  saveData();
  render();
  dialog.close();
  alert('视频链接已添加！');
}
async function bootstrapApp() {
  render();
  attachEvents();
  await loadHealth();
  checkAiHealth();
  render();
}

if (document.readyState === 'loading') {
  document.addEventListener('DOMContentLoaded', () => {
    bootstrapApp().catch((error) => {
      console.error('bootstrap failed', error);
      const healthEl = $('health');
      if (healthEl) {
        healthEl.className = 'status-pill warn';
        healthEl.textContent = '前端启动失败';
      }
    });
  }, { once: true });
} else {
  bootstrapApp().catch((error) => {
    console.error('bootstrap failed', error);
    const healthEl = $('health');
    if (healthEl) {
      healthEl.className = 'status-pill warn';
      healthEl.textContent = '前端启动失败';
    }
  });
}

