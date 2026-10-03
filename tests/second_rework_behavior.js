'use strict';
const {createPage,response,payloadFor,snapshot,assert,assertLoading,assertError,assertData,assertEmpty,waitFor,tick} = require('./f01_real_dom_behavior');
const scenario = process.argv[2];
const pending=[];
let conflict=true, delay=false, revision='original';
let failedRange = ['range-error', 'partial-error', 'all-error'].includes(scenario);
let date=scenario==='cross-year'?[2027,0,1]:[2026,9,2];
const key=`${date[0]}-${String(date[1]+1).padStart(2,'0')}-${String(date[2]).padStart(2,'0')}`;
function body(url) {
 const month=new URL(url,'http://localhost').searchParams.get('month');
 if(url.startsWith('/api/session/current?date=')) return {session:null};
 if(url==='/api/session/current?include_completed=true' && (scenario==='visibility' || scenario==='visibility-empty' || scenario==='same-month') && conflict) return {session:{id:3,plan_id:99,status:'in_progress'}};
 if(url==='/api/session/cancel') {conflict=false;return {status:'cancelled'};}
 if(url.startsWith('/api/plans/month?')) {
  const [y,m]=month.split('-').map(Number);
  return {days:Array.from({length:new Date(y,m,0).getDate()},(_,i)=>({date:`${month}-${String(i+1).padStart(2,'0')}`,id:i+1,title:`${revision}-${month}-${i+1}`,is_training:true,items:[{name:'真实动作',sets:3,reps:8}]}))};
 }
 if(url.startsWith('/api/stats/month?')) return {month,training_days:31,completed:0,completion_rate:0,duration_seconds:0};
 return payloadFor(url,'data');
}
const page=createPage({date,fetchOverride(url){
 const b=body(url);
 if(failedRange && ((scenario==='all-error') || (url.includes('month=2026-10') && (scenario==='range-error' || url.startsWith('/api/stats/month/detail'))))) {
  if(url==='/api/plans/today') return new Promise(resolve=>pending.push({url,b,resolve}));
  return Promise.resolve(response({detail:'injected failure'},503));
 }
 if ((url==='/api/plans/today' && (delay || !['visibility','visibility-empty','same-month'].includes(scenario))) || (scenario==='same-month' && revision==='old-refresh' && url.includes('month=2026-10'))) return new Promise(resolve=>pending.push({url,b,resolve}));
 return Promise.resolve(response(b));
}});
const doc=page.dom.window.document;
function click(sel){const el=doc.querySelector(sel);assert(el,`missing ${sel}`);el.click();}
async function release(status=200,empty=false){const jobs=pending.splice(0);jobs.forEach(p=>p.resolve(response(empty?{items:[],is_training:false}:p.b,status)));for(let i=0;i<20;i++)await tick();}
(async()=>{
 if(scenario==='same-month') {
  await waitFor(()=>snapshot(page).state==='data','initial Data');
  click('#monthNextBtn');for(let i=0;i<20;i++)await tick();
  revision='old-refresh';click('#monthPrevBtn');
  assert(pending.length===3,'three old month replies captured');
  revision='new-boot';click('[data-v25-cancel-conflict]');
  await waitFor(()=>doc.getElementById('weekList').textContent.includes('new-boot'),'new boot cache');
  await release();
  assert(doc.getElementById('calendar').textContent.includes('new-boot'),'old month overwrote boot cache');
  assert(!doc.getElementById('weekList').textContent.includes('读取中'),'week stuck after race');
  page.dom.window.close();console.log(JSON.stringify({PASS:true,scenario}));return;
 }
 if(scenario==='visibility' || scenario==='visibility-empty') {
  await waitFor(()=>snapshot(page).state==='data','initial Data');assertData(page,'Data');
  delay=true;click('[data-v25-cancel-conflict]');
  await waitFor(()=>pending.length>0,'cancel reload');assertLoading(page,'Data → reload Loading');
  await release(503);assertError(page,'Data → reload Error');
  click('[data-v25-retry-today]');await waitFor(()=>pending.length>0,'retry Data');assertLoading(page,'retry Loading');
  await release(200,scenario==='visibility-empty');
  if(scenario==='visibility-empty') assertEmpty(page,'Retry Empty');else assertData(page,'Retry Data');
  page.dom.window.close();
  console.log(JSON.stringify({PASS:true,scenario}));return;
 }
 assertLoading(page,'initial pending');
 click('#monthNextBtn');click('[data-nav="day"]');
 if(scenario==='all-error') pending.forEach(p=>p.b=null);
 await release(scenario==='all-error'?503:200);
 await waitFor(()=>snapshot(page).state!=='loading','boot settled');
 const week=doc.getElementById('weekList');
 assert(!week.textContent.includes('读取中'),`week stuck: ${week.textContent}`);
 if(!failedRange) {
  assert(week.querySelector(`[data-date="${key}"]`).textContent.includes(`original-${key.slice(0,7)}-${date[2]}`),'today week real data');
  assert(!week.textContent.includes('读取失败'),'week range failure');
 }
 if(failedRange) {
  assert(week.textContent.includes('读取失败'),'range failure did not settle to error');
  failedRange=false;
  if(scenario==='all-error') {click('[data-v25-retry-today]');await release();}
 }
 // A fast switch back is allowed to reuse completed boot cache and cannot
 // leave the earlier range loading. The visible month must stay current.
 click('#monthPrevBtn');
 await waitFor(()=>doc.getElementById('calendar').getAttribute('data-month-status')==='ready','return month ready');
 assert(doc.getElementById('calendar').textContent.includes('original-'+key.slice(0,7)),'returned cache');
 page.dom.window.close();console.log(JSON.stringify({PASS:true,scenario,week:week.textContent}));
})().catch(e=>{console.error(e.stack);page.dom.window.close();process.exit(1)});
