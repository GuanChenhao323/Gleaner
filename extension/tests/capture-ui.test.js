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
  const client={send:async m=>{messages.push(m);if(m.type==='config')return cfg;if(m.type==='extract.start'){task={id:m.request_id,schema_version:2,state:'succeeded',query:m.query,result:{intent:{query:m.query},candidates:[candidate(1),candidate(2)]}};return {id:task.id};}if(m.type==='extract.get')return structuredClone(task);if(m.type==='extract.save'){task.submission={request_id:task.id};return task.submission;}if(m.type==='status')return {entries:[{request_id:task.id,state:'confirmed',response:{results:[{status:'new',item_id:11},{status:'new',item_id:12}]}}],intents:[]};if(m.type==='extract.list')return {tasks:[]};}};
  const controller=new CaptureController({browser,client,forms,view,location:{href:'chrome-extension://test/popup.html'}});await controller.init();controller.dispose();
  return {controller,view,forms,messages,setTask:t=>task=t};
}

test('popup directly accepts query, previews two without checkboxes and explicitly saves entire batch',async()=>{
  const h=await harness();assert.ok(h.view.$('query'));assert.equal(h.view.document.querySelectorAll('input[type="checkbox"]').length,0);
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
