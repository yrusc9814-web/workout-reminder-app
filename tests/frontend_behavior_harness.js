/**
 * Frontend behavior harness — mirrors critical app.js async flows with injectable fetch.
 * Used by tests/test_frontend_behavior.py. Keep logic aligned with static/app.js.
 */
'use strict';

function createHarness({ fetchImpl, confirmImpl, nowIso } = {}) {
  const calls = [];
  const fetchFn = fetchImpl || (async () => ({ ok: true, status: 200, json: async () => ({}) }));
  const confirmFn = confirmImpl || (() => true);
  const isoNow = nowIso || '2026-07-12T00:00:00.000Z';

  let state = {
    exercises: [],
    templates: [],
    schedule: {},
    logs: [],
  };
  let session = null;
  let toast = null;
  let dialogOpen = true;
  let _completingSet = false;
  let _skippingExercise = false;

  async function trackedFetch(url, options = {}) {
    const entry = {
      url: String(url),
      method: (options.method || 'GET').toUpperCase(),
      body: options.body ? JSON.parse(options.body) : null,
    };
    calls.push(entry);
    return fetchFn(url, options);
  }

  function showToast(message, type = 'info') {
    toast = { message, type };
  }

  function apiPlanToScheduleEntry(plan) {
    const isTraining = Boolean(plan.isTrainingDay ?? plan.is_training);
    let templateId;
    if (isTraining && plan.template_id) templateId = String(plan.template_id);
    return {
      type: isTraining ? 'training' : 'rest',
      templateId,
      status: plan.status || 'pending',
      note: plan.notes || '',
    };
  }

  function stateFromApiPayload(payload) {
    const exercises = (payload.exercises || []).map((e) => ({ id: String(e.id), name: e.name || '', exercise_id: e.id }));
    const templates = (payload.templates || []).map((t) => ({
      id: String(t.id),
      name: t.name || '',
      exerciseIds: (t.exercises || []).map((ex) => String(ex.id)),
    }));
    const schedule = {};
    (payload.plans || payload.days || []).forEach((plan) => {
      if (plan.date) schedule[plan.date] = apiPlanToScheduleEntry(plan);
    });
    return { version: '1.0', exercises, templates, schedule, logs: payload.logs || [] };
  }

  async function savePlanFromForm({ date, type, templateId, note, status = 'pending' }) {
    if (type === 'training' && !templateId) {
      showToast('训练日必须选择训练模板', 'error');
      return { ok: false };
    }
    const prev = JSON.parse(JSON.stringify(state.schedule[date] || null));
    try {
      const formDate = new Date(date + 'T00:00:00');
      const formMonth = `${formDate.getFullYear()}-${String(formDate.getMonth() + 1).padStart(2, '0')}`;
      const monthResp = await trackedFetch(`/api/plans/month?month=${formMonth}`);
      if (!monthResp.ok) throw new Error(`计划查询失败：HTTP ${monthResp.status}`);
      const monthData = await monthResp.json();
      const plan = (monthData.days || []).find((d) => d.date === date);
      if (plan && plan.id) {
        const resp = await trackedFetch(`/api/plans/${plan.id}`, {
          method: 'PUT',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({
            title: type === 'training' ? '髋部稳定与核心控制' : '恢复日',
            is_training_day: type === 'training',
            focus: type === 'training' ? '低强度髋部稳定 + 核心控制' : '恢复与轻量活动',
            notes: note || '',
            template_id: type === 'training' && templateId ? Number(templateId) : null,
          }),
        });
        if (!resp.ok) throw new Error(`保存失败：HTTP ${resp.status}`);
      } else if (type === 'training' && templateId) {
        const template = state.templates.find((t) => t.id === String(templateId));
        const createResp = await trackedFetch('/api/plans/generate', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({
            date,
            title: '髋部稳定与核心控制',
            theme: '低强度髋部稳定 + 核心控制',
            exerciseIds: (template?.exerciseIds || []).map(Number),
            notes: note || '',
          }),
        });
        if (!createResp.ok) throw new Error(`创建计划失败：HTTP ${createResp.status}`);
      }
      state.schedule[date] = { type, templateId: type === 'training' ? String(templateId) : undefined, status, note };
      dialogOpen = false;
      showToast('计划已保存', 'success');
      return { ok: true };
    } catch (e) {
      state.schedule[date] = prev;
      dialogOpen = true;
      showToast('保存失败：请检查网络连接', 'error');
      return { ok: false, error: String(e.message || e) };
    }
  }

  async function saveVideoFromForm({ exerciseId, url, isDefault = true }) {
    const exercise = state.exercises.find((e) => e.id === String(exerciseId));
    if (!exercise) {
      showToast('动作已不存在', 'error');
      return { ok: false };
    }
    const prevVideos = JSON.parse(JSON.stringify(exercise.videos || []));
    let backendOk = true;
    if (isDefault) {
      try {
        const resp = await trackedFetch(`/api/exercises/${exercise.id}`, {
          method: 'PUT',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ name: exercise.name, video_url: url }),
        });
        if (!resp.ok) {
          showToast(`视频保存失败: HTTP ${resp.status}`, 'error');
          backendOk = false;
        }
      } catch (e) {
        showToast(`视频保存失败: ${e.message}`, 'error');
        backendOk = false;
      }
    }
    if (!backendOk) {
      exercise.videos = prevVideos;
      dialogOpen = true;
      return { ok: false };
    }
    exercise.videos = exercise.videos || [];
    exercise.videos.push({ url, isDefault: true });
    dialogOpen = false;
    showToast('视频已添加', 'success');
    return { ok: true };
  }

  async function completeSet() {
    if (_completingSet) return { skipped: true };
    _completingSet = true;
    const exercise = session.exercises[session.currentExerciseIndex];
    const isLastSet = session.currentSetIndex >= (exercise.defaultSets || 1) - 1;
    const nextSetIndex = session.currentSetIndex + 1;
    let backendOk = true;
    if (session.backendSession) {
      try {
        const resp = await trackedFetch('/api/session/update', {
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
          showToast(`同步失败: HTTP ${resp.status}`, 'error');
          backendOk = false;
        }
      } catch (e) {
        showToast('网络错误，请重试', 'error');
        backendOk = false;
      }
    }
    if (!backendOk) {
      _completingSet = false;
      return { ok: false, advanced: false };
    }
    session.totalSetsDone = (session.totalSetsDone || 0) + 1;
    if (!isLastSet) {
      session.currentSetIndex += 1;
      session.status = 'resting';
    } else {
      session.completed.push(exercise.id);
      session.currentExerciseIndex += 1;
      session.currentSetIndex = 0;
      session.status = 'in_progress';
    }
    _completingSet = false;
    return { ok: true, advanced: true };
  }

  async function skipExercise() {
    if (_skippingExercise) return { skipped: true };
    _skippingExercise = true;
    const exercise = session.exercises[session.currentExerciseIndex];
    const beforeIndex = session.currentExerciseIndex;
    let backendOk = true;
    if (session.backendSession) {
      try {
        const resp = await trackedFetch('/api/session/update', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({
            session_id: session.backendSession.id,
            exercise_id: Number(exercise.exercise_id || exercise.id),
            status: 'skipped',
          }),
        });
        if (!resp.ok) {
          showToast(`跳过同步失败: HTTP ${resp.status}`, 'error');
          backendOk = false;
        }
      } catch (e) {
        showToast('网络错误，请重试', 'error');
        backendOk = false;
      }
    }
    if (!backendOk) {
      _skippingExercise = false;
      return { ok: false, advanced: false, index: session.currentExerciseIndex };
    }
    session.skipped.push(exercise.id);
    const isLast = session.currentExerciseIndex >= session.exercises.length - 1;
    if (isLast) {
      const done = await finishTraining('done');
      _skippingExercise = false;
      return { ok: done.ok, advanced: done.ok, finished: true, callsBeforeComplete: calls.map((c) => c.url) };
    }
    session.currentExerciseIndex += 1;
    session.currentSetIndex = 0;
    _skippingExercise = false;
    return { ok: true, advanced: true, index: session.currentExerciseIndex, beforeIndex };
  }

  async function finishTraining(status = 'done') {
    if (!session) {
      showToast('没有进行中的训练会话', 'error');
      return { ok: false };
    }
    const sid = session?.backendSession?.id;
    let apiOk = false;
    if (!sid) {
      showToast('缺少后端会话，无法完成同步', 'error');
      return { ok: false, sessionCleared: false, canRetry: true, missingSession: true };
    }
    try {
      const endpoint = status === 'partial' ? '/api/session/cancel' : '/api/session/complete';
      const response = await trackedFetch(endpoint, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ session_id: sid }),
      });
      apiOk = !!response.ok;
      if (!apiOk) showToast(`训练同步失败: ${response.status}`, 'error');
    } catch (e) {
      showToast('训练同步失败: 网络错误', 'error');
    }
    if (!apiOk) {
      // keep session
      return { ok: false, sessionCleared: false, canRetry: true };
    }
    session = null;
    return { ok: true, sessionCleared: true };
  }

  async function resetToDefaults({ userConfirms = true } = {}) {
    const previewResp = await trackedFetch('/api/data/restore-defaults', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ confirm: false }),
    });
    if (!previewResp.ok) {
      showToast('预览失败', 'error');
      return { ok: false };
    }
    const preview = await previewResp.json();
    if (!userConfirms || !confirmFn(`plans=${preview.current_state?.plans}`)) {
      return { ok: false, cancelled: true, calls: calls.slice() };
    }
    const response = await trackedFetch('/api/data/restore-defaults', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ confirm: true, backup: true }),
    });
    if (!response.ok) {
      showToast('恢复失败', 'error');
      return { ok: false };
    }
    showToast('数据已恢复为默认，原数据已备份', 'success');
    return { ok: true };
  }

  return {
    calls,
    get state() { return state; },
    set state(v) { state = v; },
    get session() { return session; },
    set session(v) { session = v; },
    get toast() { return toast; },
    get dialogOpen() { return dialogOpen; },
    set dialogOpen(v) { dialogOpen = v; },
    apiPlanToScheduleEntry,
    stateFromApiPayload,
    savePlanFromForm,
    saveVideoFromForm,
    completeSet,
    skipExercise,
    finishTraining,
    resetToDefaults,
  };
}

module.exports = { createHarness };
