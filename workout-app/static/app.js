const STORAGE_KEY = 'workout_planner_data_v1';
const BACKEND_ENDPOINT_CONTRACT = [
  '/api/health',
  '/api/today',
  '/api/plans/week?date=${isoToday}',
  '/api/plans/month?year=${year}&month=${month}',
  '/api/calendar?year=${year}&month=${month}',
  '/api/stats',
  '/api/settings',
  '/api/logs',
  '/api/logs/${action}',
  '/api/reminders/dingtalk/send',
  '/api/todos/dingtalk/create',
];
const $ = (id) => document.getElementById(id);
const $$ = (selector, root = document) => Array.from(root.querySelectorAll(selector));
const today = new Date();
const isoToday = today.toISOString().slice(0, 10);
let currentPage = 'dashboard';
let visibleMonth = new Date(today.getFullYear(), today.getMonth(), 1);
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
  try {
    const raw = localStorage.getItem(STORAGE_KEY);
    if (!raw) {
      const seeded = defaultData();
      localStorage.setItem(STORAGE_KEY, JSON.stringify(seeded));
      return seeded;
    }
    return normalizeData(JSON.parse(raw));
  } catch (error) {
    console.error('本地数据损坏，已重新初始化', error);
    const seeded = defaultData();
    localStorage.setItem(STORAGE_KEY, JSON.stringify(seeded));
    return seeded;
  }
}

function saveData() {
  state.updatedAt = new Date().toISOString();
  localStorage.setItem(STORAGE_KEY, JSON.stringify(state));
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

function updateStorageUsage() {
  const bytes = new Blob([localStorage.getItem(STORAGE_KEY) || '']).size;
  $('storageUsage').textContent = `${(bytes / 1024).toFixed(1)} KB / 5 MB`;
}

async function loadHealth() {
  try {
    const response = await fetch('/api/health');
    if (!response.ok) throw new Error(String(response.status));
    $('health').className = 'status-pill ok';
    $('health').textContent = '后端正常';
  } catch (error) {
    $('health').className = 'status-pill warn';
    $('health').textContent = '本地前端可用';
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
    return `<article class="week-card ${plan.type} ${isToday ? 'today' : ''}" data-edit-plan="${date}"><span>${date}</span><strong>${isToday ? '今日 · ' : ''}${plan.type === 'training' ? escapeHtml(template?.name || '模板丢失') : '休息恢复'}</strong><em>${plan.type === 'training' ? '训练' : '休息'} · ${statusText(plan.status)}</em></article>`;
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
    cells.push(`<button class="calendar-day ${plan.type} ${date === isoToday ? 'today' : ''}" data-edit-plan="${date}" type="button"><span>${day}</span><i>${plan.type === 'training' ? escapeHtml(template?.name || '训练') : '休息'}</i><em>${statusText(plan.status)}</em></button>`);
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
    return `<article class="data-card"><div><h3>${escapeHtml(exercise.name)}</h3><p>${escapeHtml(exercise.category)} / ${escapeHtml((exercise.bodyParts || []).join('、'))} / ${escapeHtml(exercise.difficulty)}</p><p>默认组次：${escapeHtml(doseText(exercise))}</p><p>默认 B站视频：${video ? escapeHtml(video.title) : '暂无视频链接'}</p></div><div class="card-actions">${video ? `<a class="btn mini" href="${escapeHtml(video.url)}" target="_blank" rel="noopener noreferrer">打开Bilibili</a>` : ''}<button class="btn mini" data-edit-exercise="${escapeHtml(exercise.id)}" type="button">编辑</button><button class="btn mini" data-add-video="${escapeHtml(exercise.id)}" type="button">添加视频</button><button class="btn danger mini" data-delete-exercise="${escapeHtml(exercise.id)}" type="button">删除</button></div></article>`;
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
    return `<article class="video-group"><h3>${escapeHtml(exercise.name)}</h3>${videos.length ? videos.map((video) => `<div class="video-row"><div><strong>${escapeHtml(video.title)} ${video.isDefault ? '· 默认' : ''}</strong><span>${escapeHtml(video.url)}</span></div><div><button class="btn mini" data-default-video="${escapeHtml(exercise.id)}::${escapeHtml(video.id)}" type="button">设为默认</button><a class="btn mini" href="${escapeHtml(video.url)}" target="_blank" rel="noopener noreferrer">打开Bilibili</a></div></div>`).join('') : '<p>暂无视频链接</p>'}<button class="btn mini" data-add-video="${escapeHtml(exercise.id)}" type="button">添加B站视频</button></article>`;
  }).join('');
}

