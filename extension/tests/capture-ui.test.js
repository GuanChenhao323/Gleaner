import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import {parseHTML} from 'linkedom';
import {CaptureController} from '../ui/controller.js';
import {CaptureView} from '../ui/view.js';
import {CaptureFormStore} from '../ui/form-store.js';
import {storage} from './scoped-fixture.mjs';
const cfg={server:'http://localhost:8080',uid:1,email:'demo@example.test'};
const candidate=id=>({raw:{title:'作业 '+id,text:'目标正文',fields:{}},evidence:[],save_allowed:true,url:'https://moodle.must.edu.mo/mod/assign/view.php?id='+id});
async function harness({permission=async()=>true,tabGet}={}) {
  const {document}=parseHTML(fs.readFileSync(new URL('../popup.html',import.meta.url),'utf8'));
  const store=storage(),forms=new CaptureFormStore(store),view=new CaptureView(document),messages=[];
  let task;
  const browser={tabs:{query:async()=>[{id:1}],get:tabGet || (async()=>({id:1,url:'https://moodle.must.edu.mo/my/',title:'合成面板'}))},permissions:{request:permission,contains:async()=>true}};
  const client={send:async m=>{messages.push(m);if(m.type==='config')return cfg;if(m.type==='connection.check')return {state:'connected',uid:cfg.uid,email:cfg.email};if(m.type==='extract.start'){task={id:m.request_id,schema_version:2,state:'succeeded',query:m.query,result:{intent:{query:m.query},candidates:[candidate(1),candidate(2)]}};return {id:task.id};}if(m.type==='extract.get')return structuredClone(task);if(m.type==='extract.save'){task.submission={request_id:task.id};return task.submission;}if(m.type==='status')return {entries:[{request_id:task.id,state:'confirmed',response:{results:[{status:'new',item_id:11},{status:'new',item_id:12}]}}],intents:[]};if(m.type==='extract.list')return {tasks:[]};}};
  const controller=new CaptureController({browser,client,forms,view,location:{href:'chrome-extension://test/popup.html'}});await controller.init();view.$('auto-monitor').checked=false;controller.form.auto_monitor=false;controller.render();clearInterval(controller.timer);
  return {controller,view,forms,messages,setTask:t=>task=t};
}

test('popup directly accepts query, previews two without checkboxes and explicitly saves entire batch',async()=>{
  const h=await harness();assert.ok(h.view.$('query'));assert.equal(h.view.$('preview').querySelectorAll('input[type="checkbox"]').length,0);
  h.view.$('query').value='网络编程的作业';h.view.$('query').oninput();await h.controller.capture();assert.equal(h.messages.filter(m=>m.type==='extract.save').length,0);assert.equal(h.view.$('preview').querySelectorAll('article').length,2);assert.equal(h.view.$('save').disabled,false);
  await h.controller.save();const save=h.messages.find(m=>m.type==='extract.save');assert.deepEqual(Object.keys(save).sort(),['id','query','type']);assert.match(h.view.$('results').textContent,/新增 2/);assert.equal(h.view.$('save').disabled,true);
});

test('query editing invalidates previous preview and cannot save it',async()=>{
  const h=await harness();h.view.$('query').value='网络编程的作业';await h.controller.capture();h.view.$('query').value='数据科学的作业';h.view.$('query').oninput();assert.equal(h.controller.task,null);assert.equal(h.view.$('save').disabled,true);await h.controller.save();assert.equal(h.messages.filter(m=>m.type==='extract.save').length,0);
});

test('query change during permission dialog cannot start old or new unconfirmed capture',async()=>{
  let grant;const h=await harness({permission:()=>new Promise(r=>grant=r)});h.view.$('query').value='网络编程的作业';const capture=h.controller.capture();h.view.$('query').value='数据科学的作业';h.view.$('query').oninput();grant(true);await capture;assert.equal(h.messages.filter(m=>m.type==='extract.start').length,0);
});

test('denied permission gives no capture, empty input also stops before extraction',async()=>{
  const h=await harness({permission:async()=>false});await assert.rejects(async()=>h.controller.capture(),/query_required/);h.view.$('query').value='网络编程的作业';await assert.rejects(h.controller.capture(),/permission_denied/);assert.equal(h.messages.filter(m=>m.type==='extract.start').length,0);
});

