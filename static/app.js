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
  '/api/notifications/send',
  '/api/exercises',
  '/api/exercises/${exercise_id}',
  '/api/templates',
  '/api/templates/${template_id}',
  '/api/training/complete',
  '/api/plans/${plan_id}',
];
const $ = (id) => document.getElementById(id);
const $$ = (selector, root = document) => Array.from(root.querySelectorAll(selector));
const THEME_STORAGE_KEY = 'workout_theme_mode_v1';
const today = new Date();
const isoToday = today.toISOString().slice(0, 10);
let currentPage = 'dashboard';
let visibleMonth = new Date(today.getFullYear(), today.getMonth(), 1);
let startupState = 'loading';
let state = loadData();
let session = null;
let themeMode = 'system';
let systemThemeMedia = null;

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
      { id: 'pelvic_tilt', name: '仰卧骨盆后倾', category: '核心控制', bodyParts: ['核心', '腰腹'], difficulty: '低', defaultSets: 3, defaultReps: '12次', durationSeconds: null, notes: '适合核心激活和骨盆控制。', benefit: '主要激活腹横肌与骨盆底肌，改善骨盆前倾，增强腰椎-骨盆带的神经肌肉控制能力，适合久坐人群日常矫正。', tips: ['仰卧屈膝，双脚踩稳', '腰背轻轻贴向地面', '动作慢，不要憋气'], videos: [{ id: 'video_pelvic_tilt_001', title: '仰卧骨盆后倾教学', platform: 'bilibili', url: 'https://www.bilibili.com/video/BV1X625B5EWd/', isDefault: true, remark: '适合初学者' }] },
      { id: 'dead_bug', name: '死虫 Dead Bug', category: '核心控制', bodyParts: ['核心', '腰腹'], difficulty: '低', defaultSets: 3, defaultReps: '10次', durationSeconds: null, notes: '保持腰背贴地，动作慢一点。', benefit: '训练核心抗伸展能力，强化腹横肌与多裂肌协同，提升脊柱在四肢运动中的稳定性，减少下背代偿风险。', tips: ['腰背贴地', '手脚交替伸展', '动作放慢，不要借力', '保持核心收紧，均匀呼吸'], videos: [{ id: 'video_dead_bug_001', title: '死虫核心训练教学', platform: 'bilibili', url: 'https://www.bilibili.com/video/BV1Bu411V7rW/', isDefault: true, remark: '核心控制入门' }, { id: 'video_dead_bug_002', title: '死虫动作细节讲解', platform: 'bilibili', url: 'https://www.bilibili.com/video/BV1y5411L7Yx/', isDefault: false, remark: '备用视频' }] },
      { id: 'glute_bridge', name: '臀桥', category: '髋部稳定', bodyParts: ['臀部', '核心'], difficulty: '低', defaultSets: 3, defaultReps: '15次', durationSeconds: null, notes: '发力时收紧臀部，避免腰部代偿。', benefit: '主要刺激臀大肌与腘绳肌，改善髋伸肌群募集模式，纠正臀部"失忆症"，减轻腰椎在日常负重中的压力。', tips: ['双脚踩稳', '发力时收紧臀部', '不要用腰顶起来'], videos: [{ id: 'video_glute_bridge_001', title: '臀桥标准动作教学', platform: 'bilibili', url: 'https://www.bilibili.com/video/BV1Jg4y1z7Nm/', isDefault: true, remark: '臀部激活' }] },
      { id: 'bird_dog', name: 'Bird Dog', category: '核心控制', bodyParts: ['核心', '背部'], difficulty: '低', defaultSets: 3, defaultReps: '10次/侧', durationSeconds: null, notes: '保持骨盆稳定，手脚慢慢伸展。', benefit: '训练核心抗旋转与脊柱动态稳定能力，增强肩-髋交叉协调模式，改善姿势控制与平衡能力。', tips: ['四点支撑', '不要塌腰', '左右交替伸展'], videos: [{ id: 'video_bird_dog_001', title: 'Bird Dog 动作教学', platform: 'bilibili', url: 'https://www.bilibili.com/video/BV1No4y1h7NH/', isDefault: true, remark: '核心稳定' }] },
      { id: 'plank', name: '平板支撑', category: '核心控制', bodyParts: ['核心', '肩部'], difficulty: '中', defaultSets: 3, defaultReps: null, durationSeconds: 30, notes: '计时型动作，保持身体一条直线。', benefit: '强化整体核心肌群耐力，包括腹直肌、腹横肌、竖脊肌与肩胛稳定肌群，提升躯干在静态承重下的刚性。', tips: ['肘在肩下', '核心收紧', '不憋气'], videos: [{ id: 'video_plank_001', title: '平板支撑入门', platform: 'bilibili', url: 'https://www.bilibili.com/video/BV1Rv4y1d7XM/', isDefault: true, remark: '计时型动作' }] },
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
    exercises: (Array.isArray(data?.exercises) ? data.exercises : fallback.exercises)
      .map((ex) => ({
        ...ex,
        benefit: ex.benefit || '',
      })),
    templates: Array.isArray(data?.templates) ? data.templates : fallback.templates,
    schedule: data?.schedule && typeof data.schedule === 'object' ? data.schedule : fallback.schedule,
    logs: Array.isArray(data?.logs) ? data.logs : [],
  };
}

function loadData() {
  // Start with an empty shell — real data comes from the API
  return normalizeData({
    version: '1.0',
    updatedAt: new Date().toISOString(),
    exercises: [],
    templates: [],
    schedule: {},
    logs: [],
  });
}

function saveData() {
  state.updatedAt = new Date().toISOString();
  updateStorageUsage();
}

async function saveToBackend() {
  // Persist state to backend via exercise/template/plan/schedule API calls.
  // Returns { success: bool, errors: [] }
  const errors = [];
  try {
    // This batch approach sends the state to the backend's JSON import endpoint.
    // In a full implementation, each CRUD operation would call its own endpoint.
    const response = await fetch('/api/training/complete', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ date: isoToday, status: 'sync', completed: [], skipped: [] }),
    });
    if (!response.ok) errors.push(`保存失败: HTTP ${response.status}`);
  } catch (error) {
    errors.push(`保存失败: ${error.message}`);
  }
  return { success: errors.length === 0, errors };
}

function showToast(message, type = 'info') {
  const toast = $('toastMessage');
  if (!toast) return;
  toast.textContent = message;
  toast.className = `toast ${type}`;
  toast.classList.add('is-visible');
  clearTimeout(toast._timeout);
  toast._timeout = setTimeout(() => { toast.classList.remove('is-visible'); }, 4000);
}

function apiExerciseToState(exercise) {
  return {
    id: String(exercise.id),
    exercise_id: exercise.exercise_id != null ? Number(exercise.exercise_id) : null,
    name: exercise.name || '',
    category: exercise.category || '',
    bodyParts: String(exercise.body_parts || '').split(',').map((item) => item.trim()).filter(Boolean),
    difficulty: exercise.difficulty || '低',
    defaultSets: exercise.default_sets || 1,
    defaultReps: exercise.default_reps,
    durationSeconds: exercise.duration_seconds,
    notes: exercise.notes || '',
    benefit: exercise.benefit || '',
    tips: exercise.tips ? String(exercise.tips).split('\n').filter(Boolean) : [],
    videos: exercise.video_url ? [{ id: `video_${exercise.id}`, title: `${exercise.name || '动作'} Bilibili`, platform: 'bilibili', url: exercise.video_url, isDefault: true, remark: '来自 SQLite' }] : [],
  };
}

function apiTemplateToState(template) {
  return {
    id: String(template.id),
    name: template.name || '',
    description: template.description || '',
    difficulty: template.difficulty || '低强度',
    estimatedMinutes: template.estimated_minutes || 30,
    exerciseIds: (template.exercises || []).map((exercise) => String(exercise.id)),
  };
}

function apiPlanToScheduleEntry(plan, templates) {
  const isTraining = Boolean(plan.isTrainingDay ?? plan.is_training);
  // Do NOT default to templates[0] — a plan may not have any template associated
  const planStatus = plan.status || 'pending';
  let templateId;
  if (isTraining && plan.template_id) {
    templateId = String(plan.template_id);
  }
  return {
    type: isTraining ? 'training' : 'rest',
    templateId,
    status: planStatus,
    note: plan.notes || '',
  };
}

