import test from 'node:test';
import assert from 'node:assert/strict';
import {webcrypto} from 'node:crypto';
import {rendered,courses,parser,storage} from './scoped-fixture.mjs';
import {normalize} from '../extraction/intent.js';
import {ExtractionPipeline} from '../extraction/pipeline.js';
import {DomPageReader,assertSamePage} from '../extraction/readers.js';
import {DraftRepository} from '../extraction/drafts.js';
import {PageExtractionService} from '../extraction/service.js';
globalThis.crypto??=webcrypto;
const pipeline=new ExtractionPipeline();
const extract=(p,q,choice)=>pipeline.extract(p.read(q,choice),parser.parse(q));
const url='https://moodle.must.edu.mo/my/';
const cfg={server:'http://localhost:8080',uid:1,token:'test-only'};

test('deterministic query grammar supports course, structured keyword, field projection and traditional text',()=>{
  assert.equal(normalize('網絡編程'),'网络编程');
  assert.equal(parser.parse('网络编程的作业').target,'网络编程');
  assert.deepEqual(parser.parse('课程：网络编程；关键词：实验').keyword,'实验');
  const p=parser.parse('这位老师的邮箱和办公室');assert.equal(p.target,'');assert.equal(p.current,true);assert.deepEqual(p.fields,['email','office']);
  assert.equal(parser.parse('奖学金公告').target,'奖学金');
  assert.throws(()=>parser.parse(' '),/query_required/);
  assert.throws(()=>parser.parse('今天截止的作业'),/unsupported_query/);
  assert.throws(()=>parser.parse('规则：全部'),/unsupported_query/);
});

test('course scope precedes body extraction: two matches, unrelated course body never read or serialized',()=>{
  const p=rendered(courses());p.document.body.setAttribute('data-userid','7');
  const excluded=p.document.querySelector('[data-assignment-id="2201"] .activity-description');
  Object.defineProperty(excluded,'textContent',{get(){throw Error('unmatched body was read');}});
  const s=p.read('网络编程的作业'),r=pipeline.extract(s,parser.parse('网络编程的作业'));
  assert.equal(s.extraction.body_reads,2);assert.equal(r.candidates.length,2);
  assert.deepEqual(r.candidates.map(c=>c.entity_id),['assignment:1101','assignment:1102']);
  assert.ok(r.candidates.every(c=>c.save_allowed));assert.ok(!JSON.stringify(r).includes('数据科学'));
});

test('structured keyword filters assignment title before reading any other description',()=>{
  const p=rendered(courses());const s=p.read('课程：网络编程；关键词：1102');
  assert.equal(s.records.length,1);assert.equal(s.extraction.body_reads,1);assert.equal(s.records[0].entity_id,'assignment:1102');
});

test('unmatched course and unmatched keyword are zero, never whole-page fallback',()=>{
  const p=rendered(courses());
  for(const q of ['数据库的作业','课程：网络编程；关键词：不存在']) {const s=p.read(q);assert.equal(s.records.length,0);assert.equal(s.extraction.body_reads,0);}
});

test('ambiguous course asks for scope before bodies; native choice is revalidated',()=>{
  const p=rendered(courses({ambiguous:true}));
  const first=p.read('网络编程的作业');assert.equal(first.state,'needs_choice');assert.equal(first.extraction.body_reads,0);assert.equal(first.choices.length,2);
  const chosen=p.read('网络编程的作业','404');assert.deepEqual(chosen.records.map(r=>r.entity_id),['assignment:4401']);
  assert.throws(()=>p.read('网络编程的作业','999'),/invalid_choice/);
});

test('course entrances and activity summaries stay preview-only, without automatic navigation',()=>{
  const p=rendered(courses({inline:false}));const r=extract(p,'网络编程的作业');
  assert.equal(r.candidates.length,2);assert.ok(r.candidates.every(c=>c.save_reason==='detail_required'));
  const entrance=rendered('<main><a href="/course/view.php?id=101">网络编程</a></main>');
  const s=entrance.read('网络编程的作业');assert.equal(s.records.length,0);assert.equal(s.navigation.length,1);
});

