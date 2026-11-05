import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import vm from 'node:vm';
import { webcrypto } from 'node:crypto';
import { parseHTML } from 'linkedom';
import { request } from '../lib/api.js';
import { Outbox } from '../lib/outbox.js';
const scripts = ['content/runtime.js', 'adapters/must_moodle.js', 'adapters/must_student_portal.js', 'adapters/must_fie_people.js', 'content/capture.js'];
function environment(adapter, body, url = 'http://localhost:8098/portal#news', account = 'school-a') {
  const { document } = parseHTML(`<html><head><title>模拟页</title><meta name="campus-radar-fixture" content="${adapter}"></head><body data-account-id="${account}">${body}<footer>学院通用电话0000</footer></body></html>`);
  const ctx = vm.createContext({ document, location: new URL(url), URL, setTimeout, Date, console, getSelection: () => '' });
  for (const script of scripts) vm.runInContext(fs.readFileSync(new URL('../'+script, import.meta.url), 'utf8'), ctx);
  return { R: ctx.CampusRadar, document, ctx };
}
const plain = v => JSON.parse(JSON.stringify(v));
test('portal same URL yields three native IDs; only chosen two become submission payload', () => {
  const { R } = environment('student', '<main>'+['a', 'b', 'c'].map(i=>`<article data-notice-id="${i}"><h2>通知${i}</h2><p>独立原文${i}</p></article>`).join('')+'</main>');
  const page = R.scan(); assert.equal(page.candidates.length, 3);
  const selected = page.candidates.filter(c => c.entity_id !== 'notice:c');
  assert.deepEqual(plain(selected.map(c=>c.entity_id)), ['notice:a', 'notice:b']);
  assert.equal(new Set(selected.map(c=>c.locator.url)).size, 1);
});
test('FIE directory and detail identities; footer contact is excluded', () => {
  const d = environment('fie', '<main><a href="/person/view/id-9001.html">模拟甲</a><a href="/person/view/id-9002.html">模拟乙</a><footer><a href="/person/view/id-9999.html">通用页脚</a></footer></main>', 'http://localhost:8098/person/id-828.html');
  assert.deepEqual(plain(d.R.scan().candidates.map(c=>c.entity_id)), ['person:9001', 'person:9002']);
  const p = environment('fie', '<main><article data-person-id="9001"><h1>模拟甲</h1><dl><dt>办公室</dt><dd>A101</dd></dl><p>个人资料</p><footer><dl><dt>办公室</dt><dd>通用前台0000</dd><dt>邮箱</dt><dd>global@example.test</dd></dl></footer></article></main>', 'http://localhost:8098/person/view/id-9001.html');
  const c = p.R.scan().candidates[0]; assert.equal(c.raw.fields.office, 'A101'); assert.equal(c.raw.fields.email, undefined); assert.ok(!c.raw.text.includes('0000')); assert.equal(c.entity_id, 'person:9001');
});
test('Moodle course navigation does not become an item; activity is native ID', () => {
  const { R } = environment('moodle', '<main id="region-main"><a href="/course/view.php?id=101">课程</a><a href="/mod/assign/view.php?id=1001">作业</a></main>', 'http://localhost:8098/my/');
  const p = R.scan(); assert.equal(p.navigation.length, 1); assert.equal(p.candidates.length, 1); assert.equal(p.candidates[0].entity_id, 'assignment:1001'); assert.equal(p.candidates[0].needs_detail, true);
});
test('timetable keeps semester/week/period and hash route without guessing a date', () => {
  const { R } = environment('student', '<main><div data-semester="2026秋"></div><div data-week="2"></div><article data-schedule-id="course-3"><h2>课表</h2><dl><dt>星期</dt><dd>周五</dd><dt>节次</dt><dd>3-4</dd></dl></article></main>', 'http://localhost:8098/portal#timetable');
  const c = R.scan().candidates[0]; assert.equal(c.recipe.view.route, '#timetable'); assert.equal(c.raw.fields.week, '2'); assert.equal(c.raw.fields.period, '3-4'); assert.equal(c.raw.fields.datetime_text, undefined);
});
test('login, selection missing, unsupported DOM and render timeout fail closed', async () => {
  const login = environment('student', '<main><input type="password"></main>'); assert.throws(()=>login.R.scan(), /need_login/);
  const missing = environment('student', '<main><article data-notice-id="b"><h2>通知</h2><p>原文</p></article></main>');
  assert.throws(()=>missing.R.capture({ adapter:'student', entity_id:'notice:a' }), /selection_missing/);
  const shell = environment('student', '<div>正在加载</div>'); await assert.rejects(shell.R.wait(null, 20), /render_timeout/);
  const unknown = environment('student', '<main><div>未知结构</div></main>'); assert.throws(()=>unknown.R.scan(), /unsupported_dom/);
});
test('strict response rejects HTML 200, empty JSON, missing per-item IDs and false success', async () => {
  for (const value of ['<html>Login</html>', '{}', '{"ok":true}', '{"ok":false,"schema_version":1}']) {
    await assert.rejects(request({server:'http://localhost'}, '/api/v1/captures', {}, {fetcher:async()=>new Response(value, {status:200})}));
  }
});
test('durable outbox survives instance replacement and never flushes another account', async () => {
  const data = {}; const storage = { get: async k=>({[k]:structuredClone(data[k])}), set: async patch=>Object.assign(data,structuredClone(patch)) };
  globalThis.crypto ??= webcrypto;
  const cfg = {server:'http://localhost',uid:1}; const calls=[];
  const first = new Outbox(storage,async()=>{throw Error('offline');});
  await first.add(cfg,'/api/v1/captures',{request_id:'persistent-request'});
  const restored = new Outbox(storage,async(c,p,b)=>{calls.push(b.request_id); return {ok:true};});
  await restored.flush({...cfg,uid:2}); assert.equal(calls.length,0);
  await restored.flush(cfg); assert.deepEqual(calls,['persistent-request']);
  assert.equal((await restored.all())[0].state,'confirmed'); assert.equal((await restored.all())[0].body,undefined);
});