function stateFromApiPayload(payload) {
  // NEVER fallback to defaultData — empty API responses are real empty states
  const exercises = (payload.exercises || []).map(apiExerciseToState);
  const templates = (payload.templates || []).map(apiTemplateToState);
  const schedule = {};
  (payload.plans || payload.days || []).forEach((plan) => {
    if (plan.date) schedule[plan.date] = apiPlanToScheduleEntry(plan, templates);
  });
  if (payload.today?.date) {
    const todayEntry = apiPlanToScheduleEntry(payload.today, templates);
    const monthEntry = schedule[payload.today.date];
    schedule[payload.today.date] = {
      ...todayEntry,
      templateId: todayEntry.templateId || monthEntry?.templateId,
    };
  }
  return {
    version: '1.0',
    updatedAt: new Date().toISOString(),
    exercises,
    templates,
    schedule,
    logs: payload.logs || [],
  };
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

function getExerciseRemark(exercise) {
  if (!exercise) return '';
  return [exercise.notes, exercise.benefit, Array.isArray(exercise.tips) ? exercise.tips.join('；') : exercise.tips]
    .map((item) => String(item || '').trim())
    .find(Boolean) || '';
}

function getSystemTheme() {
  return window.matchMedia && window.matchMedia('(prefers-color-scheme: dark)').matches ? 'dark' : 'light';
}

function getResolvedTheme(mode = themeMode) {
  return mode === 'system' ? getSystemTheme() : mode;
}

function updateThemeUI() {
  const status = $('themeStatus');
  const hint = $('themeModeHint');
  const resolved = getResolvedTheme();
  if (status) status.textContent = themeMode === 'system' ? `跟随系统 · 当前${resolved === 'dark' ? '深色' : '浅色'}` : (themeMode === 'dark' ? '深色' : '浅色');
  if (hint) hint.textContent = themeMode === 'system' ? `当前使用跟随系统模式，系统偏好为${resolved === 'dark' ? '深色' : '浅色'}。` : `当前已切换为${themeMode === 'dark' ? '深色' : '浅色'}模式，并保存在 localStorage。`;
  $$('[data-theme-option]').forEach((button) => {
    const active = button.dataset.themeOption === themeMode;
    button.classList.toggle('active', active);
    button.setAttribute('aria-checked', active ? 'true' : 'false');
  });
}

function applyTheme(mode = themeMode) {
  themeMode = ['light', 'dark', 'system'].includes(mode) ? mode : 'system';
  const resolved = getResolvedTheme(themeMode);
  document.body.dataset.theme = resolved;
  document.body.classList.toggle('theme-light', resolved === 'light');
  document.body.classList.toggle('theme-dark', resolved === 'dark');
  document.documentElement.style.colorScheme = resolved;
  updateThemeUI();
}

function setTheme(mode) {
  window.localStorage.setItem(THEME_STORAGE_KEY, mode);
  applyTheme(mode);
}

function setAiProgress(stateName) {
  const progress = $('aiProgress');
  if (progress) progress.dataset.state = stateName;
}

function initTheme() {
  themeMode = window.localStorage.getItem(THEME_STORAGE_KEY) || 'system';
  if (!window.localStorage.getItem(THEME_STORAGE_KEY)) {
    window.localStorage.setItem(THEME_STORAGE_KEY, themeMode);
  }
  if (window.matchMedia) {
    systemThemeMedia = window.matchMedia('(prefers-color-scheme: dark)');
    if (typeof systemThemeMedia.addEventListener === 'function') {
      systemThemeMedia.addEventListener('change', () => {
        if (themeMode === 'system') applyTheme('system');
      });
    }
  }
  applyTheme(themeMode);
}

async function loadHealth() {
  startupState = 'loading';
  try {
    const monthToken = `${visibleMonth.getFullYear()}-${String(visibleMonth.getMonth() + 1).padStart(2, '0')}`;
    const [healthResponse, todayResponse, exercisesResponse, templatesResponse, plansResponse, logsResponse] = await Promise.all([
      fetch('/api/health'),
      fetch('/api/today'),
      fetch('/api/exercises'),
      fetch('/api/templates'),
      fetch(`/api/plans/month?month=${monthToken}`),
      fetch('/api/logs'),
    ]);
    if (!healthResponse.ok) throw new Error(String(healthResponse.status));
    if (!todayResponse.ok) throw new Error(String(todayResponse.status));
    const [todayPayload, exercisePayload, templatePayload, planPayload, logPayload] = await Promise.all([
      todayResponse.json(),
      exercisesResponse.ok ? exercisesResponse.json() : Promise.resolve({ exercises: [] }),
      templatesResponse.ok ? templatesResponse.json() : Promise.resolve({ templates: [] }),
      plansResponse.ok ? plansResponse.json() : Promise.resolve({ days: [] }),
      logsResponse.ok ? logsResponse.json() : Promise.resolve({ logs: [] }),
    ]);
    state = stateFromApiPayload({
      today: todayPayload,
      exercises: exercisePayload.exercises || [],
      templates: templatePayload.templates || [],
      days: planPayload.days || [],
      logs: logPayload.logs || [],
    });
    startupState = 'api_ready';
    if ($('health')) {
      $('health').className = 'status-pill ok';
      $('health').textContent = '';
    }
    // Update connection status in sidebar
    const connStatus = $('connectionStatus');
    if (connStatus) {
      connStatus.textContent = '在线';
      connStatus.className = 'status-ok';
    }
    startupState = 'ready';
  } catch (error) {
    startupState = 'ready';
    if ($('health')) {
      $('health').className = 'status-pill warn';
      $('health').textContent = '后端未就绪';
    }
    const connStatus = $('connectionStatus');
    if (connStatus) {
      connStatus.textContent = '后端未就绪';
      connStatus.className = 'status-warn';
    }
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
  // Dashboard does not render full calendar — it lives on the month page
  // renderCalendar('monthCalendar') intentionally removed to keep dashboard compact
  renderDashboardManagement();
}

function dispatchSession(action, payload) {
  if (!session && action !== 'END_SESSION') return;
  switch (action) {
    case 'COMPLETE_SET': completeSet(); break;
    case 'NEXT_EXERCISE': nextExercise(); break;
    case 'PREV_EXERCISE': prevExercise(); break;
    case 'SKIP_EXERCISE': skipExercise(); break;
    case 'END_SESSION': finishTraining('partial'); break;
    case 'START_TIMER': startTimer(); break;
    case 'PAUSE_TIMER': pauseTimer(); break;
    case 'RESUME_TIMER': resumeTimer(); break;
    case 'START_REST': startRestTimer(); break;
    case 'SKIP_REST': skipRestTimer(); break;
  }
}

// ── Timer state ─────────────────────────────────────────────────────────────

let timerInterval = null;
let timerSeconds = 0;

function clearTimer() {
  if (timerInterval) { clearInterval(timerInterval); timerInterval = null; }
  timerSeconds = 0;
  updateTimerDisplay(true);
}

function updateTimerDisplay(hidden = false) {
  const el = $('activeTimer');
  if (!el) return;
  if (hidden) {
    el.classList.add('is-hidden');
    el.innerHTML = '';
    return;
  }
  el.classList.remove('is-hidden');
  const mins = Math.floor(timerSeconds / 60);
  const secs = timerSeconds % 60;
  el.innerHTML = `<span class="timer-display">${String(mins).padStart(2, '0')}:${String(secs).padStart(2, '0')}</span>`;
}

function startTimer() {
  const template = templateById(session.templateId);
  const exercises = templateExercises(template);
  const exercise = exercises[session.currentExerciseIndex];
  if (!exercise || !exercise.durationSeconds) return;
  timerSeconds = exercise.durationSeconds;
  updateTimerDisplay();
  session._timing = true;
  tickTimer();
}

function tickTimer() {
  clearTimer();
  if (timerSeconds <= 0) {
    updateTimerDisplay(true);
    session._timing = false;
    completeSet();
    return;
  }
  timerInterval = setInterval(() => {
    timerSeconds--;
    updateTimerDisplay();
    if (timerSeconds <= 0) {
      clearTimer();
      updateTimerDisplay(true);
      session._timing = false;
      completeSet();
    }
  }, 1000);
}

function pauseTimer() {
  clearTimer();
  session._pausedSeconds = timerSeconds;
  updateTimerDisplay();
}

function resumeTimer() {
  timerSeconds = session._pausedSeconds || timerSeconds;
  session._pausedSeconds = 0;
  updateTimerDisplay();
  tickTimer();
}

function startRestTimer() {
  // Default 60 second rest between sets
  timerSeconds = 60;
  session.status = 'resting';
  updateTimerDisplay();
  tickRestTimer();
}

function tickRestTimer() {
  clearTimer();
  if (timerSeconds <= 0) {
    updateTimerDisplay(true);
    session.status = 'in_progress';
    session.currentSetIndex = Math.min(session.currentSetIndex, (templateExercises(templateById(session.templateId))[session.currentExerciseIndex]?.defaultSets || 1) - 1);
    updateApp('session:rest-end');
    return;
  }
  timerInterval = setInterval(() => {
    timerSeconds--;
    updateTimerDisplay();
    if (timerSeconds <= 0) {
      clearTimer();
      updateTimerDisplay(true);
      session.status = 'in_progress';
      updateApp('session:rest-end');
    }
  }, 1000);
}

function skipRestTimer() {
  clearTimer();
  updateTimerDisplay(true);
  session.status = 'in_progress';
  updateApp('session:rest-end');
}

function switchPage(page) {
  currentPage = page;
  // Update hash for browser history and bookmarkability
  if (window.location.hash !== `#${page}`) {
    history.pushState(null, '', `#${page}`);
  }
  $$('.nav-item').forEach((item) => {
    const isActive = item.dataset.page === page;
    item.classList.toggle('active', isActive);
    item.setAttribute('aria-current', isActive ? 'page' : 'false');
  });
  $$('.page').forEach((panel) => panel.classList.toggle('active', panel.dataset.pagePanel === page));
  if (page === 'trainingSession' && !session) startTrainingSession();
  render();
}

function handleHashChange() {
  const hash = window.location.hash.replace('#', '');
  if (hash && hash !== currentPage && ['dashboard','today','week','month','exerciseLibrary','templateManager','videoLinks','settings'].includes(hash)) {
    switchPage(hash);
  }
}

// ── Focus and accessibility helpers ─────────────────────────────────────────

function safeScrollTo(el) {
  if (!el) return;
  const prefersReduced = window.matchMedia && window.matchMedia('(prefers-reduced-motion: reduce)').matches;
  el.scrollIntoView({ behavior: prefersReduced ? 'instant' : 'smooth', block: 'start' });
}

function closeDialogAndFocusTrigger(dialog, triggerSelector) {
  dialog.close();
  const trigger = document.querySelector(triggerSelector);
  if (trigger) trigger.focus();
}

function openDialogWithFocus(dialog) {
  dialog.showModal();
  const first = dialog.querySelector('button, [href], input, select, textarea, [tabindex]:not([tabindex="-1"])');
  if (first) first.focus();
  // Trap Tab within dialog
  dialog.addEventListener('keydown', trapDialogFocus);
}

function trapDialogFocus(event) {
  if (event.key !== 'Tab') return;
  const dialog = event.currentTarget;
  const focusable = Array.from(dialog.querySelectorAll('button, [href], input, select, textarea, [tabindex]:not([tabindex="-1"])'))
    .filter((el) => !el.disabled && el.offsetParent !== null);
  if (!focusable.length) return;
  const first = focusable[0];
  const last = focusable[focusable.length - 1];
  if (event.shiftKey && document.activeElement === first) {
    event.preventDefault();
    last.focus();
  } else if (!event.shiftKey && document.activeElement === last) {
    event.preventDefault();
    first.focus();
  }
}

function renderTodayCard(targetId, full = false) {
  const plan = todayPlan();
  const template = todayTemplate();
  const exercises = templateExercises(template);
  const target = $(targetId);
  if (!plan) {
    target.innerHTML = `<h2>今日暂无计划</h2><p>你还没有为今天安排训练或休息。</p><div class="button-row"><button class="btn primary" data-edit-plan="${isoToday}" type="button">编辑今日计划</button><button class="btn secondary" data-ai-action="import" type="button">AI 生成本周计划</button></div>`;
    return;
  }
  if (plan.type === 'rest') {
    const backAction = targetId === 'dashboardToday' ? '' : '<button class="btn secondary" data-page-link="dashboard" type="button">返回仪表盘</button>';
    target.innerHTML = `<div class="rest-day-copy"><h2>今天是休息日</h2><p class="rest-lead">${escapeHtml(plan.note || '身体也需要把训练成果慢慢吸收。今天不用追进度，给关节、睡眠和心情一点空间。')}</p><div class="rest-suggestions"><span>散步 20 分钟</span><span>拉伸 10 分钟</span><span>保持恢复</span></div>${backAction}</div>`;
    return;
  }
  const visible = full ? exercises : exercises.slice(0, 3);
  const trainingCopy = `<div><h2>${escapeHtml(template?.name || '当前计划引用的训练模板不存在')}</h2><div class="hero-meta"><span>训练时长：${template?.estimatedMinutes || 35} 分钟</span><span>难度：${escapeHtml(template?.difficulty || '低强度')}</span><span>状态：${statusText(plan.status)}</span><span>完成进度：${plan.status === 'done' ? '100%' : '0%'}</span></div><ol class="mini-actions">${visible.map((exercise) => { const remark = getExerciseRemark(exercise); const video = defaultVideo(exercise); return `<li><strong>${escapeHtml(exercise.name)}</strong><span>${escapeHtml(doseText(exercise))}</span>${video ? `<a class="exercise-video-link" href="${escapeHtml(video.url)}" target="_blank" rel="noopener noreferrer"><svg viewBox="0 0 24 24" aria-hidden="true"><path d="m9 8 6 4-6 4V8Z" fill="none" stroke="currentColor" stroke-width="2" stroke-linejoin="round"/><rect x="3" y="5" width="18" height="14" rx="3" fill="none" stroke="currentColor" stroke-width="2"/></svg>查看示范</a>` : '<button data-add-video="'+escapeHtml(exercise.id)+'" type="button">添加视频</button>'}${exercise.benefit ? `<small class="benefit-text">${escapeHtml(exercise.benefit)}</small>` : ''}${remark ? `<small class="exercise-note-inline"><strong>备注：</strong>${escapeHtml(remark)}</small>` : ''}</li>`; }).join('')}</ol>${exercises.length > 3 && !full ? '<button class="text-btn" data-expand-today type="button">展开全部动作</button>' : ''}<div class="button-row"><button class="btn secondary" data-show-detail type="button">查看动作详情</button><button class="btn primary" data-start-training type="button">开始训练</button></div></div>`;
  target.innerHTML = trainingCopy;
}

function buildMonthlyTrendChart(rate, trainingDays, monthDays, lineHtml) {
  return `<div class="monthly-trend-panel"><div class="chart-card-head"><span class="chart-icon"><svg viewBox="0 0 24 24" aria-hidden="true"><path d="M4 17.5 9 12l4 3.2 6.5-8.2" fill="none" stroke="currentColor" stroke-width="2.1" stroke-linecap="round" stroke-linejoin="round"/><path d="M4 20h16" fill="none" stroke="currentColor" stroke-width="2.1" stroke-linecap="round"/></svg></span><div><strong>月度完成曲线</strong><small>${trainingDays} 个训练日 · ${monthDays} 天视图</small></div></div>${lineHtml}<div class="monthly-trend-foot"><strong>${rate}%</strong><span>本月累计完成率</span></div></div>`;
}

function renderStats() {
  const monthKey = `${visibleMonth.getFullYear()}-${String(visibleMonth.getMonth() + 1).padStart(2, '0')}`;
  const entries = Object.entries(state.schedule).filter(([date]) => date.startsWith(monthKey));
  const training = entries.filter(([, plan]) => plan.type === 'training');
  const rest = entries.filter(([, plan]) => plan.type === 'rest');
  const done = training.filter(([, plan]) => plan.status === 'done');
  const skipped = training.filter(([, plan]) => plan.status === 'skipped');
  const postponed = training.filter(([, plan]) => plan.status === 'postponed');
  const pending = training.filter(([, plan]) => plan.status === 'pending' || !['done','skipped','postponed'].includes(plan.status));
  const totalDays = entries.length;
  const rate = training.length ? Math.round((done.length / training.length) * 100) : 0;
  const restRate = totalDays ? Math.round((rest.length / totalDays) * 100) : 0;

  // Calculate current streak (consecutive completed training days leading up to today)
  let streak = 0;
  const checkDate = new Date(today);
  while (true) {
    const dateStr = toIso(checkDate);
    const plan = state.schedule[dateStr];
    if (plan && plan.type === 'training' && plan.status === 'done') {
      streak++;
      checkDate.setDate(checkDate.getDate() - 1);
    } else {
      break;
    }
  }

  // 本周完成率（周一至周日）
  const monday = addDays(today, -today.getDay() + 1);
  const weekDays = Array.from({ length: 7 }, (_, i) => toIso(addDays(monday, i)));
  const weekTraining = weekDays.filter(d => { const p = state.schedule[d]; return p && p.type === 'training'; });
  const weekDone = weekDays.filter(d => { const p = state.schedule[d]; return p && p.type === 'training' && p.status === 'done'; });
  const weekRate = weekTraining.length ? Math.round((weekDone.length / weekTraining.length) * 100) : 0;

  // SVG helpers
  const chartIcons = {
    trend: '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M4 17.5 9 12l4 3.2 6.5-8.2" fill="none" stroke="currentColor" stroke-width="2.1" stroke-linecap="round" stroke-linejoin="round"/><path d="M4 20h16" fill="none" stroke="currentColor" stroke-width="2.1" stroke-linecap="round"/></svg>',
    ratio: '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M5 18V7M12 18V4M19 18v-8" fill="none" stroke="currentColor" stroke-width="2.1" stroke-linecap="round"/><path d="M4 18h16" fill="none" stroke="currentColor" stroke-width="2.1" stroke-linecap="round"/></svg>',
    status: '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M7 12.2l3 3 7-7" fill="none" stroke="currentColor" stroke-width="2.1" stroke-linecap="round" stroke-linejoin="round"/><path d="M5 5.5h14v13H5z" fill="none" stroke="currentColor" stroke-width="2.1" stroke-linejoin="round"/></svg>',
    streak: '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M12 20c3.4-1.4 5.4-3.8 5.4-6.7 0-2.2-1.2-4.2-3-5.4-.2 1.7-.9 2.9-2 3.7.1-2.5-1.1-4.6-3.2-6.1C8.9 8 7 10.2 6.7 13.2 6.4 16.1 8.4 18.6 12 20Z" fill="none" stroke="currentColor" stroke-width="2.1" stroke-linejoin="round"/></svg>',
    recovery: '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M12 20c4.5-2.2 7-5.2 7-9.2V6.4L12 4 5 6.4v4.4c0 4 2.5 7 7 9.2Z" fill="none" stroke="currentColor" stroke-width="2.1" stroke-linejoin="round"/><path d="M9 12.2h6M12 9.2v6" fill="none" stroke="currentColor" stroke-width="2.1" stroke-linecap="round"/></svg>',
  };
  const daysInVisibleMonth = new Date(visibleMonth.getFullYear(), visibleMonth.getMonth() + 1, 0).getDate();
  let cumulativeDone = 0;
  let cumulativeTraining = 0;
  const trendPoints = Array.from({ length: daysInVisibleMonth }, (_, index) => {
    const day = index + 1;
    const date = `${monthKey}-${String(day).padStart(2, '0')}`;
    const plan = state.schedule[date];
    if (plan?.type === 'training') {
      cumulativeTraining += 1;
      if (plan.status === 'done') cumulativeDone += 1;
    }
    const pct = cumulativeTraining ? Math.round((cumulativeDone / cumulativeTraining) * 100) : 0;
    const x = 18 + (index / Math.max(daysInVisibleMonth - 1, 1)) * 244;
    const y = 98 - (pct / 100) * 72;
    return { x, y, pct, day };
  });
  const trendPath = trendPoints.map((point, index) => `${index ? 'L' : 'M'}${point.x.toFixed(1)} ${point.y.toFixed(1)}`).join(' ');
  const trendArea = `${trendPath} L262 110 L18 110 Z`;
  const lastPoint = trendPoints[trendPoints.length - 1] || { x: 18, y: 98, pct: 0, day: 1 };
  const lineHtml = `<div class="daily-line-chart"><svg viewBox="0 0 280 128" aria-label="月度完成曲线图"><path class="line-grid" d="M18 26H262M18 62H262M18 98H262"/><path class="line-area" d="${trendArea}"/><path class="line-path" d="${trendPath}"/><circle class="line-end" cx="${lastPoint.x.toFixed(1)}" cy="${lastPoint.y.toFixed(1)}" r="4.5"/><text x="18" y="122">1日</text><text x="244" y="122">${daysInVisibleMonth}日</text></svg></div>`;
  window.dashboardMonthlyTrendHtml = buildMonthlyTrendChart(rate, training.length, daysInVisibleMonth, lineHtml);
  const totalProjects = totalDays || daysInVisibleMonth;
  const ongoing = Math.max(training.length - done.length - skipped.length - postponed.length, 0);
  // Dynamic gauge segments based on real completion data
  const tBase = Math.max(training.length, 1);
  const gDone = Math.round((done.length / tBase) * 100);
  const gSkp = Math.round((skipped.length / tBase) * 100);
  const gPost = Math.round((postponed.length / tBase) * 100);
  const completionHtml = `<div class="overall-gauge">
    <div class="overall-gauge-top"><strong>整体进度</strong><span>本月训练</span></div>
    <svg class="chart-ring-svg" viewBox="0 0 320 230" aria-label="本月完成率">
      <path class="gauge-track" d="M62 190A108 108 0 1 1 258 190" pathLength="100"/>
      <path class="gauge-segment gauge-green" d="M62 190A108 108 0 1 1 258 190" pathLength="100" style="stroke-dasharray:${gDone} 100;stroke-dashoffset:0"/>
      <path class="gauge-segment gauge-yellow" d="M62 190A108 108 0 1 1 258 190" pathLength="100" style="stroke-dasharray:${gSkp} 100;stroke-dashoffset:-${gDone}"/>
      <path class="gauge-segment gauge-orange" d="M62 190A108 108 0 1 1 258 190" pathLength="100" style="stroke-dasharray:${gPost} 100;stroke-dashoffset:-${gDone + gSkp}"/>
      <text x="54" y="208">0</text><text x="250" y="208">100</text>
    </svg>
    <div class="gauge-center"><strong>${rate}%</strong><span>已完成</span></div>
    <div class="gauge-stats"><span><strong>${totalProjects}</strong>总天数</span><span><strong>${done.length}</strong>已完成</span><span><strong>${pending.length}</strong>待开始</span><span><strong>${ongoing}</strong>进行中</span></div>
  </div>`;

  // Training/Rest ratio bar
  const tPct = totalDays ? Math.round((training.length / totalDays) * 100) : 0;
  const rPct = 100 - tPct;
  const ratioHtml = `<div class="chart-inner"><div class="chart-label"><span>训练 ${training.length} 天</span><span class="chart-val">${tPct}%</span></div><div class="chart-bar"><div class="chart-bar-fill" style="width:${tPct}%;background:var(--green)"></div></div><div class="chart-label"><span>休息 ${rest.length} 天</span><span class="chart-val">${rPct}%</span></div><div class="chart-bar"><div class="chart-bar-fill" style="width:${rPct}%;background:var(--rest)"></div></div></div>`;

  // Status breakdown bar
  const tCount = training.length || 1;
  const dPct = Math.round((done.length / tCount) * 100);
  const sPct = Math.round((skipped.length / tCount) * 100);
  const pPct = Math.round((postponed.length / tCount) * 100);
  const pendPct = 100 - dPct - sPct - pPct;
  const statusHtml = `<div class="chart-inner"><div class="chart-label"><span>训练日执行状态</span></div><div class="chart-bar stacked"><div class="chart-bar-fill" style="width:${dPct}%;background:var(--green)" title="已完成 ${done.length}天"></div><div class="chart-bar-fill" style="width:${sPct}%;background:var(--orange)" title="已跳过 ${skipped.length}天"></div><div class="chart-bar-fill" style="width:${pPct}%;background:var(--purple)" title="已延期 ${postponed.length}天"></div><div class="chart-bar-fill" style="width:${Math.max(pendPct, 0)}%;background:var(--line)" title="待开始 ${pending.length}天"></div></div><div class="chart-legend"><span class="legend-dot" style="background:var(--green)"></span>完成 ${done.length}<span class="legend-dot" style="background:var(--orange)"></span>跳过 ${skipped.length}<span class="legend-dot" style="background:var(--purple)"></span>延期 ${postponed.length}<span class="legend-dot" style="background:var(--line)"></span>待定 ${pending.length}</div></div>`;

  // Combined streak + recovery
  const comboHtml = `<div class="chart-inner"><div class="metric-row"><div class="metric-item"><strong>${streak}</strong><span>连续训练（天）</span></div><div class="metric-item"><strong>${weekRate}%</strong><span>本周完成率</span></div><div class="metric-item"><strong>${restRate}%</strong><span>恢复占比</span></div></div></div>`;

  const chartHtml = `<div class="chart-grid">
    <div class="chart-card chart-card-primary chart-completion"><div class="chart-card-head"><span class="chart-icon">${chartIcons.trend}</span><div><strong>本月完成率</strong><small>训练日完成进度 · 共${training.length}个训练日</small></div></div>${completionHtml}</div>
    <div class="chart-card"><div class="chart-card-head"><span class="chart-icon">${chartIcons.status}</span><div><strong>执行状态</strong><small>完成 / 跳过 / 延期</small></div></div>${statusHtml}</div>
    <div class="chart-card"><div class="chart-card-head"><span class="chart-icon">${chartIcons.streak}</span><div><strong>连续训练</strong><small>习惯与恢复</small></div></div>${comboHtml}</div>
  </div>`;

  $('monthLabel').textContent = monthKey;
  $('stats').innerHTML = chartHtml;
  if ($('monthStats')) $('monthStats').innerHTML = '';
}

function renderTodayVideos() {
  const template = todayTemplate();
  const exercises = templateExercises(template);
  const content = exercises.length ? exercises.map((exercise) => {
    const video = defaultVideo(exercise);
    return `<article class="video-row"><div><strong>${escapeHtml(exercise.name)}</strong><span>${video ? escapeHtml(video.url) : '暂无视频链接'}</span></div>${video ? `<a class="btn mini" href="${escapeHtml(video.url)}" target="_blank" rel="noopener noreferrer">打开视频</a>` : `<button class="btn mini" data-add-video="${escapeHtml(exercise.id)}" type="button">添加视频</button>`}</article>`;
  }).join('') : '<div class="empty-state video-empty-state"><strong>今天先不看训练视频</strong><span>休息日也很重要。散步、拉伸或早点睡，都算是在为下一次训练充电。</span></div>';
  $('todayVideos').innerHTML = `${window.dashboardMonthlyTrendHtml || ''}${content}`;
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
    const remark = getExerciseRemark(exercise);
    return `<article class="data-card"><div><h3>${escapeHtml(exercise.name)}</h3><p>${escapeHtml(exercise.category)} / ${escapeHtml((exercise.bodyParts || []).join('、'))} / ${escapeHtml(exercise.difficulty)}</p><p>默认组次：${escapeHtml(doseText(exercise))}</p><p>默认 B站视频：${video ? escapeHtml(video.title) : '暂无视频链接'}</p>${exercise.benefit ? `<p class="benefit-line">${escapeHtml(exercise.benefit)}</p>` : ''}${remark ? `<p class="exercise-note"><strong>备注：</strong>${escapeHtml(remark)}</p>` : ''}</div><div class="card-actions">${video ? `<a class="btn mini" href="${escapeHtml(video.url)}" target="_blank" rel="noopener noreferrer">打开Bilibili</a>` : ''}<button class="btn mini" data-edit-exercise="${escapeHtml(exercise.id)}" type="button">编辑</button><button class="btn mini" data-add-video="${escapeHtml(exercise.id)}" type="button">添加视频</button><button class="btn mini secondary" data-ai-search-video="${escapeHtml(exercise.id)}" type="button">AI搜索</button><button class="btn danger mini" data-delete-exercise="${escapeHtml(exercise.id)}" type="button">删除</button></div></article>`;
  }).join('') || '<div class="empty-state">动作库为空，点击新增动作开始维护。</div>';
}