test('assignment detail requires course ownership for a course condition; preserves native activity identity',()=>{
  const html='<nav class="breadcrumb"><a href="/course/view.php?id=101">网络编程</a></nav><main><h1>实验一</h1><div class="activity-description">选中的作业正文</div></main>';
  const p=rendered(html,'https://moodle.must.edu.mo/mod/assign/view.php?id=1101');
  assert.equal(p.read('网络编程的作业').records[0].entity_id,'assignment:1101');
  p.document.querySelector('nav').remove();assert.equal(p.read('网络编程的作业').records.length,0);
});

test('information list filters titles only; login-gated detail cannot be claimed as already read',()=>{
  const p=rendered('<main><a href="https://infoportal-web.must.edu.mo/detail?id=1&category=info.dict.category.notice">奖学金申请通知</a><a href="https://infoportal-web.must.edu.mo/detail?id=2&category=info.dict.category.notice">停水通知</a></main>','https://student-wmweb.must.edu.mo/');
  const r=extract(p,'奖学金公告');assert.equal(r.candidates.length,1);assert.equal(r.candidates[0].raw.text,'奖学金申请通知');assert.equal(r.candidates[0].save_reason,'detail_required');
  assert.equal(p.read('奖学金公告').extraction.body_reads,0);
});

test('information detail excludes volatile counts and generic footer, preserves explicit date text',()=>{
  const p=rendered('<main><article><h1>奖学金通知</h1><dl><dt>發佈時間</dt><dd>2026-11-10</dd></dl><p>申请原始说明</p><p>瀏覽量：10</p></article></main><footer>通用电话0000</footer>','https://infoportal-web.must.edu.mo/detail?id=1');
  const r=extract(p,'奖学金公告');assert.equal(r.candidates.length,1);assert.ok(!r.candidates[0].raw.text.includes('瀏覽量'));assert.ok(!r.candidates[0].raw.text.includes('0000'));assert.equal(r.candidates[0].raw.fields.published_text,'2026-11-10');
});

test('requested personnel fields do not extract CV, navigation or footer; projection identity remains separate',()=>{
  const p=rendered('<header>通用邮箱 fake@example.test</header><main><div class="personnel-introduction"><div class="intro-detail"><div class="name-position-box"><div class="name">样本甲</div><div class="position">讲师</div></div><div class="other-intro">sample@example.test</div><dl><dt>辦公室</dt><dd>X100</dd></dl></div></div><div class="resume-detail wm-editor">不应读取的长篇履历</div></main><footer>通用联系电话0000</footer>','https://fie.must.edu.mo/id-828/person/view/id-1.html');
  const cv=p.document.querySelector('.resume-detail');Object.defineProperty(cv,'textContent',{get(){throw Error('CV was read');}});
  const s=p.read('这位老师的邮箱和办公室'),r=pipeline.extract(s,parser.parse('这位老师的邮箱和办公室'));
  assert.equal(s.extraction.body_reads,0);const c=r.candidates[0];assert.equal(c.save_allowed,true);assert.equal(c.raw.text,'邮箱：sample@example.test\n办公室：X100');assert.deepEqual(c.raw.fields,{subtype:'teacher_profile',email:'sample@example.test',office:'X100'});assert.equal(c.target.locator.view.projection,'email,office');
});

test('missing requested contact field is explicit and never filled from footer',()=>{
  const p=rendered('<meta name="campus-radar-fixture" content="fie"><main><article><h1>样本甲</h1><p>没有个人电话</p></article></main><footer>电话12345</footer>','http://localhost:8098/person/view/id-1.html');
  const c=extract(p,'这位老师的电话').candidates[0];assert.equal(c.save_allowed,false);assert.deepEqual(c.missing_fields,['phone']);assert.ok(!c.raw.text.includes('12345'));
});