function renderSettings() {
  $('jsonBox').value = $('jsonBox').value || '';
  $('importPreview').innerHTML = `<strong>本地数据状态</strong><p>动作 ${state.exercises.length} 个，模板 ${state.templates.length} 个，计划 ${Object.keys(state.schedule).length} 天，训练记录 ${state.logs.length} 条。</p>`;
}

function renderTrainingSession() {
  const target = $('trainingSession');
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
  const progress = Math.round(((session.currentExerciseIndex) / Math.max(exercises.length, 1)) * 100);
  target.innerHTML = `<div class="session-head"><button class="ghost-btn" data-page-link="dashboard" type="button">返回</button><div><h2>${escapeHtml(template.name)}</h2><p>本地训练模式 · 第 ${session.currentExerciseIndex + 1} / ${exercises.length} 个动作 · 总进度 ${progress}% · 状态：${escapeHtml(statusText(session.status))}</p></div><button class="btn danger" data-end-session type="button">结束训练</button></div><div class="session-grid"><article class="current-exercise"><p class="eyebrow">当前动作</p><h3>${escapeHtml(exercise.name)}</h3><p>目标：${escapeHtml(exercise.category)} · ${escapeHtml(doseText(exercise))} · 当前第 ${session.currentSetIndex + 1} / ${exercise.defaultSets} 组</p><ul>${(exercise.tips || []).map((tip) => `<li>${escapeHtml(tip)}</li>`).join('')}</ul><div class="button-row"><button class="btn primary" data-complete-set type="button">完成本组</button><button class="btn secondary" data-rest type="button">进入休息</button><button class="btn warning" data-skip-exercise type="button">跳过动作</button></div></article><aside class="video-panel"><p class="eyebrow">当前视频</p>${video ? `<h3>${escapeHtml(video.title)}</h3><p>${escapeHtml(video.remark || '')}</p><a class="btn primary" href="${escapeHtml(video.url)}" target="_blank" rel="noopener noreferrer">打开Bilibili视频</a><button class="btn secondary" data-change-video="${escapeHtml(exercise.id)}" type="button">更换视频</button>` : `<h3>当前动作暂无视频</h3><button class="btn secondary" data-add-video="${escapeHtml(exercise.id)}" type="button">添加视频</button>`}</aside></div><div class="session-actions"><button class="ghost-btn" data-prev-exercise type="button" ${session.currentExerciseIndex === 0 ? 'disabled' : ''}>上一个动作</button><button class="ghost-btn" data-next-exercise type="button">下一个动作</button><button class="ghost-btn" data-pause-session type="button">${session.status === 'paused' ? '继续训练' : '暂停训练'}</button></div><ol class="session-list">${exercises.map((item, index) => `<li class="${index === session.currentExerciseIndex ? 'active' : ''} ${session.completed.includes(item.id) ? 'done' : ''} ${session.skipped.includes(item.id) ? 'skipped' : ''}" data-jump-exercise="${index}">${escapeHtml(item.name)}<span>${index === session.currentExerciseIndex ? '进行中' : session.completed.includes(item.id) ? '已完成' : session.skipped.includes(item.id) ? '已跳过' : '待开始'}</span></li>`).join('')}</ol>`;
}

function render() {
  updateStorageUsage();
  renderTodayCard('dashboardToday');
  renderTodayCard('todayDetail', true);
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
  $('exerciseDialog').dataset.editingId = id || '';
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
  session = { templateId: template.id, currentExerciseIndex: 0, currentSetIndex: 0, status: 'in_progress', startedAt: new Date().toISOString(), completed: [], skipped: [] };
  currentPage = 'trainingSession';
  switchPage('trainingSession');
}