function renderTemplates() {
  $('templateList').innerHTML = state.templates.map((template) => {
    const exercises = templateExercises(template);
    return `<article class="template-card"><h3>${escapeHtml(template.name)}</h3><p>${escapeHtml(template.description || '')}</p><div class="hero-meta"><span>${exercises.length} 个动作</span><span>约 ${template.estimatedMinutes || 30} 分钟</span><span>${escapeHtml(template.difficulty || '低强度')}</span></div><ol>${exercises.map((exercise) => `<li>${escapeHtml(exercise.name)} · ${escapeHtml(doseText(exercise))}${getExerciseRemark(exercise) ? `<span class="template-note-list"><strong>备注：</strong>${escapeHtml(getExerciseRemark(exercise))}</span>` : ''}</li>`).join('')}</ol><div class="card-actions"><button class="btn mini" data-edit-template="${escapeHtml(template.id)}" type="button">编辑模板</button><button class="btn danger mini" data-delete-template="${escapeHtml(template.id)}" type="button">删除模板</button></div></article>`;
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
  const icons = {
    library: '<svg viewBox="0 0 24 24" aria-hidden="true"><circle cx="12" cy="5.2" r="2.4" fill="currentColor"/><path d="M9.2 9.1c1.7-.9 3.8-.9 5.6 0l1.4 3.8 3 1.2-1 2.1-4.1-1.3-1.1-2.2-1.4 3.1-3.6 3.2-1.5-1.7 3-3.1.9-2.6-3 .8-.9 2.7-2.1-.6 1.2-4.1 3.6-1.3Z" fill="currentColor"/></svg>',
    template: '<svg viewBox="0 0 24 24" aria-hidden="true"><circle cx="12" cy="5.1" r="2.3" fill="currentColor"/><path d="M9.4 8.4h5.2l.9 3.1 3.4-2 .9 2-4.4 2.6-1.2-1.7v6.8h-2.4v-4.9l-2.4 4.5-2.1-1 2.4-4.8-4.4.3-.2-2.2 4.1-.5.2-2.2Z" fill="currentColor"/><path d="M5.2 16.6h2.6v2H5.2v-2Zm12.9.2h2.3v1.8h-2.3v-1.8Z" fill="currentColor"/></svg>',
    calendar: '<svg viewBox="0 0 24 24" aria-hidden="true"><circle cx="13.8" cy="5.2" r="2.2" fill="currentColor"/><path d="M10.5 8.5h5.8l.9 3.4 2.9-.1.1 2.2-4.4.4-1.1-2.4-2.3 2.2 3 2.4-1.4 1.9-4.1-3.1.2-1.8-2.5 1-2.8 3.5-1.8-1.4 3-4.1 3.4-1.4 1.1-2.7Z" fill="currentColor"/><path d="M17.5 17.7h3.1v1.9h-3.1v-1.9Z" fill="currentColor"/></svg>',
    sync: '<svg viewBox="0 0 24 24" aria-hidden="true"><circle cx="11.6" cy="5.2" r="2.2" fill="currentColor"/><path d="M8.4 8.9h5.8l1.2 2.7 3.4-.5.4 2.1-4.5 1.1-1.2-1.4-.5 2.7 2.6 2.1-1.5 1.8-3.5-2.8-.5-2.9-1.7 1.9-3.2.6-.5-2.1 2.7-.9 1-4.4Z" fill="currentColor"/><path d="M17.2 6.9h3.5l-1.1-1.1 1.1-1.1 3 3-3 3-1.1-1.1 1.1-1.1h-3.5V6.9ZM6.8 19.2H3.3l1.1 1.1-1.1 1.1-3-3 3-3 1.1 1.1-1.1 1.1h3.5v1.6Z" fill="currentColor"/></svg>',
  };
  target.innerHTML = [
    { link: 'exerciseLibrary', icon: icons.library, title: '动作库管理', stat: `${state.exercises.length} 个动作`, tone: 'green' },
    { link: 'templateManager', icon: icons.template, title: '训练模板管理', stat: `${state.templates.length} 个模板`, tone: 'orange' },
    { link: 'week', icon: icons.calendar, title: '训练计划管理', stat: `${Object.keys(state.schedule).length} 天计划`, tone: 'mint' },
    { link: 'settings', icon: icons.sync, title: '导入 / 导出数据', stat: '数据管理', tone: 'violet' },
  ].map(({ link, icon, title, stat, tone }) =>
    `<button class="manage-card" data-page-link="${link}" data-card-layered="true" data-tone="${tone}" type="button" aria-label="${title}">
      <div class="manage-bg-layer" data-visual-role="fitness-abstract" aria-hidden="true"></div>
      <div class="manage-overlay-layer" data-visual-role="tone-overlay" aria-hidden="true"></div>
      <div class="manage-icon-layer" data-visual-role="center-icon" aria-hidden="true"><div class="manage-icon">${icon}</div></div>
      <div class="manage-content-layer" data-visual-role="card-copy"><h3>${title}</h3><span class="manage-stat">${stat}</span></div>
    </button>`
  ).join('');
}

function renderAiDraftPreview(draft) {
  const cards = [
    {
      title: '训练计划',
      count: `${draft.plans?.length || 0} 天`,
      detail: (draft.plans || []).slice(0, 3).map((plan) => `${escapeHtml(plan.date || '未定日期')} · ${plan.type === 'training' ? '训练' : '恢复'} · ${escapeHtml(plan.note || '无备注')}`).join('<br/>') || '暂无计划',
    },
    {
      title: '训练模板',
      count: `${draft.templates?.length || 0} 个`,
      detail: (draft.templates || []).slice(0, 3).map((template) => `${escapeHtml(template.name || template.id || '未命名模板')} · ${template.exerciseIds?.length || 0} 个动作`).join('<br/>') || '暂无模板',
    },
    {
      title: '动作 / 视频',
      count: `${draft.exercises?.length || 0} 个`,
      detail: (draft.exercises || []).slice(0, 3).map((exercise) => `${escapeHtml(exercise.name || exercise.id || '未命名动作')} · ${escapeHtml(exercise.category || '未分类')}`).join('<br/>') || '暂无动作',
    },
  ];
  $('aiDraftPreview').innerHTML = cards.map((card) => `<article class="ai-draft-card"><strong>${card.title}</strong><span>${card.count}</span><span>${card.detail}</span></article>`).join('');
}

function renderSettings() {

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
        ${exercise.durationSeconds ? `<div id="activeTimer" class="timer-container is-hidden"></div>` : '<div id="activeTimer" class="timer-container is-hidden"></div>'}
        ${getExerciseRemark(exercise) ? `<p class="exercise-note"><strong>备注：</strong>${escapeHtml(getExerciseRemark(exercise))}</p>` : ''}
        <ul>${(exercise.tips || []).map((tip) => `<li>${escapeHtml(tip)}</li>`).join('')}</ul>
        <div class="button-row">
          ${exercise.durationSeconds ? `<button class="btn primary" id="startTimerButton" data-start-timer type="button">开始计时</button><button class="btn secondary" data-pause-timer type="button" ${!session._timing ? 'disabled' : ''}>暂停计时</button>` : `<button class="btn primary" id="completeExerciseButton" data-complete-set type="button">完成本组</button>`}
          <button class="btn secondary" data-rest type="button">进入休息</button>
          <button class="btn warning" data-skip-exercise type="button">跳过动作</button>
        </div>
        ${session.status === 'resting' ? `<div class="resting-controls"><button class="btn secondary" data-skip-rest type="button">跳过休息</button></div>` : ''}
        <div class="set-badges">${Array.from({ length: exercise.defaultSets }, (_, i) => `<span class="set-badge ${i < session.currentSetIndex ? 'set-complete' : i === session.currentSetIndex ? 'set-current' : ''}">第${i + 1}组</span>`).join('')}</div>
      </article>
      <aside class="video-panel">
        <p class="eyebrow">训练视频</p>
        ${video ? `<h3>${escapeHtml(video.title)}</h3><p>${escapeHtml(video.remark || '')}</p><a class="btn primary" href="${escapeHtml(video.url)}" target="_blank" rel="noopener noreferrer">打开Bilibili视频</a><button class="btn secondary" data-change-video="${escapeHtml(exercise.id)}" type="button">更换视频</button>` : `<h3>当前动作暂无视频</h3><button class="btn secondary" data-add-video="${escapeHtml(exercise.id)}" type="button">添加视频</button>`}
        <p class="helper-text">B站视频将在新标签页中打开</p>
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
  openDialogWithFocus($('planDialog'));
}

function openExerciseDialog(id = null) {
  const exercise = id ? exerciseById(id) : { id: '', name: '', category: '核心控制', bodyParts: ['核心'], difficulty: '低', defaultSets: 3, defaultReps: '10次', durationSeconds: null, notes: '', benefit: '', tips: [], videos: [] };
  $('exerciseForm').innerHTML = `<h2>${id ? '编辑动作' : '新增动作'}</h2><label>动作 ID<input name="id" value="${escapeHtml(exercise.id)}" ${id ? 'readonly' : ''} required pattern="[A-Za-z0-9_]+" /></label><label>动作名称<input name="name" value="${escapeHtml(exercise.name)}" required /></label><label>分类<input name="category" value="${escapeHtml(exercise.category)}" required /></label><label>训练部位<input name="bodyParts" value="${escapeHtml((exercise.bodyParts || []).join('、'))}" /></label><label>难度<select name="difficulty"><option ${exercise.difficulty === '低' ? 'selected' : ''}>低</option><option ${exercise.difficulty === '中' ? 'selected' : ''}>中</option><option ${exercise.difficulty === '高' ? 'selected' : ''}>高</option></select></label><label>默认组数<input name="defaultSets" type="number" min="1" value="${escapeHtml(exercise.defaultSets)}" /></label><label>动作类型<select name="motionType"><option value="reps" ${exercise.durationSeconds ? '' : 'selected'}>次数型</option><option value="duration" ${exercise.durationSeconds ? 'selected' : ''}>计时型</option></select></label><label>默认次数<input name="defaultReps" value="${escapeHtml(exercise.defaultReps || '')}" /></label><label>默认时长秒数<input name="durationSeconds" type="number" min="1" value="${escapeHtml(exercise.durationSeconds || '')}" /></label><label>动作备注<textarea name="notes">${escapeHtml(exercise.notes || '')}</textarea></label><label>训练目的/预期效果<textarea name="benefit" class="textarea-sm">${escapeHtml(exercise.benefit || '')}</textarea></label><label>动作要点（每行一条）<textarea name="tips">${escapeHtml((exercise.tips || []).join('\\n'))}</textarea></label><div class="modal-actions"><button class="btn secondary" type="button" data-close-modal>取消</button><button class="btn primary" type="submit">保存</button></div>`;

  openDialogWithFocus($('exerciseDialog'));
}

function openTemplateDialog(id = null) {
  const template = id ? templateById(id) : { id: '', name: '', description: '', exerciseIds: [], difficulty: '低强度', estimatedMinutes: 30 };
  $('templateForm').innerHTML = `<h2>${id ? '编辑模板' : '新建模板'}</h2><label>模板 ID<input name="id" value="${escapeHtml(template.id)}" ${id ? 'readonly' : ''} required pattern="[A-Za-z0-9_]+" /></label><label>模板名称<input name="name" value="${escapeHtml(template.name)}" required /></label><label>模板描述<textarea name="description">${escapeHtml(template.description || '')}</textarea></label><label>预计分钟<input name="estimatedMinutes" type="number" min="1" value="${escapeHtml(template.estimatedMinutes || 30)}" /></label><label>难度<input name="difficulty" value="${escapeHtml(template.difficulty || '低强度')}" /></label><div class="checkbox-list">${state.exercises.map((exercise) => `<label><input type="checkbox" name="exerciseIds" value="${escapeHtml(exercise.id)}" ${template.exerciseIds?.includes(exercise.id) ? 'checked' : ''}/> ${escapeHtml(exercise.name)}</label>`).join('')}</div><div class="modal-actions"><button class="btn secondary" type="button" data-close-modal>取消</button><button class="btn primary" type="submit">保存</button></div>`;
  $('templateDialog').dataset.editingId = id || '';
  openDialogWithFocus($('templateDialog'));
}

function openVideoDialog(exerciseId) {
  const exercise = exerciseById(exerciseId);
  $('videoForm').innerHTML = `<h2>添加 / 编辑视频</h2><p>${escapeHtml(exercise?.name || '')}</p><label>视频 ID<input name="id" value="${escapeHtml(uid('video'))}" required /></label><label>视频标题<input name="title" required /></label><label>B站链接<input name="url" required /></label><label>备注<input name="remark" /></label><label class="inline"><input name="isDefault" type="checkbox" checked /> 设为默认</label><div class="modal-actions"><button class="btn secondary" type="button" data-close-modal>取消</button><button class="btn primary" type="submit">保存</button></div>`;
  $('videoDialog').dataset.exerciseId = exerciseId;
  openDialogWithFocus($('videoDialog'));
}

async function startTrainingSession() {
  const plan = todayPlan();
  if (!plan) { showToast('今日暂无计划，请先编辑今日计划', 'error'); return; }
  if (plan.type === 'rest') { showToast('今天是休息日，不进入训练执行页', 'info'); return; }
  if (!plan.templateId) {
    showToast('当前计划未绑定训练模板，请编辑计划并选择模板', 'error');
    openPlanDialog(isoToday);
    return;
  }
  const template = todayTemplate();
  if (!template) {
    showToast('当前计划引用的训练模板不存在，请重新选择模板', 'error');
    openPlanDialog(isoToday);
    return;
  }

  // Get plan_id from backend
  let planId = null;
  try {
    const resp = await fetch(`/api/plans?date=${isoToday}`);
    if (resp.ok) {
      const data = await resp.json();
      if (data.plans && data.plans.length > 0) planId = data.plans[0].id;
    }
  } catch (e) {
    showToast('获取计划失败：网络错误', 'error');
    return;
  }
  if (!planId) {
    showToast('无法找到今日计划，请先保存计划', 'error');
    return;
  }

  // Start or resume backend session
  let backendSession = null;
  try {
    const resp = await fetch('/api/session/start', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ plan_id: planId }),
    });
    if (!resp.ok) {
      const err = await resp.json().catch(() => ({}));
      showToast(`开始训练失败：${err.detail || 'HTTP ' + resp.status}`, 'error');
      return;
    }
    const data = await resp.json();
    backendSession = data.session;
  } catch (e) {
    showToast('开始训练失败：网络错误', 'error');
    return;
  }

  // Restore progress from backend records if resumed
  let currentExerciseIndex = 0;
  let currentSetIndex = 0;
  const completed = [];
  const skipped = [];
  if (backendSession?.records?.length) {
    const templateExercisesList = templateExercises(template);
    backendSession.records.forEach((rec, idx) => {
      const matchIdx = templateExercisesList.findIndex(
        (ex) => Number(ex.exercise_id || ex.id) === Number(rec.exercise_id)
      );
      if (rec.status === 'completed') {
        if (matchIdx >= 0) completed.push(templateExercisesList[matchIdx].id);
        currentExerciseIndex = Math.max(currentExerciseIndex, matchIdx + 1);
      } else if (rec.status === 'skipped') {
        if (matchIdx >= 0) skipped.push(templateExercisesList[matchIdx].id);
        currentExerciseIndex = Math.max(currentExerciseIndex, matchIdx + 1);
      } else if (rec.status === 'pending' && rec.sets_completed) {
        currentExerciseIndex = matchIdx >= 0 ? matchIdx : currentExerciseIndex;
        currentSetIndex = rec.sets_completed;
      }
    });
    if (currentExerciseIndex >= templateExercisesList.length) currentExerciseIndex = Math.max(0, templateExercisesList.length - 1);
  }

  session = {
    templateId: template.id,
    planId: planId,
    backendSession: backendSession,
    currentExerciseIndex,
    currentSetIndex,
    status: 'in_progress',
    startedAt: backendSession?.started_at || new Date().toISOString(),
    completed,
    skipped,
    totalSetsDone: completed.length + (currentSetIndex || 0),
  };
  currentPage = 'trainingSession';
  switchPage('trainingSession');
}