test('timetable filters course and retains missing date/week context without inferred recurrence identity',()=>{
  const p=rendered('<main data-semester="2609"><div class="fc-event"><div>网络编程</div><div>09:00 - 11:50</div></div><div class="fc-event"><div>数据科学</div><div>12:30 - 15:20</div></div></main>','https://classtimetable-coes-wmweb.must.edu.mo/my-class-timetable-student');
  const s=p.read('网络编程的课表');assert.equal(s.extraction.body_reads,1);const c=extract(p,'网络编程的课表').candidates[0];assert.equal(c.raw.fields.semester,'2609');assert.equal(c.raw.fields.date_text,'');assert.equal(c.entity_id,null);assert.equal(c.save_allowed,false);assert.ok(c.missing_fields.includes('native_occurrence_id'));
});

test('login, loading shells, unsupported source and changed route/account are distinct failures',()=>{
  assert.throws(()=>rendered('<input type="password">').read('网络编程的作业'),/need_login/);
  assert.throws(()=>rendered('<div id="app">正在加载…</div>').read('作业'),/page_not_ready/);
  assert.equal(rendered('<main>body</main>','https://unknown.test/').read('作业').outcome.status,'no_match');
  assert.throws(()=>assertSamePage({url,account:{native:'a'}},{url,account:{native:'b'}}),/account_mismatch/);
  assert.throws(()=>assertSamePage({url},{url:url+'#next'}),/route_mismatch/);
  assert.throws(()=>extract(rendered(courses()),'奖学金公告'),/wrong_section/);
});

test('DOM reader rejects malformed injection response, bounds render waiting and catches account changes',async()=>{
  const reader=new DomPageReader({scripting:{executeScript:async()=>[{}]}});await assert.rejects(reader.invoke(1,'execute'),/page_read_failed/);
  const timeout=new DomPageReader({}, {timeout:3,pause:()=>new Promise(r=>setTimeout(r,2))});timeout.metadata=async()=>({url,account:{native:'a'}});timeout.invoke=async()=>{throw Error('page_not_ready');};await assert.rejects(timeout.read(1,parser.parse('作业')),/render_timeout/);
  const changed=new DomPageReader({});let n=0;changed.metadata=async()=>({url,account:{native:n++?'b':'a'}});changed.invoke=async()=>({records:[]});await assert.rejects(changed.read(1,parser.parse('作业')),/account_mismatch/);
});

function serviceHarness(options={}) {
  const store=storage(),repository=new DraftRepository(store),sent=[];let active={...cfg};
  const p=rendered(courses());p.document.body.setAttribute('data-userid','7');let reads=0;
  const service=new PageExtractionService({browser:{tabs:{get:async id=>({id,url})},permissions:{contains:async()=>true}},repository,reader:{read:async(_,intent,choice)=>{reads++;return p.read(intent.query,choice);}},config:async()=>active,accountKey:async()=> 'salted-account',enqueue:async(_,body)=>{sent.push(body);return {request_id:body.request_id};},...options});
  return {service,repository,store,sent,setConfig:c=>active=c,reads:()=>reads};
}
const input=(query='网络编程的作业',id=crypto.randomUUID())=>({type:'extract.start',version:2,request_id:id,tabId:1,url,query});
test('read has no upload; one explicit save uploads exactly two, request replay is idempotent',async()=>{
  const h=serviceHarness(),m=input();const {id}=await h.service.handle(cfg,m);await h.service.queue;
  assert.equal(h.sent.length,0);assert.equal((await h.service.handle(cfg,{type:'extract.get',id})).result.account.native,undefined);
  assert.deepEqual(await h.service.handle(cfg,m),{id});assert.equal(h.reads(),1);
  await assert.rejects(h.service.handle(cfg,{type:'extract.save',id,query:m.query,ids:['candidate-1']}),/invalid_request/);assert.equal(h.sent.length,0);
  const result=await h.service.handle(cfg,{type:'extract.save',id,query:m.query});
  assert.equal(result.request_id,id);assert.equal(h.sent.length,1);assert.equal(h.sent[0].enabled,false);assert.deepEqual(h.sent[0].selected.map(c=>c.entity_id),['assignment:1101','assignment:1102']);
  await h.service.handle(cfg,{type:'extract.save',id,query:m.query});assert.equal(h.sent.length,1);
  await assert.rejects(h.service.handle(cfg,{...m,query:'数据科学的作业'}),/idempotency_conflict/);
  await assert.rejects(h.service.handle(cfg,{type:'extract.save',id,query:'数据科学的作业'}),/query_changed/);
});