function finishTraining(status = 'done') {
  const plan = todayPlan();
  if (plan) plan.status = status;
  state.logs.unshift({ id: uid('log'), date: isoToday, templateId: session?.templateId, startedAt: session?.startedAt, endedAt: new Date().toISOString(), completed: session?.completed || [], skipped: session?.skipped || [], status });
  session = null;
  saveData();
  switchPage('dashboard');
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
  $('navList').addEventListener('click', (event) => { const page = event.target.dataset.page; if (page) switchPage(page); });
  document.body.addEventListener('click', async (event) => {
    const target = event.target;
    if (target.dataset.pageLink) switchPage(target.dataset.pageLink);
    if (target.dataset.aiDisabled !== undefined) alert('第二阶段开放');
    if (target.dataset.startTraining !== undefined || target.id === 'startTodayTop') startTrainingSession();
    if (target.dataset.expandToday !== undefined) renderTodayCard('dashboardToday', true);
    if (target.dataset.showDetail !== undefined) switchPage('today');
    if (target.dataset.editPlan) openPlanDialog(target.dataset.editPlan);
    if (target.dataset.editExercise) openExerciseDialog(target.dataset.editExercise);
    if (target.id === 'addExercise') openExerciseDialog();
    if (target.dataset.addVideo) openVideoDialog(target.dataset.addVideo);
    if (target.dataset.editTemplate) openTemplateDialog(target.dataset.editTemplate);
    if (target.id === 'addTemplate') openTemplateDialog();
    if (target.dataset.deleteExercise) deleteExercise(target.dataset.deleteExercise);
    if (target.dataset.deleteTemplate) deleteTemplate(target.dataset.deleteTemplate);
    if (target.dataset.defaultVideo) setDefaultVideo(...target.dataset.defaultVideo.split('::'));
    if (target.dataset.closeModal !== undefined) target.closest('dialog').close();
    if (target.id === 'prevMonth' || target.id === 'prevMonthPage') { visibleMonth.setMonth(visibleMonth.getMonth() - 1); render(); }
    if (target.id === 'nextMonth' || target.id === 'nextMonthPage') { visibleMonth.setMonth(visibleMonth.getMonth() + 1); render(); }
    if (target.dataset.completeSet !== undefined) completeSet();
    if (target.dataset.nextExercise !== undefined) nextExercise();
    if (target.dataset.prevExercise !== undefined) prevExercise();
    if (target.dataset.skipExercise !== undefined) skipExercise();
    if (target.dataset.rest !== undefined) { session.status = 'resting'; renderTrainingSession(); }
    if (target.dataset.pauseSession !== undefined) { session.status = session.status === 'paused' ? 'in_progress' : 'paused'; renderTrainingSession(); }
    if (target.dataset.endSession !== undefined && confirm('确认结束本次训练？当前训练进度会保存为未完成。')) finishTraining('partial');
    if (target.dataset.jumpExercise) { session.currentExerciseIndex = Number(target.dataset.jumpExercise); session.currentSetIndex = 0; session.status = 'in_progress'; renderTrainingSession(); }
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
  const form = new FormData(event.target);
  const video = { id: form.get('id').trim(), title: form.get('title').trim(), platform: 'bilibili', url: form.get('url').trim(), isDefault: form.get('isDefault') === 'on', remark: form.get('remark') };
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
  if (session.currentSetIndex < exercise.defaultSets - 1) { session.currentSetIndex += 1; session.status = 'resting'; } else { session.completed.push(exercise.id); if (session.currentExerciseIndex < exercises.length - 1) nextExercise(); else finishTraining('done'); }
  renderTrainingSession();
}
function nextExercise() { const template = templateById(session.templateId); const exercises = templateExercises(template); if (session.currentExerciseIndex < exercises.length - 1) { session.currentExerciseIndex += 1; session.currentSetIndex = 0; session.status = 'in_progress'; renderTrainingSession(); } else finishTraining('done'); }
function prevExercise() { if (session.currentExerciseIndex > 0) { session.currentExerciseIndex -= 1; session.currentSetIndex = 0; session.status = 'in_progress'; renderTrainingSession(); } }
function skipExercise() { const template = templateById(session.templateId); const exercises = templateExercises(template); session.skipped.push(exercises[session.currentExerciseIndex].id); nextExercise(); }

function previewImport() {
  try {
    const data = normalizeData(JSON.parse($('jsonBox').value));
    const result = validateImport(data);
    $('importPreview').innerHTML = `<strong>导入预览</strong><p>动作数量：${result.counts.exercises}，模板数量：${result.counts.templates}，计划数量：${result.counts.schedule}，错误数量：${result.errors.length}</p>${result.errors.length ? `<pre>${escapeHtml(result.errors.join('\n'))}</pre>` : '<button id="confirmImport" class="btn primary" type="button">确认导入</button>'}`;
    const confirmBtn = $('confirmImport');
    if (confirmBtn) confirmBtn.addEventListener('click', () => { state = data; saveData(); render(); alert('导入完成'); });
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

loadHealth();
attachEvents();
render();