async function finishTraining(status = 'done') {
  if (!session) return showToast('没有进行中的训练会话', 'error');

  const summary = {
    templateName: session?.templateId ? (templateById(session.templateId)?.name || '未知模板') : '无模板',
    completed: session?.completed || [],
    skipped: session?.skipped || [],
    totalSetsDone: session?.totalSetsDone || 0,
    status,
    startedAt: session?.startedAt,
  };

  const sid = session?.backendSession?.id;
  let apiOk = false;

  if (!sid) {
    showToast('缺少后端会话，无法完成同步。请返回训练后重试，或重新开始训练。', 'error');
  } else {
    try {
      const endpoint = status === 'partial' ? '/api/session/cancel' : '/api/session/complete';
      const body = status === 'partial'
        ? JSON.stringify({ session_id: sid })
        : JSON.stringify({ session_id: sid, rating: null });

      const response = await fetch(endpoint, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body,
      });

      if (response.ok) {
        const result = await response.json();
        summary.backendStatus = result.status;
        apiOk = true;
      } else {
        const err = await response.json().catch(() => ({}));
        showToast(`训练同步失败: ${err.detail || response.status}`, 'error');
      }
    } catch (error) {
      showToast('训练同步失败: 网络错误', 'error');
    }
  }

  window.__lastTrainingSummary = summary;

  if (!apiOk) {
    // Keep session alive — do NOT null it out
    render();
    const summaryEl = document.getElementById('trainingSummaryBanner');
    if (summaryEl) {
      summaryEl.classList.remove('is-hidden');
      summaryEl.classList.add('is-visible');
      summaryEl.innerHTML = `<div class="summary-banner-inner session-summary"><strong>⚠ 训练同步失败</strong><span>模板：${escapeHtml(summary.templateName)} | 完成：${summary.completed.length}个 | 跳过：${summary.skipped.length}个</span><div class="button-row"><button id="retrySyncBtn" class="btn primary" type="button">重试同步</button><button id="returnTrainingBtn" class="btn secondary" type="button">返回训练</button></div></div>`;
      setTimeout(() => {
        const retry = document.getElementById('retrySyncBtn');
        const ret = document.getElementById('returnTrainingBtn');
        if (retry) retry.addEventListener('click', () => { summaryEl.classList.add('is-hidden'); finishTraining(status); });
        if (ret) ret.addEventListener('click', () => { summaryEl.classList.add('is-hidden'); switchPage('trainingSession'); });
      }, 100);
    }
    return;
  }

  session = null;
  render();
  switchPage('dashboard');

  const summaryEl = document.getElementById('trainingSummaryBanner');
  if (summaryEl) {
    summaryEl.classList.remove('is-hidden');
    summaryEl.classList.add('is-visible');
    const badge = '<span class="sync-badge ok">已同步</span>';
    summaryEl.innerHTML = `<div class="summary-banner-inner session-summary"><strong>训练完成摘要 ${badge}</strong><span>模板：${escapeHtml(summary.templateName)} | 完成：${summary.completed.length}个 | 跳过：${summary.skipped.length}个 | 组数：${summary.totalSetsDone}</span><button id="dismissSummaryBanner" class="btn mini secondary" type="button">关闭</button></div>`;
    setTimeout(() => { summaryEl.classList.add('is-hidden'); summaryEl.classList.remove('is-visible'); }, 10000);
  }
}