test('a lost save reply reuses persistent task ID, so enqueue can deduplicate',async()=>{
  const h=serviceHarness(),m=input();const {id}=await h.service.start(cfg,m);await h.service.queue;
  const update=h.repository.update.bind(h.repository);h.repository.update=async(o,i,v)=>{if(v.submission)throw Error('simulated worker loss');return update(o,i,v);};
  await assert.rejects(h.service.handle(cfg,{type:'extract.save',id,query:m.query}),/worker loss/);
  h.repository.update=update;await h.service.handle(cfg,{type:'extract.save',id,query:m.query});assert.equal(h.sent[0].request_id,h.sent[1].request_id);
});

test('empty, zero, incomplete and unknown-account capture cannot save; owner switch isolates drafts',async()=>{
  const h=serviceHarness();await assert.rejects(h.service.start(cfg,input('')),/query_required/);assert.equal(h.reads(),0);
  const {id}=await h.service.start(cfg,input('数据库的作业'));await h.service.queue;await assert.rejects(h.service.handle(cfg,{type:'extract.save',id,query:'数据库的作业'}),/invalid_selection/);
  await assert.rejects(h.service.handle({...cfg,uid:2},{type:'extract.get',id}),/draft_not_found/);
  const unknown=serviceHarness({accountKey:async()=>{throw Error('should not be called');},reader:{read:async(_,intent)=>rendered(courses()).read(intent.query)}});
  const task=await unknown.service.start(cfg,input());await unknown.service.queue;assert.equal((await unknown.repository.get(unknown.service.owner(cfg),task.id)).result.binding,null);
  await assert.rejects(unknown.service.handle(cfg,{type:'extract.save',id:task.id,query:'网络编程的作业'}),/account_unknown/);
});

test('backend account change while reading never produces a successful preview',async()=>{
  let release;const waiting=new Promise(r=>release=r);const h=serviceHarness({reader:{read:async(_,intent)=>{await waiting;return rendered(courses()).read(intent.query);}}});const {id}=await h.service.start(cfg,input());
  await new Promise(r=>setImmediate(r));h.setConfig({...cfg,uid:2});release();await h.service.queue;assert.equal((await h.repository.get(h.service.owner(cfg),id)).error,'backend_account_changed');
});

test('draft TTL, capacity, owner isolation and worker recovery survive service recreation',async()=>{
  const store=storage();let now=1;let repo=new DraftRepository(store,()=>now);const a=await repo.create('a',{});await repo.update('a',a.id,{state:'running'});repo=new DraftRepository(store,()=>now);await repo.recover();assert.equal((await repo.get('a',a.id)).state,'interrupted');
  await assert.rejects(repo.get('b',a.id),/draft_not_found/);now+=86400001;assert.equal((await repo.list('a')).length,0);for(let i=0;i<10;i++)await repo.create('a',{});await assert.rejects(repo.create('a',{}),/draft_limit/);
});

test('injection itself is bounded even if Chrome never answers a page load',async()=>{
  const reader=new DomPageReader({scripting:{executeScript:()=>new Promise(()=>{})}},{timeout:5});
  await assert.rejects(reader.read(1,parser.parse('作业')),/render_timeout/);
});
