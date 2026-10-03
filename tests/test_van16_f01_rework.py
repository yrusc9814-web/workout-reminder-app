"""F01日视图状态机的真实 DOM 行为回归。"""
from __future__ import annotations

import os
import subprocess
import textwrap
from pathlib import Path

import pytest


APP_DIR = Path(__file__).resolve().parents[1]
EVIDENCE_DIR = Path("/private/tmp/van16-f01-rework-evidence")
DEFAULT_DOM_DEPS = Path("/private/tmp/van13-jsdom-deps/node_modules")


def test_f01_extracted_boot_generation_supplement():
    """Keep the narrow extracted boot-generation regression beside the full-page gate."""
    dom_deps = Path(os.environ.get("VAN16_DOM_DEPS", str(DEFAULT_DOM_DEPS)))
    if not (dom_deps / "jsdom").exists():
        pytest.fail(f"F01 jsdom dependency is required at {dom_deps}; refusing to skip the gate")

    script = textwrap.dedent(
        r"""
        const fs = require('fs');
        const vm = require('vm');
        const path = require('path');
        const { JSDOM } = require(path.join(
          process.env.VAN16_DOM_DEPS || '/private/tmp/van13-jsdom-deps/node_modules',
          'jsdom'
        ));

        const source = fs.readFileSync('static/index.html', 'utf8');
        function section(startMarker, endMarker) {
          const start = source.indexOf(startMarker);
          const end = source.indexOf(endMarker, start);
          if (start < 0 || end < 0) throw new Error(`missing source section ${startMarker}`);
          return source.slice(start, end);
        }
        function response(body, status = 200) {
          return {
            ok: status >= 200 && status < 300,
            status,
            text: async () => JSON.stringify(body),
          };
        }
        function tick() {
          return new Promise(resolve => setImmediate(resolve));
        }
        function snapshot(runtime) {
          const doc = runtime.dom.window.document;
          const fetchState = doc.getElementById('dayFetchState');
          const emptyHero = doc.getElementById('dayEmptyHero');
          const content = doc.getElementById('dayHeroContent');
          return {
            state: runtime.context.v25TodayDisplayState,
            heroState: doc.getElementById('dayHero').getAttribute('data-today-state'),
            fetchHidden: fetchState.hidden,
            fetchText: fetchState.textContent,
            emptyHidden: emptyHero.hidden,
            emptyText: emptyHero.textContent,
            contentHidden: content.hidden,
            fetchDisplay: runtime.dom.window.getComputedStyle(fetchState).display,
            emptyDisplay: runtime.dom.window.getComputedStyle(emptyHero).display,
            contentDisplay: runtime.dom.window.getComputedStyle(content).display,
            retryVisible: !fetchState.hidden && !!fetchState.querySelector('[data-v25-retry-today]'),
            planText: doc.getElementById('todayPlanList').textContent,
            todayPlan: runtime.context.todayPlan.map(item => item.name),
          };
        }
        function assert(condition, message) {
          if (!condition) throw new Error(message);
        }
        function assertLoading(s, label) {
          assert(s.state === 'loading' && s.heroState === 'loading', `${label}: expected loading state: ${JSON.stringify(s)}`);
          assert(!s.fetchHidden && s.fetchDisplay !== 'none' && s.contentHidden && s.contentDisplay === 'none' && s.emptyHidden && s.emptyDisplay === 'none', `${label}: loading layers are wrong: ${JSON.stringify(s)}`);
          assert(!s.fetchText.includes('今天还没有训练动作'), `${label}: loading copied empty text: ${s.fetchText}`);
        }
        function assertError(s, label) {
          assert(s.state === 'error' && s.heroState === 'error', `${label}: expected error state: ${JSON.stringify(s)}`);
          assert(!s.fetchHidden && s.fetchDisplay !== 'none' && s.retryVisible && s.contentHidden && s.contentDisplay === 'none' && s.emptyHidden && s.emptyDisplay === 'none', `${label}: error layers are wrong: ${JSON.stringify(s)}`);
          assert(s.fetchText.includes('读取失败'), `${label}: missing error copy: ${s.fetchText}`);
          assert(!s.fetchText.includes('今天还没有训练动作'), `${label}: error copied empty text: ${s.fetchText}`);
        }
        function assertEmpty(s, label) {
          assert(s.state === 'empty' && s.heroState === 'empty', `${label}: expected empty state: ${JSON.stringify(s)}`);
          assert(s.fetchHidden && s.fetchDisplay === 'none' && !s.emptyHidden && s.emptyDisplay !== 'none' && s.contentHidden && s.contentDisplay === 'none', `${label}: empty layers are wrong: ${JSON.stringify(s)}`);
          assert(s.emptyText.includes('今天还没有训练动作'), `${label}: missing real empty copy: ${s.emptyText}`);
        }
        function assertData(s, label, expectedName) {
          assert(s.state === 'data' && s.heroState === 'data', `${label}: expected data state: ${JSON.stringify(s)}`);
          assert(s.fetchHidden && s.fetchDisplay === 'none' && s.emptyHidden && s.emptyDisplay === 'none' && !s.contentHidden && s.contentDisplay !== 'none', `${label}: data layers are wrong: ${JSON.stringify(s)}`);
          assert(s.todayPlan.includes(expectedName), `${label}: backend data missing: ${JSON.stringify(s)}`);
          assert(!s.fetchText.includes('读取失败'), `${label}: stale error copy remains: ${JSON.stringify(s)}`);
        }

        function makeRuntime({ mode = 'data', delayToday = false, oldLocalStorage = false, todayTitle = '真实计划', todayName = '真实动作' } = {}) {
          const dom = new JSDOM(source, { url: 'http://127.0.0.1:3000/' });
          let currentMode = mode;
          let shouldDelayToday = delayToday;
          let currentTitle = todayTitle;
          let currentName = todayName;
          const pendingToday = [];
          const calls = [];

          function todayBody() {
            if (currentMode === 'empty') return { date: '2026-10-02', is_training: false, isTrainingDay: false, items: [] };
            return {
              date: '2026-10-02',
              id: 41,
              title: currentTitle,
              is_training: true,
              isTrainingDay: true,
              items: [{ id: 7, exercise_id: 9, name: currentName, sets: 3, reps: 8, duration_seconds: 30, spec: '3 组 · 8 次' }],
            };
          }
          function payload(pathname) {
            if (pathname === '/api/plans/today') return todayBody();
            if (pathname.indexOf('/api/calendar?month=') === 0) return { days: [] };
            if (pathname.indexOf('/api/stats/month/detail?month=') === 0) return { days: [], completed: 0 };
            if (pathname.indexOf('/api/stats/month?month=') === 0) return { month: '2026-10', training_days: 0, completed: 0, completion_rate: 0, duration_seconds: 0 };
            if (pathname.indexOf('/api/stats/week/detail?date=') === 0) return { days: [], training_days: 0, completed: 0 };
            if (pathname === '/api/exercises') return { exercises: [] };
            if (pathname === '/api/templates') return { templates: [] };
            if (pathname === '/api/favorites') return { favorites: [] };
            if (pathname === '/api/ai/provider') return { provider: 'local-demo', model: '' };
            if (pathname === '/api/ai/models') return { models: [] };
                if (pathname.indexOf('/api/plans/month?month=') === 0) return { days: [] };
                if (pathname.indexOf('/api/session/current?date=') === 0) return { session: null };
                if (pathname === '/api/session/current?include_completed=true') return { session: null };
            throw new Error(`unexpected API path: ${pathname}`);
          }
          function fetchImpl(pathname) {
                calls.push(pathname);
                if (pathname === '/api/plans/today' && shouldDelayToday) {
                  const delayedBody = todayBody();
                  return new Promise((resolve, reject) => pendingToday.push({ resolve, reject, body: delayedBody }));
            }
            if ((currentMode === 'error' || currentMode === 'all-error') && pathname === '/api/plans/today') return Promise.resolve(response({ detail: 'offline' }, 503));
            if (currentMode === 'all-error' && pathname === '/api/calendar?month=2026-10') return Promise.resolve(response({ detail: 'offline' }, 503));
            return Promise.resolve(response(payload(pathname)));
          }

          const context = {
            console,
            Promise,
            JSON,
            Object,
            Array,
            Error,
            Math,
            Number,
            String,
            Date,
            document: dom.window.document,
            fetch: fetchImpl,
            setTimeout,
            clearTimeout,
            todayPlan: [],
            todayStepIndex: 0,
            todaySetIndex: 0,
            todayActionElapsedSeconds: 0,
            todayActionStartedAt: null,
            todaySkipped: [],
            todayRecordFacts: [],
            todayPendingProgress: null,
            todayStarted: false,
            todayDone: false,
            todayIsRest: true,
            todaySessionKey: '2026-10-02',
            dailySessions: {},
            v25TodayDisplayState: 'loading',
            v25RemoteDataVerified: false,
            v25RemoteProgressPending: false,
            v25LocalDoneAwaitingVerification: false,
            v25RemotePlanId: null,
            v25RemotePlanPromise: null,
            v25RemoteSessionId: null,
            v25RemoteSessionPromise: null,
            v25RemoteSessionConflict: null,
            v25RemoteSessionConflictPrompted: false,
            v25RemoteStatusVerified: false,
            v25Remote: { ready: false, today: null, calendar: {}, monthStatus: {}, monthRequests: {}, loadedMonths: {}, statsByMonth: {}, detailByMonth: {}, stats: null, weekStats: [], exercises: [], templates: [], favorites: [] },
            v25DisplayedMonthRequest: 0,
            v25BootRequestSequence: 0,
            v25BootPromise: null,
            calendarDisplayYear: 2026,
            calendarDisplayMonth: 9,
            calendarPlans: {},
            formatDateKey: date => `${date.getFullYear()}-${String(date.getMonth() + 1).padStart(2, '0')}-${String(date.getDate()).padStart(2, '0')}`,
            getToday: () => new Date(2026, 9, 2),
            todayPlanEl: id => dom.window.document.getElementById(id),
            v25UiDoneConfirmed: () => false,
            todayExecutionSummary: () => ({ completedActions: 0, skippedActions: 0, completedSets: 0, durationLabel: '实际时长未知' }),
            todayRecordFact: () => null,
            aggregateIntensity: () => '低强度',
            getTodayCurrentName: () => '',
            exerciseDetails: {},
            isVerifiedVideo: () => false,
            escapeHtml: value => String(value),
            resetStartBtn: () => {},
            saveTrainingState: () => {},
            renderWeek: () => {},
            renderCalendarMonth: () => {},
            showToast: () => {},
            v25ApplyStats: () => {},
            v25ApplyWeekStats: () => {},
            v25ApplyCalendar: () => {},
            v25ApplyPlanDays: () => {},
            v25RenderLibrary: () => {},
            v25ApplyTemplates: () => {},
            renderFavorites: () => {},
            saveFavorites: () => {},
            mode: () => {},
            apiSettings: {},
            v25BackendStatusForDay: () => null,
            v25ReconcileTodaySession: () => ({ started: false, stepIndex: 0, setIndex: 0, actionElapsedSeconds: 0, actionStartedAt: null, skipped: [], records: [], pending: null, done: false }),
            v25RemoteExerciseByName: () => null,
            v25ParseUiItem: item => ({ id: Number(item.id), exercise_id: Number(item.exercise_id), name: item.name, sets: Number(item.sets || 1), reps: item.reps == null ? null : Number(item.reps), duration_seconds: item.duration_seconds == null ? null : Number(item.duration_seconds), notes: item.notes || null, video_url: item.video_url || null, spec: item.spec || '' }),
            v25SpecForItem: () => '',
            v25WeekMonthTokens: () => [],
            v25DisplayedMonthToken: () => '2026-10',
            v25ShowSessionConflict: () => {},
            v25ClearMonth: () => {},
          };
          if (oldLocalStorage) {
            dom.window.localStorage.setItem('qd-training-state-v1', JSON.stringify({ version: 1, data: { dailySessions: { '2026-10-02': { items: [{ name: '旧本地假动作', time: 99 }], started: true, done: true } } } }));
            context.todayPlan = [{ name: '旧本地假动作', time: 99, sets: 9, spec: '旧数据' }];
            context.todayDone = true;
          }
          vm.createContext(context);
          // Use the production reset function; this is the call that keeps a
          // retry from presenting the previous local/session snapshot.
          vm.runInContext(section('function resetTodayRuntimeForUnverifiedData', 'function hydrateTrainingState'), context);
          vm.runInContext(section('function v25ApiFetch', 'function v25ShowSessionConflict'), context);
          vm.runInContext(section('function renderTodayPlan', 'function startPlan'), context);
          vm.runInContext(section('function bootV25Api', '// P0-2：启动前'), context);
          return {
            dom,
            context,
            calls,
            setMode(next) { currentMode = next; },
            setDelay(next) { shouldDelayToday = next; },
            setTodayData(title, name) { currentTitle = title; currentName = name; },
                resolveDelayedToday() {
                  const rows = pendingToday.splice(0);
                  rows.forEach(row => row.resolve(response(row.body)));
                },
            snapshot() { return snapshot({ dom, context }); },
          };
        }

        (async () => {
          const delayed = makeRuntime({ mode: 'data', delayToday: true, oldLocalStorage: true });
          const delayedBoot = delayed.context.bootV25Api();
          await tick();
          assertLoading(delayed.snapshot(), 'loading → data');
          delayed.setDelay(false);
          delayed.resolveDelayedToday();
          await delayedBoot;
          assertData(delayed.snapshot(), 'loading → data', '真实动作');
          assert(!delayed.snapshot().todayPlan.includes('旧本地假动作'), 'loading → data: localStorage polluted backend data');

          const empty = makeRuntime({ mode: 'empty', oldLocalStorage: true });
          await empty.context.bootV25Api();
          assertEmpty(empty.snapshot(), 'loading → empty');
          assert(!empty.snapshot().todayPlan.includes('旧本地假动作'), 'loading → empty: localStorage polluted empty result');

          const failed = makeRuntime({ mode: 'error', oldLocalStorage: true });
          await failed.context.bootV25Api();
          assertError(failed.snapshot(), 'loading → error');
          assert(!failed.snapshot().todayPlan.includes('旧本地假动作'), 'loading → error: localStorage polluted error result');

          const monthSwitched = makeRuntime({ mode: 'all-error' });
          monthSwitched.context.v25DisplayedMonthRequest = 7;
          monthSwitched.context.v25DisplayedMonthToken = () => '2026-11';
          await monthSwitched.context.bootV25Api();
          assertError(monthSwitched.snapshot(), 'month switch during boot → error');

          const recovered = makeRuntime({ mode: 'error' });
          await recovered.context.bootV25Api();
          assertError(recovered.snapshot(), 'error → retry');
          recovered.setMode('data');
          const retryButton = recovered.dom.window.document.querySelector('[data-v25-retry-today]');
          assert(retryButton, 'error → retry: retry button is not in the real DOM');
          recovered.context.v25BootPromise = recovered.context.bootV25Api();
          await recovered.context.v25BootPromise;
          assertData(recovered.snapshot(), 'error → retry → data', '真实动作');

          const recoveredEmpty = makeRuntime({ mode: 'error' });
          await recoveredEmpty.context.bootV25Api();
          recoveredEmpty.setMode('empty');
          const emptyRetryButton = recoveredEmpty.dom.window.document.querySelector('[data-v25-retry-today]');
          recoveredEmpty.context.v25BootPromise = recoveredEmpty.context.bootV25Api();
          await recoveredEmpty.context.v25BootPromise;
          assertEmpty(recoveredEmpty.snapshot(), 'error → retry → empty');

          const race = makeRuntime({ mode: 'data', delayToday: true, todayTitle: '旧响应计划', todayName: '旧响应动作' });
          const oldBoot = race.context.bootV25Api();
          await tick();
          race.setTodayData('新重试计划', '新重试动作');
          race.setDelay(false);
          const newBoot = race.context.bootV25Api();
          await newBoot;
          assertData(race.snapshot(), 'old response protection', '新重试动作');
          race.resolveDelayedToday();
          await oldBoot;
          assertData(race.snapshot(), 'old response protection after late response', '新重试动作');
          assert(!race.snapshot().todayPlan.includes('旧响应动作'), 'late old response overwrote the retry result');

          console.log(JSON.stringify({
            PASS: true,
            states: ['loading→data', 'loading→empty', 'loading→error', 'error→retry→data', 'error→retry→empty'],
            localStorage: 'isolated old state never overrode backend result',
            race: 'late boot generation ignored',
          }));
        })().catch(error => {
          console.error(error.stack || error);
          process.exit(1);
        });
        """
    )
    result = subprocess.run(
        ["node", "-e", script],
        capture_output=True,
        text=True,
        cwd=APP_DIR,
        timeout=45,
        env={**os.environ, "VAN16_DOM_DEPS": str(dom_deps)},
    )
    EVIDENCE_DIR.mkdir(parents=True, exist_ok=True)
    (EVIDENCE_DIR / "f01-real-dom-states.json").write_text(result.stdout or result.stderr, encoding="utf-8")
    assert result.returncode == 0, result.stderr + "\n" + result.stdout
    assert '"PASS":true' in result.stdout