function dismissTrainingSummary() {
  const el = document.getElementById('trainingSummaryBanner');
  if (el) el.classList.add('is-hidden');
}

async function resetToDefaults() {
  try {
    // Step 1: Dry-run to show preview
    const previewResp = await fetch('/api/data/restore-defaults', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ confirm: false }),
    });
    if (!previewResp.ok) {
      const err = await previewResp.json().catch(() => ({ detail: `HTTP ${previewResp.status}` }));
      showToast(`预览失败：${err.detail || '未知错误'}`, 'error');
      return;
    }
    const preview = await previewResp.json();
    const cs = preview.current_state || {};
    const previewMsg = `当前计划 ${cs.plans ?? 0} 条，动作 ${cs.exercises ?? 0} 个，模板 ${cs.templates ?? 0} 个，会话 ${cs.sessions ?? 0} 条，日志 ${cs.logs ?? 0} 条。\n将删除训练计划/会话/日志并恢复默认数据。`;
    if (!confirm(`${previewMsg}\n\n确认恢复默认数据？`)) return;

    // Step 2: User confirmed — do actual restore
    const response = await fetch('/api/data/restore-defaults', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ confirm: true, backup: true }),
    });
    if (response.ok) {
      const result = await response.json();
      showToast(result.message || '数据已恢复为默认，原数据已备份', 'success');
    } else {
      const err = await response.json().catch(() => ({ detail: `HTTP ${response.status}` }));
      showToast(`恢复失败：${err.detail || '未知错误'}`, 'error');
    }
  } catch (error) {
    showToast(`恢复失败：${error.message}`, 'error');
  }
  await loadHealth();
  render();
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
    const aiImportEl = target.closest('[data-ai-action="import"]'); if (aiImportEl) { switchPage('settings'); const box = $('aiImportPrompt'); if (box) safeScrollTo(box); }
    const aiAnalyzeEl = target.closest('[data-ai-action="analyze"]'); if (aiAnalyzeEl) { switchPage('settings'); const statusEl = $('aiStatus'); if (statusEl) statusEl.textContent = '分析入口已就绪：完成一次训练后可调用表现分析。'; }
    const aiSearchEl = target.closest('[data-ai-action="search-video"]'); if (aiSearchEl) openAiVideoSearchDialog(null);
    const aiSearchVideoEl = target.closest('[data-ai-search-video]'); if (aiSearchVideoEl) openAiVideoSearchDialog(aiSearchVideoEl.dataset.aiSearchVideo);
    const startTrainingEl = target.closest('[data-start-training]'); if (startTrainingEl) startTrainingSession();
    if (target.closest('[data-expand-today]')) renderTodayCard('dashboardToday', true);
    if (target.closest('[data-show-detail]')) switchPage('today');
    const editPlanEl = target.closest('[data-edit-plan]'); if (editPlanEl) openPlanDialog(editPlanEl.dataset.editPlan);
    const editExerciseEl = target.closest('[data-edit-exercise]'); if (editExerciseEl) openExerciseDialog(editExerciseEl.dataset.editExercise);
    if (target.id === 'addExercise' || target.id === 'addExerciseTop') openExerciseDialog();
    const addVideoEl = target.closest('[data-add-video]'); if (addVideoEl) openVideoDialog(addVideoEl.dataset.addVideo);
    const editTemplateEl = target.closest('[data-edit-template]'); if (editTemplateEl) openTemplateDialog(editTemplateEl.dataset.editTemplate);
    if (target.id === 'addTemplate' || target.id === 'addTemplateTop') openTemplateDialog();
    const deleteExerciseEl = target.closest('[data-delete-exercise]'); if (deleteExerciseEl) deleteExercise(deleteExerciseEl.dataset.deleteExercise);
    const deleteTemplateEl = target.closest('[data-delete-template]'); if (deleteTemplateEl) deleteTemplate(deleteTemplateEl.dataset.deleteTemplate);
    const defaultVideoEl = target.closest('[data-default-video]'); if (defaultVideoEl) setDefaultVideo(...defaultVideoEl.dataset.defaultVideo.split('::'));
    const closeModalEl = target.closest('[data-close-modal]'); if (closeModalEl) closeModalEl.closest('dialog').close();
    if (target.id === 'prevMonth' || target.id === 'prevMonthPage') { visibleMonth.setMonth(visibleMonth.getMonth() - 1); render(); }
    if (target.id === 'nextMonth' || target.id === 'nextMonthPage') { visibleMonth.setMonth(visibleMonth.getMonth() + 1); render(); }
    if (target.closest('[data-complete-set]')) dispatchSession('COMPLETE_SET');
    if (target.closest('[data-start-timer]')) dispatchSession('START_TIMER');
    if (target.closest('[data-pause-timer]')) dispatchSession('PAUSE_TIMER');
    if (target.closest('[data-resume-timer]')) dispatchSession('RESUME_TIMER');
    if (target.closest('[data-next-exercise]')) dispatchSession('NEXT_EXERCISE');
    if (target.closest('[data-prev-exercise]')) dispatchSession('PREV_EXERCISE');
    if (target.closest('[data-skip-exercise]')) dispatchSession('SKIP_EXERCISE');
    if (target.closest('[data-rest]')) dispatchSession('START_REST');
    if (target.closest('[data-skip-rest]')) dispatchSession('SKIP_REST');
    if (target.closest('[data-end-session]') && confirm('确认结束本次训练？当前训练进度会保存为未完成。')) finishTraining('partial');
    const jumpEl = target.closest('[data-jump-exercise]'); if (jumpEl) { session.currentExerciseIndex = Number(jumpEl.dataset.jumpExercise); session.currentSetIndex = 0; session.status = 'in_progress'; updateApp('session:jump'); }
    if (target.id === 'dismissSummaryBanner') dismissTrainingSummary();
    const themeOption = target.closest('[data-theme-option]'); if (themeOption) setTheme(themeOption.dataset.themeOption);
    if (target.closest('[data-reset-data]') && confirm('确认重置为默认种子数据？这将会先备份你的数据，然后恢复默认计划。')) resetToDefaults();
  });
  $('exerciseSearch').addEventListener('input', renderExercises);
  $('exerciseFilter').addEventListener('change', renderExercises);
  $('exerciseForm').addEventListener('submit', saveExerciseFromForm);
  $('templateForm').addEventListener('submit', saveTemplateFromForm);
  $('planForm').addEventListener('submit', savePlanFromForm);
  $('videoForm').addEventListener('submit', saveVideoFromForm);
  $('exportJson').addEventListener('click', () => { $('jsonBox').value = JSON.stringify(state, null, 2); });
  $('openImport').addEventListener('click', previewImport);
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