test('reopening popup restores same owner/tab/query and completed preview without rereading page',async()=>{
  const h=await harness();h.view.$('query').value='网络编程的作业';await h.controller.capture();const reloaded=new CaptureController({browser:h.controller.browser,client:h.controller.client,forms:h.forms,view:h.view,location:{href:'chrome-extension://test/popup.html'}});await reloaded.init();reloaded.dispose();assert.equal(reloaded.task.id,h.controller.task.id);assert.equal(h.messages.filter(m=>m.type==='extract.start').length,1);assert.equal(h.view.$('query').value,'网络编程的作业');assert.equal(await h.forms.load({...cfg,uid:2},1),null);
});

test('zero/partial results never enable save; completed snapshot can save after original tab closes',async()=>{
  const h=await harness();h.view.$('query').value='网络编程的作业';await h.controller.capture();const task=structuredClone(h.controller.task);task.result.candidates=[];h.view.task(task);assert.equal(h.view.$('save').disabled,true);task.result.candidates=[{...candidate(1),save_allowed:false,save_reason:'detail_required'}];h.view.task(task);assert.equal(h.view.$('save').disabled,true);
  h.controller.browser.tabs.get=async()=>{throw Error('No tab with id');};await h.controller.save();assert.equal(h.messages.filter(m=>m.type==='extract.save').length,1);
});

test('missing preview on reopen preserves input and leaves a usable new-capture flow',async()=>{
  const h=await harness();await h.forms.write(cfg,{tabId:1,url:'https://moodle.must.edu.mo/my/',query:'网络编程的作业',taskId:'expired',phase:'reading'});
  const original=h.controller.client.send.bind(h.controller.client);let missing=true;
  h.controller.client.send=async m=>{if(m.type==='extract.get' && missing){missing=false;throw Error('draft_not_found');}return original(m);};
  const reopened=new CaptureController({browser:h.controller.browser,client:h.controller.client,forms:h.forms,view:h.view,location:{href:'chrome-extension://test/popup.html'}});
  await reopened.init();try {assert.equal(reopened.form.taskId,null);assert.equal(h.view.$('query').value,'网络编程的作业');await reopened.capture();assert.equal(reopened.task.state,'succeeded');}finally{reopened.dispose();}
});

test('navigation-required and preview-only results do not look like zero matches or saved items',async()=>{
  const h=await harness();const task={schema_version:2,state:'succeeded',query:'测试课程的作业',result:{candidates:[],warnings:[],navigation:[{title:'测试课程',url:'https://moodle.must.edu.mo/course/view.php?id=101'}],outcome:{status:'navigation_required'}}};
  h.view.task(task);assert.match(h.view.$('preview').textContent,/已定位目标课程/);assert.ok(!h.view.$('preview').textContent.includes('匹配 0 条'));assert.equal(h.view.$('save').disabled,true);
  task.result.navigation=[];task.result.outcome={status:'matched'};task.result.candidates=[{...candidate(1),record_type:'course_entry',save_allowed:false,save_reason:'navigation_only'}];
  h.view.task(task);assert.match(h.view.$('preview').textContent,/课程概览 · 仅预览/);assert.match(h.view.$('preview').textContent,/可保存 0 条，仅预览 1 条/);assert.equal(h.view.$('save').disabled,true);
});

test('unsupported DOM renders an explicit failure, not a successful zero-match result',async()=>{
  const h=await harness();h.view.task({state:'failed',error:'unsupported_dom'});assert.match(h.view.$('preview').textContent,/尚未可靠识别此页面结构/);assert.ok(!h.view.$('preview').textContent.includes('匹配 0 条'));
});

