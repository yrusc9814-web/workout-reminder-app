'use strict';
const assert = require('assert');
const fs = require('fs');
const { JSDOM } = require(process.env.VAN18_DOM_DEPS || '/private/tmp/van13-jsdom-deps/node_modules/jsdom');
const catalog = JSON.parse(process.env.VAN18_CATALOG);
const today = '2026-10-04';
const source = fs.readFileSync('static/index.html', 'utf8').replace('    })();\n  </script>', `
      window.van18 = {
        plans: BASE_TRAINING_PLANS, recommend: buildPlanFromTpl,
        resolve: v25ResolvePlanItems, payload: v25PlanPayload,
        start: startPlan, ensure: v25EnsureRemotePlan,
        replace: replaceDayPlan, adjust: renderAdjustModal,
        setCatalog: function(rows) { v25Remote.exercises = rows; },
        getToday: function() { return todayPlan; },
        refresh: function() { return v25RefreshCanonical([v25TodayKey()], {forceActivePlan:true}); },
        ready: function() { return v25Remote.ready; }
      };
    })();\n  </script>`);
const writes = [], saved = new Map(), errors = [];
function reply(body, status = 200) { return {ok:status < 400, status, text:async()=>JSON.stringify(body), json:async()=>body}; }
function read(url) {
  if (url === '/api/exercises') return {exercises:catalog};
  if (url === '/api/templates') return {templates:[]};
  if (url === '/api/favorites') return {favorites:[]};
  if (url === '/api/plans/today') return saved.get(today) || {date:today,isTrainingDay:false,is_training:false,items:[]};
  if (url.startsWith('/api/plans/month')) return {days:Array.from(saved.values()).map(p=>({...p,is_training:true}))};
  if (url.startsWith('/api/calendar')) return {days:[]};
  if (url.startsWith('/api/session/current')) return {session:null};
  if (url.startsWith('/api/stats')) return {days:[],training_days:0,completed:0,completion_rate:0};
  if (url === '/api/ai/models') return {models:[]};
  if (url === '/api/ai/provider') return {provider:'local-demo'};
  return {};
}
function create(storage={}) {
  return new JSDOM(source, {url:'http://127.0.0.1:3000/', runScripts:'dangerously', pretendToBeVisual:true, beforeParse(w) {
    const DateOriginal = w.Date;
    w.Date = class extends DateOriginal { constructor(...args) { super(...(args.length ? args : ['2026-10-04T12:00:00+08:00'])); } static now() { return new DateOriginal('2026-10-04T12:00:00+08:00').getTime(); } };
    Object.entries(storage).forEach(([k,v])=>w.localStorage.setItem(k,v));
    w.scrollTo=()=>{}; w.HTMLElement.prototype.scrollIntoView=()=>{};
    w.fetch=async(url, options={})=> {
      const method=options.method || 'GET';
      if (process.env.VAN18_BASE_URL) {
        if (method !== 'GET' && (url.startsWith('/api/plans/by-date/') || url === '/api/plans/generate')) writes.push({url,body:JSON.parse(options.body)});
        return fetch(process.env.VAN18_BASE_URL + url, options);
      }
      if (method === 'PUT' && url.startsWith('/api/plans/by-date/')) {
        const body=JSON.parse(options.body); writes.push({url,body});
        assert(body.items.every(i=>i.exercise_id != null));
        const plan={...body,id:401,isTrainingDay:true,is_training:true,items:body.items.map((i,n)=>({...i,id:100+n}))};
        saved.set(body.date,plan); return reply({status:'saved',plan});
      }
      if (method === 'POST' && url === '/api/plans/generate') { writes.push({url,body:JSON.parse(options.body)}); return reply({plan:{id:401}}); }
      return reply(read(String(url)));
    };
    w.addEventListener('error', e=>errors.push(e.message));
  }});
}
const pause=ms=>new Promise(r=>setTimeout(r,ms));
async function settle() { await pause(100); }
async function run() {
  let dom=create(); let w=dom.window; await settle(); assert(w.van18.ready());
  // Real IDs from the isolated API catalog; rename every display name.
  const renamed=catalog.map(ex=>({...ex,name:'目录展示改名 '+ex.id}));
  w.van18.setCatalog(renamed);
  for (const plan of [w.van18.plans.quick10,w.van18.plans.back15,...[10,20,30].map(w.van18.recommend)]) {
    const altered={...plan,items:plan.items.map((x,i)=>'任意展示文案 '+i+' · '+x.split(' · ')[1])};
    const resolved=w.van18.resolve(altered);
    assert.equal(resolved.length,plan.items.length);
    assert.deepEqual(Array.from(resolved, i=>i.exercise_id),Array.from(plan.exerciseKeys,k=>catalog.find(ex=>ex.catalog_key===k).id));
  }
  // Actual production click, canonical write and canonical readback.
  w.document.querySelector('[data-start-plan="back15"]').click(); await settle();
  assert.equal(writes.at(-1).body.items.length,4);
  const expected=Array.from(w.van18.plans.back15.exerciseKeys,k=>catalog.find(ex=>ex.catalog_key===k).id);
  assert.deepEqual(writes.at(-1).body.items.map(i=>i.exercise_id),expected);
  assert.deepEqual(Array.from(w.van18.getToday(),i=>i.exerciseId),expected);
  const storage={}; for(let i=0;i<w.localStorage.length;i++) { const k=w.localStorage.key(i); storage[k]=w.localStorage.getItem(k); }
  dom.window.close(); dom=create(storage); w=dom.window; await settle();
  assert.deepEqual(Array.from(w.van18.getToday(),i=>i.exerciseId),expected);
  // The missing catalog action cannot turn a three-action plan into two.
  const before=writes.length;
  w.document.querySelector('[data-start-plan="upper20"]').click(); await settle();
  assert.equal(writes.length,before); assert(w.document.querySelector('#v25Toast').textContent.includes('wall-angel'));
  const broken={...w.van18.plans.back15,exerciseKeys:['missing',...w.van18.plans.back15.exerciseKeys.slice(1)]};
  assert.throws(()=>w.van18.payload(today,broken),/无法解析/);
  await assert.rejects(w.van18.ensure(broken),/无法解析/);
  await assert.rejects(w.van18.ensure({items:['未知动作 · 3×8','猫牛式 · 3×10']}),/未绑定/);
  assert.equal(writes.length,before);
  assert.throws(()=>w.van18.payload(today,{items:['有效动作','']}),/缺少名称/);
  // Schedule uses the same stable identities through actual modal buttons.
  w.document.querySelector('[data-plan-id="back15"]').click(); await settle();
  const schedule=w.document.querySelector('[data-schedule-day]'); assert(schedule); schedule.click(); await settle();
  assert.deepEqual(writes.at(-1).body.items.map(i=>i.exercise_id),expected);
  // Adjustment choices are built-ins too; check the real replacement path.
  w.van18.adjust(18,'time');
  const short=w.__replaceSuggestions.find(p=>p.id==='shortCore'); assert(short);
  w.van18.replace(18,short); await settle();
  assert.equal(writes.at(-1).body.items.length,3);
  assert.deepEqual(writes.at(-1).body.items.map(i=>i.exercise_id),Array.from(short.exerciseKeys,k=>catalog.find(ex=>ex.catalog_key===k).id));
  assert.deepEqual(errors,[]);
  dom.window.close(); console.log(JSON.stringify({PASS:true,startCount:4,refreshIds:expected,missingBlocked:true,schedule:true,replace:true}));
}
run().catch(e=>{console.error(e);process.exit(1);});