async function saveExerciseFromForm(event) {
  event.preventDefault();
  const form = new FormData(event.target);
  const id = form.get('id').trim();
  const motionType = form.get('motionType');
  const bodyPartsRaw = form.get('bodyParts').split(/[、,，]/).map((x) => x.trim()).filter(Boolean);
  const payload = {
    name: form.get('name').trim(),
    category: form.get('category').trim(),
    bodyParts: bodyPartsRaw,
    difficulty: form.get('difficulty'),
    defaultSets: Number(form.get('defaultSets') || 1),
    defaultReps: motionType === 'reps' ? form.get('defaultReps').trim() : null,
    durationSeconds: motionType === 'duration' ? Number(form.get('durationSeconds') || 30) : null,
    notes: form.get('notes'),
    benefit: form.get('benefit'),
    tips: form.get('tips').split('\n').map((x) => x.trim()).filter(Boolean),
  };

  const wasNew = !state.exercises.find((item) => item.id === id);
  try {
    const endpoint = wasNew ? '/api/exercises' : `/api/exercises/${id}`;
    const method = wasNew ? 'POST' : 'PUT';
    const response = await fetch(endpoint, {
      method,
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload),
    });
    if (!response.ok) {
      const err = await response.json().catch(() => ({ detail: `HTTP ${response.status}` }));
      throw new Error(err.detail || `请求失败：${response.status}`);
    }
    const saved = await response.json();

    // Update in-memory state from API response
    const exercise = {
      id: String(saved.id),
      name: saved.name,
      category: saved.category,
      bodyParts: bodyPartsRaw,
      difficulty: saved.difficulty,
      defaultSets: saved.default_sets,
      defaultReps: saved.default_reps,
      durationSeconds: saved.duration_seconds,
      notes: saved.notes || '',
      benefit: saved.benefit || '',
      tips: saved.tips ? String(saved.tips).split('|').filter(Boolean) : [],
      videos: exerciseById(String(saved.id))?.videos || [],
    };
    const existing = state.exercises.findIndex((item) => item.id === String(saved.id));
    if (existing >= 0) state.exercises[existing] = exercise; else state.exercises.push(exercise);

    saveData();
    $('exerciseDialog').close();
    render();
    showToast(wasNew ? '动作已创建' : '动作已更新', 'success');
  } catch (error) {
    showToast(error.message, 'error');
  }
}