test('result groups explain course entries, native assignments, timeline and contacts without changing save selection',async()=>{
  const h=await harness();
  const entries=[{...candidate(1),record_type:'course_entry',save_allowed:false,save_reason:'navigation_only',presentation:{group:'courses',region:'课程概览',matched_by:'course_identity',course_relation:'native'}},{...candidate(2),record_type:'assignment',presentation:{group:'assignments',region:'Recently accessed items',matched_by:'course_identity',course_relation:'native'}},{...candidate(3),record_type:'timeline_event',save_allowed:false,save_reason:'timeline_preview_only',presentation:{group:'timeline',region:'Timeline',matched_by:'section_heading',course_relation:'unconfirmed'}},{...candidate(4),record_type:'contact_info',save_allowed:false,save_reason:'contact_preview_only',presentation:{group:'contacts',region:'Moodle Support',matched_by:'requested_fields',course_relation:'none'}}];
  h.view.task({schema_version:2,state:'succeeded',result:{candidates:entries}});
  const root=h.view.$('preview');assert.deepEqual([...root.querySelectorAll('[data-result-group]')].map(n=>n.dataset.resultGroup),['courses','assignments','timeline','contacts']);assert.equal(root.querySelectorAll('article').length,4);assert.match(root.textContent,/来源区块：Recently accessed items/);assert.match(root.textContent,/尚无原生归属证明/);assert.equal(h.view.$('save').disabled,true);assert.match(h.view.$('save').textContent,/仅预览/);
  h.view.task({schema_version:2,state:'succeeded',result:{candidates:[entries[1]]}});assert.equal(h.view.$('save').disabled,false);
});

test('a missing target region renders failure rather than an apparently successful zero result',async()=>{
  const h=await harness();h.view.task({state:'failed',error:'unsupported_region'});assert.match(h.view.$('preview').textContent,/指定区块不存在/);assert.ok(!h.view.$('preview').textContent.includes('匹配 0 条'));assert.equal(h.view.$('save').disabled,true);
});

test('preview-only guidance leads contacts and timeline to appropriate next actions without duplicate field text',async()=>{
  const h=await harness(),c={...candidate(1),record_type:'contact_info',save_allowed:false,save_reason:'contact_preview_only',raw:{title:'Moodle Support',text:'邮箱：support@example.test',fields:{email:'support@example.test'}}};
  h.view.task({schema_version:2,state:'succeeded',result:{candidates:[c]}});assert.ok(!h.view.$('preview').textContent.includes('课程名的作业'));assert.equal(h.view.$('preview').querySelector('article').querySelectorAll('pre').length,2);assert.equal(h.view.$('save').textContent,'联系信息仅预览');assert.equal(h.view.$('save').disabled,true);
  h.view.task({schema_version:2,state:'succeeded',result:{candidates:[{...c,record_type:'timeline_event',save_reason:'timeline_preview_only'}]}});assert.match(h.view.$('preview').textContent,/重新提取/);assert.equal(h.view.$('save').textContent,'请重新提取以保存活动摘要');assert.equal(h.view.$('save').disabled,true);
});

test('generic source label gates save, while changing matching scope invalidates the old preview',async()=>{
  const h=await harness({tabGet:async()=>({id:1,url:'https://unknown.example.test/'})});
  h.view.$('query').value='项目会议';await h.controller.capture();
  h.controller.task.result.source='generic';h.controller.task.result.candidates.forEach(c=>c.record_type='web_fragment');h.controller.renderTask(h.controller.task);
  assert.equal(h.view.$('save').disabled,true);
  h.view.select('source-kind','labeled');h.view.$('source-kind').onchange();
  h.view.$('source-label').value='学校邮箱';h.view.$('source-label').oninput();assert.equal(h.view.$('save').disabled,true);await h.controller.confirmBinding();assert.equal(h.view.$('save').disabled,false);
  h.view.select('match-scope','title');h.view.$('match-scope').onchange();assert.equal(h.controller.task,null);assert.equal(h.view.$('save').disabled,true);
});

test('reopening after original tab closes restores preview instead of dereferencing absent page metadata',async()=>{
  const h=await harness();h.view.$('query').value='网络编程的作业';await h.controller.capture();
  h.controller.browser.tabs.get=async()=>{throw Error('No tab with id');};
  const reopened=new CaptureController({browser:h.controller.browser,client:h.controller.client,forms:h.forms,view:h.view,location:{href:'chrome-extension://test/popup.html?tab=1'}});
  await reopened.init();try {assert.equal(reopened.task.state,'succeeded');assert.match(h.view.$('page').textContent,/原网页已关闭/);assert.equal(h.view.$('save').disabled,false);await reopened.save();assert.match(h.view.$('results').textContent,/新增 2/);}finally {reopened.dispose();}
});