test('recipe survives backend canonical JSON key order; changed view/route cannot write original', () => {
  const {R} = environment('student', '<main data-semester="2026秋" data-week="2"><article data-notice-id="a"><h2>通知</h2><p>原文</p></article></main>');
  const c = R.scan().candidates[0];
  const recipe = plain(c.recipe);
  recipe.view = Object.fromEntries(Object.entries(recipe.view).sort(([a],[b])=>a.localeCompare(b)));
  assert.equal(R.capture(recipe).entity_id, 'notice:a');
  assert.throws(()=>R.capture({...recipe, view:{...recipe.view,week:'3'}}), /view_mismatch/);
  assert.throws(()=>R.capture({...recipe, url:'http://localhost:8098/portal#other'}), /route_mismatch/);
});

test('response success requires matched item IDs, result job ID and valid claim', async()=>{
  const body={request_id:'r',targets:[{candidate_id:'a'}]};
  const cases=[
    ['/api/v1/captures',body,{request_id:'r',results:[{candidate_id:'a',status:'new'}]}],
    ['/api/v1/captures',body,{request_id:'r',results:[{candidate_id:'a',status:'failed'}]}],
    ['/api/v1/monitor-jobs/91/result',{}, {job_id:92,status:'changed'}],
    ['/api/v1/monitor-jobs/claim',{device_id:'a'}, {job:{id:1,lease:'x',recipe:{},revision:1}}],
  ];
  for (const [path,payload,reply] of cases) await assert.rejects(request({server:'http://localhost'},path,payload,{fetcher:async()=>new Response(JSON.stringify({ok:true,schema_version:1,...reply}),{headers:{'Content-Type':'application/json'}})}));
});


test('unrelated user IDs in page content cannot bind the school account', () => {
  const {R} = environment('moodle', '<main id="region-main"><div data-userid="another-student">Other student</div><a href="/mod/assign/view.php?id=1001">作业</a></main>', 'http://localhost:8098/my/', '');
  assert.equal(R.scan().account, '');
});

test('401 waits for backend re-login; transient failures stop after three attempts', async () => {
  const data={}; const storage={get:async k=>({[k]:structuredClone(data[k])}),set:async p=>Object.assign(data,structuredClone(p))};
  const cfg={server:'http://localhost',uid:1};
  const authBox=new Outbox(storage,async()=>request(cfg,'/api/v1/captures',{}, {fetcher:async()=>new Response('{"error":"unauthorized"}',{status:401,headers:{'Content-Type':'application/json'}})}));
  await authBox.add(cfg,'/api/v1/captures',{request_id:'auth'}); await authBox.flush(cfg);
  assert.equal(data.outbox[0].state,'auth_required');
  await authBox.retry({...cfg,uid:2}); assert.equal(data.outbox[0].state,'auth_required');
  const retryData={};const retryStorage={get:async k=>({[k]:structuredClone(retryData[k])}),set:async p=>Object.assign(retryData,structuredClone(p))};let attempts=0;
  const offline=new Outbox(retryStorage,async()=>{attempts++;throw Error('backend_unavailable');});
  await offline.add(cfg,'/api/v1/captures',{request_id:'offline'});
  for(let i=0;i<4;i++){retryData.outbox[0].next=0;await offline.flush(cfg);}
  assert.equal(attempts,3);assert.equal(retryData.outbox[0].state,'failed');
});