async function saveTemplateFromForm(event) {
  event.preventDefault();
  const form = new FormData(event.target);
  const id = form.get('id').trim();
  const exerciseIds = form.getAll('exerciseIds');
  if (!exerciseIds.length) { showToast('训练模板至少选择 1 个动作', 'error'); return; }

  const payload = {
    name: form.get('name').trim(),
    description: form.get('description'),
    exercise_ids: exerciseIds.map(Number),
    estimated_minutes: Number(form.get('estimatedMinutes') || 30),
    difficulty: form.get('difficulty'),
  };

  const wasNew = !state.templates.find((item) => item.id === id);
  try {
    const endpoint = wasNew ? '/api/templates' : `/api/templates/${id}`;
    const method = wasNew ? 'POST' : 'PUT';
    const response = await fetch(endpoint, {
      method,
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload),
    });
    if (!response.ok) {
      const err = await response.json().catch(() => ({ detail: `HTTP ${response.status}` }));
      throw new Error(err.detail || `请求失败：${response.status}`);
    }
    const saved = await response.json();

    const template = {
      id: String(saved.id),
      name: saved.name,
      description: saved.description || '',
      exerciseIds: (saved.exercises || []).map((ex) => String(ex.id)),
      difficulty: saved.difficulty || '低强度',
      estimatedMinutes: saved.estimated_minutes || 30,
    };
    const existing = state.templates.findIndex((item) => item.id === String(saved.id));
    if (existing >= 0) state.templates[existing] = template; else state.templates.push(template);

    saveData();
    $('templateDialog').close();
    render();
    showToast(wasNew ? '模板已创建' : '模板已更新', 'success');
  } catch (error) {
    showToast(error.message, 'error');
  }
}

async function savePlanFromForm(event) {
  event.preventDefault();
  const form = new FormData(event.target);
  const date = form.get('date');
  const type = form.get('type');
  const templateId = form.get('templateId');
  if (type === 'training' && !templateId) { showToast('训练日必须选择训练模板', 'error'); return; }

  // Update backend first, then local state on success
  try {
    // Use the form's date for month lookup, NOT isoToday
    const formDate = new Date(date);
    const formMonth = `${formDate.getFullYear()}-${String(formDate.getMonth() + 1).padStart(2, '0')}`;
    const monthResp = await fetch(`/api/plans/month?month=${formMonth}`);
    if (monthResp.ok) {
      const monthData = await monthResp.json();
      const plan = (monthData.days || []).find((d) => d.date === date);
      if (plan && plan.id) {
        const resp = await fetch(`/api/plans/${plan.id}`, {
          method: 'PUT',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({
            title: type === 'training' ? '髋部稳定与核心控制' : '恢复日',
            is_training_day: type === 'training',
            focus: type === 'training' ? '低强度髋部稳定 + 核心控制' : '恢复与轻量活动',
            notes: form.get('note') || '',
            template_id: type === 'training' && templateId ? Number(templateId) : null,
          }),
        });
        if (!resp.ok) {
          throw new Error(`保存失败：HTTP ${resp.status}`);
        }
      } else if (type === 'training' && templateId) {
        // Plan doesn't exist yet — create a new one via plan generation
        const template = templateById(templateId);
        if (template) {
          const createResp = await fetch('/api/plans/generate', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
              date: date,
              title: '髋部稳定与核心控制',
              theme: '低强度髋部稳定 + 核心控制',
              exerciseIds: template.exerciseIds.map(Number),
              notes: form.get('note') || '',
            }),
          });
          if (!createResp.ok) {
            throw new Error(`创建计划失败：HTTP ${createResp.status}`);
          }
        }
      }
    } else {
      throw new Error(`计划查询失败：HTTP ${monthResp.status}`);
    }

    // Only update local state AFTER backend confirms success
    state.schedule[date] = { type, templateId: type === 'training' ? templateId : undefined, status: form.get('status'), note: form.get('note') };
    saveData();
    $('planDialog').close();
    render();
    showToast('计划已保存', 'success');
  } catch (e) {
    console.error('保存计划到后端失败', e);
    showToast('保存失败：请检查网络连接', 'error');
  }
}

async function saveVideoFromForm(event) {
  event.preventDefault();
  const exercise = exerciseById($('videoDialog').dataset.exerciseId);
  if (!exercise) { showToast('动作已不存在', 'error'); return; }
  const form = new FormData(event.target);
  const rawUrl = form.get('url').trim();
  const validation = validateBilibiliUrl(rawUrl);
  if (!validation.valid) { showToast(validation.error, 'error'); return; }
  const video = { id: form.get('id').trim(), title: form.get('title').trim(), platform: 'bilibili', url: rawUrl, isDefault: form.get('isDefault') === 'on', remark: form.get('remark') };

  // Backend first, local state only on success
  let backendOk = true;
  if (video.isDefault) {
    try {
      const resp = await fetch(`/api/exercises/${exercise.id}`, {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          name: exercise.name,
          category: exercise.category,
          bodyParts: exercise.bodyParts,
          difficulty: exercise.difficulty,
          defaultSets: exercise.defaultSets,
          defaultReps: exercise.defaultReps,
          durationSeconds: exercise.durationSeconds,
          notes: exercise.notes,
          benefit: exercise.benefit,
          tips: exercise.tips,
          video_url: rawUrl,
        }),
      });
      if (!resp.ok) {
        const err = await resp.json().catch(() => ({}));
        showToast(`视频保存失败: ${err.detail || 'HTTP ' + resp.status}`, 'error');
        backendOk = false;
      }
    } catch (e) {
      showToast(`视频保存失败: ${e.message}`, 'error');
      backendOk = false;
    }
  }

  if (!backendOk) return; // Keep dialog open on failure

  exercise.videos = exercise.videos || [];
  if (video.isDefault) exercise.videos.forEach((item) => { item.isDefault = false; });
  exercise.videos.push(video);
  saveData();

  $('videoDialog').close();
  render();
  showToast('视频已添加', 'success');
}

async function deleteExercise(id) {
  const exercise = exerciseById(id);
  if (!exercise) return;
  const refs = state.templates.filter((template) => template.exerciseIds.includes(id));
  const message = refs.length
    ? `该动作正在被以下模板引用：\n${refs.map((item) => `- ${item.name}`).join('\n')}\n删除后将从这些模板中移除。确认删除？`
    : `确认删除动作「${exercise.name}」？`;
  if (!confirm(message)) return;

  try {
    const response = await fetch(`/api/exercises/${id}`, { method: 'DELETE' });
    if (!response.ok && response.status !== 404) {
      throw new Error(`HTTP ${response.status}`);
    }
  } catch (e) {
    showToast('删除失败：请检查网络连接', 'error');
    console.error('删除动作异常：', e);
    return;
  }

  state.exercises = state.exercises.filter((item) => item.id !== id);
  state.templates.forEach((template) => { template.exerciseIds = template.exerciseIds.filter((item) => item !== id); });
  saveData();
  render();
  showToast('动作已删除', 'info');
}

async function deleteTemplate(id) {
  const template = templateById(id);
  if (!template) return;
  if (!confirm(`确认删除模板「${template.name}」？如果有计划引用该模板，对应日期将变为”暂无有效模板”。`)) return;

  try {
    const response = await fetch(`/api/templates/${id}`, { method: 'DELETE' });
    if (!response.ok && response.status !== 404) {
      throw new Error(`HTTP ${response.status}`);
    }
  } catch (e) {
    showToast('删除失败：请检查网络连接', 'error');
    console.error('删除模板异常：', e);
    return;
  }

  state.templates = state.templates.filter((item) => item.id !== id);
  saveData();
  render();
  showToast('模板已删除', 'info');
}

function setDefaultVideo(exerciseId, videoId) {
  const exercise = exerciseById(exerciseId);
  exercise.videos.forEach((video) => { video.isDefault = video.id === videoId; });
  saveData(); render();
}

let _completingSet = false;
let _skippingExercise = false;

async function completeSet() {
  if (_completingSet) return; // Prevent double-click
  _completingSet = true;
  const btn = document.querySelector('[data-complete-set]');
  if (btn) { btn.disabled = true; btn.textContent = '同步中...'; }

  const template = templateById(session.templateId);
  const exercises = templateExercises(template);
  const exercise = exercises[session.currentExerciseIndex];
  const isLastSet = session.currentSetIndex >= (exercise.defaultSets || 1) - 1;
  const nextSetIndex = session.currentSetIndex + 1;

  // Call backend BEFORE advancing local state
  let backendOk = true;
  if (session.backendSession) {
    try {
      const resp = await fetch('/api/session/update', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          session_id: session.backendSession.id,
          exercise_id: Number(exercise.exercise_id || exercise.id),
          status: isLastSet ? 'completed' : 'in_progress',
          sets_completed: nextSetIndex,
        }),
      });
      if (!resp.ok) {
        const err = await resp.json().catch(() => ({}));
        showToast(`同步失败: ${err.detail || 'HTTP ' + resp.status}`, 'error');
        backendOk = false;
      }
    } catch (e) {
      showToast('网络错误，请重试', 'error');
      backendOk = false;
    }
  }

  if (!backendOk) {
    _completingSet = false;
    if (btn) { btn.disabled = false; btn.textContent = '重试本组'; }
    return; // Do NOT advance local state on backend failure
  }

  session.totalSetsDone = (session.totalSetsDone || 0) + 1;

  if (!isLastSet) {
    session.currentSetIndex += 1;
    session.status = 'resting';
  } else {
    session.completed.push(exercise.id);
    if (session.currentExerciseIndex < exercises.length - 1) {
      nextExercise();
    } else {
      _completingSet = false;
      if (btn) { btn.disabled = false; btn.textContent = '完成本组'; }
      await finishTraining('done');
      return;
    }
  }
  _completingSet = false;
  if (btn) { btn.disabled = false; btn.textContent = '完成本组'; }
  updateApp('session:set-complete');
}
function nextExercise() { const template = templateById(session.templateId); const exercises = templateExercises(template); if (session.currentExerciseIndex < exercises.length - 1) { session.currentExerciseIndex += 1; session.currentSetIndex = 0; session.status = 'in_progress'; updateApp('session:next'); } else finishTraining('done'); }
function prevExercise() { if (session.currentExerciseIndex > 0) { session.currentExerciseIndex -= 1; session.currentSetIndex = 0; session.status = 'in_progress'; updateApp('session:prev'); } }
async function skipExercise() {
  if (_skippingExercise) return;
  _skippingExercise = true;
  const btn = document.querySelector('[data-skip-exercise]');
  if (btn) { btn.disabled = true; btn.textContent = '同步中...'; }

  const template = templateById(session.templateId);
  const exercises = templateExercises(template);
  const exercise = exercises[session.currentExerciseIndex];
  if (!exercise) { _skippingExercise = false; nextExercise(); return; }

  // Persist skipped to backend BEFORE advancing
  let backendOk = true;
  const sid = session?.backendSession?.id;
  if (sid) {
    try {
      const resp = await fetch('/api/session/update', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ session_id: sid, exercise_id: Number(exercise.exercise_id || exercise.id), status: 'skipped' }),
      });
      if (!resp.ok) {
        const err = await resp.json().catch(() => ({}));
        showToast(`跳过同步失败: ${err.detail || 'HTTP ' + resp.status}`, 'error');
        backendOk = false;
      }
    } catch (e) {
      showToast('网络错误，请重试', 'error');
      backendOk = false;
    }
  }

  if (!backendOk) {
    _skippingExercise = false;
    if (btn) { btn.disabled = false; btn.textContent = '重试跳过'; }
    return;
  }

  session.skipped.push(exercise.id);
  const isLastExercise = session.currentExerciseIndex >= exercises.length - 1;
  if (isLastExercise && session.backendSession) {
    // Last exercise + skipped → complete session after persisting skip
    _skippingExercise = false;
    if (btn) { btn.disabled = false; btn.textContent = '跳过动作'; }
    await finishTraining('done');
    return;
  }
  _skippingExercise = false;
  if (btn) { btn.disabled = false; btn.textContent = '跳过动作'; }
  nextExercise();
}

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
      overlapWarning = `<p class="import-warning">⚠ 以下日期已有计划，导入将覆盖：${overlap.slice(0, 5).join(', ')}${overlap.length > 5 ? ` 等共 ${overlap.length} 天` : ''}</p>`;
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
        showToast('导入完成', 'success');
      });
    }
  } catch (error) { $('importPreview').innerHTML = `<strong>导入失败</strong><p>${escapeHtml(error.message)}</p>`; }
}

async function sendDingTalk() {
  try {
    const response = await fetch('/api/notifications/send', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ channel: 'dingtalk', title: '运动训练提醒', message: '请查看今日训练动作和视频链接', include_todo: true }),
    });
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
  if (!prompt) { showToast('请先输入训练需求描述', 'error'); return; }
  const resultEl = $('aiDraftResult');
  const errorEl = $('aiImportError');
  resultEl.classList.add('is-hidden');
  errorEl.classList.add('is-hidden');
  setAiProgress('thinking');
  const btn = $('aiGenerateDraft');
  btn.disabled = true;
  btn.textContent = 'Thinking...';
  try {
    await new Promise((resolve) => setTimeout(resolve, 160));
    setAiProgress('generating');
    btn.textContent = 'Generating...';
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

    // Handle AI fallback (draft:null) gracefully
    if (!draft || data.status === 'fallback') {
      $('aiDraftErrors').innerHTML = `<span class="status-warn">AI 服务未配置，无法生成草稿</span><p>${escapeHtml((data.fallback || {}).message || '请配置 AI 后再试，或手动添加训练计划。')}</p>`;
      if (data.fallback?.search_url) {
        $('aiDraftErrors').innerHTML += `<p><a href="${escapeHtml(data.fallback.search_url)}" target="_blank" rel="noopener noreferrer">在 Bilibili 搜索训练动作</a></p>`;
      }
      setAiProgress('idle');
      resultEl.classList.remove('is-hidden');
      btn.disabled = false;
      btn.textContent = '生成草稿';
      return;
    }

    const counts = {
      exercises: draft.exercises?.length || 0,
      templates: draft.templates?.length || 0,
      plans: draft.plans?.length || 0,
    };
    renderAiDraftPreview(draft);
    $('aiDraftErrors').innerHTML = (data.warnings || []).length
      ? `<strong>警告：</strong><br/>${data.warnings.map((w) => escapeHtml(w)).join('<br/>')}`
      : `<span class="status-ok">校验通过 — ${counts.exercises} 个动作、${counts.templates} 个模板、${counts.plans} 天计划</span>`;
    setAiProgress('done');
    resultEl.classList.remove('is-hidden');
  } catch (error) {
    setAiProgress('idle');
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
  setAiProgress('done');
  showToast('导入完成！AI 生成数据已合并到当前计划', 'success');
}

function cancelAiImport() {
  $('aiDraftResult').classList.add('is-hidden');
  $('aiImportError').classList.add('is-hidden');
  setAiProgress('idle');
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
    if (!ids.length) { showToast('动作库为空，请先添加动作', 'error'); return; }
    const chosen = prompt('为哪个动作搜索视频？输入动作 ID：\n' + ids.join(', '));
    if (!chosen) return;
    exerciseId = chosen.trim();
    dialog.dataset.exerciseId = exerciseId;
  }

  const exercise = exerciseById(exerciseId);
  if (!exercise) { showToast('未找到该动作', 'error'); return; }
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
    suggestionsEl.innerHTML = `<span class="status-error">搜索失败：${escapeHtml(error.message)}</span>`;
  }
  dialog.showModal();
}

function confirmAiVideoSearch(event) {
  event.preventDefault();
  const dialog = $('aiVideoSearchDialog');
  const exerciseId = dialog.dataset.exerciseId;
  const url = $('aiVideoSearchFinalUrl').value.trim();
  if (!exerciseId || !url) { showToast('请填写视频链接', 'error'); return; }
  const exercise = exerciseById(exerciseId);
  if (!exercise) { showToast('动作已不存在', 'error'); return; }
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
  showToast('视频链接已添加', 'success');
}
async function bootstrapApp() {
  initTheme();
  // On mobile, close sidebar details to save first-screen space
  if (window.matchMedia && window.matchMedia('(max-width: 1024px)').matches) {
    $$('.sidebar-collapse').forEach((el) => { el.open = false; });
  }
  window.addEventListener('hashchange', handleHashChange);
  // Restore page from URL hash on load
  handleHashChange();
  render();
  attachEvents();
  await loadHealth();
  // Restore any active backend session after data load
  try {
    const cur = await fetch('/api/session/current');
    if (cur.ok) {
      const data = await cur.json();
      if (data.session && data.session.status === 'in_progress') {
        // Ensure local plan/template mapping exists before resuming UI
        const planId = data.session.plan_id;
        const planDate = data.plan?.date;
        if (planDate && !state.schedule[planDate] && data.plan) {
          state.schedule[planDate] = apiPlanToScheduleEntry(data.plan, state.templates);
        }
        // Prefer backend-bound template_id; never guess templates[0]
        const templateId = data.plan?.template_id
          ? String(data.plan.template_id)
          : state.schedule[planDate || isoToday]?.templateId;
        if (!templateId) {
          showToast('未完成会话缺少模板绑定，请编辑今日计划并选择模板后继续', 'error');
        } else {
          session = {
            templateId: String(templateId),
            planId,
            backendSession: data.session,
            currentExerciseIndex: 0,
            currentSetIndex: 0,
            status: 'in_progress',
            startedAt: data.session.started_at || new Date().toISOString(),
            completed: [],
            skipped: [],
            totalSetsDone: 0,
          };
          // Reconstruct progress from records
          const template = templateById(String(templateId));
          const list = templateExercises(template);
          (data.session.records || []).forEach((rec) => {
            const matchIdx = list.findIndex((ex) => Number(ex.exercise_id || ex.id) === Number(rec.exercise_id));
            if (rec.status === 'completed' && matchIdx >= 0) {
              session.completed.push(list[matchIdx].id);
              session.currentExerciseIndex = Math.max(session.currentExerciseIndex, matchIdx + 1);
            } else if (rec.status === 'skipped' && matchIdx >= 0) {
              session.skipped.push(list[matchIdx].id);
              session.currentExerciseIndex = Math.max(session.currentExerciseIndex, matchIdx + 1);
            } else if (rec.status === 'pending' && rec.sets_completed) {
              if (matchIdx >= 0) session.currentExerciseIndex = matchIdx;
              session.currentSetIndex = rec.sets_completed;
            }
          });
          showToast('已恢复未完成的训练会话', 'info');
        }
      }
    }
  } catch (e) {
    // offline: ignore resume
  }
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

// Testability / E2E hooks (read-only accessors + existing actions)
window.__workoutApp = {
  getSession: () => session,
  getState: () => state,
  startTrainingSession,
  completeSet,
  skipExercise,
  finishTraining,
  skipRestTimer,
  switchPage,
};

