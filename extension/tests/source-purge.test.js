import test from 'node:test';
import assert from 'node:assert/strict';
import {CaptureContextSync} from '../lifecycle/capture-context.js';
import {DraftRepository} from '../extraction/drafts.js';
import {request} from '../lib/api.js';
import {panelHarness,capture} from './panel-fixture.mjs';
const cfg={server:'http://localhost:8080',uid:1,token:'test'},owner=cfg.server+'|1';
function memory() {const values={};return {values,get:async key=>key===null?structuredClone(values):{[key]:structuredClone(values[key])},set:async v=>Object.assign(values,structuredClone(v)),remove:async keys=>{for(const k of Array.isArray(keys)?keys:[keys])delete values[k];}};}
const context={schema_version:1,ok:true,generation:1,resident_pages:['keep-page'],reading_sources:[{id:20,revision:3}],monitors:[],item_ids:[5]};

test('new erasure epoch removes old owner previews, capture receipts and erased bindings, preserving other owners and valid rules',async()=>{
  const storage=memory();Object.assign(storage.values,{captureContexts:{[owner]:0},extractionDrafts:[{owner,id:'old',expires_at:Date.now()+99999,capture_generation:0,result:{private:'erased'}},{owner:cfg.server+'|2',id:'other',expires_at:Date.now()+99999,result:{private:'keep'}}],outbox:[{scope:owner,path:'/api/v1/web-captures',state:'confirmed',response:{private:'erased'}},{scope:owner,path:'/api/v1/reading-jobs/7/result',context:{reading_source_id:20},body:{revision:3,snapshot:{text:'keep'}},state:'pending'},{scope:owner,path:'/api/v1/reading-jobs/6/result',context:{reading_source_id:19},body:{revision:2,snapshot:{text:'erased'}},state:'pending'},{scope:owner,path:'/api/v1/reading-jobs/5/result',context:{reading_source_id:19},response:{private:'erased'},state:'confirmed'},{scope:cfg.server+'|2',path:'/api/v1/web-captures',body:{private:'other'}}],residentSites:[{owner,pages:[{page_id:'erase-page',rawUrl:'private-token'},{page_id:'keep-page'}]}],[`captureForm.v2:${owner}|1`]:{query:'erase query'},readingActiveJob:{owner,jobs:[{source_id:19,revision:2},{source_id:20,revision:3}]}});
  const sync=new CaptureContextSync({storage,repository:new DraftRepository(storage),api:async()=>context});
  assert.equal(await sync.sync(cfg),1);
  assert.equal(storage.values.extractionDrafts.length,1);assert.equal(storage.values.extractionDrafts[0].id,'other');
  assert.equal(storage.values.outbox.length,2);assert.equal(storage.values.residentSites[0].pages.length,1);
  assert.equal(storage.values.readingActiveJob.jobs.length,1);assert.equal(storage.values.readingActiveJob.jobs[0].source_id,20);
  assert.ok(!JSON.stringify(storage.values).includes('erased'));assert.ok(!JSON.stringify(storage.values).includes('private-token'));
});

test('offline cannot claim a new epoch and same-epoch synchronization preserves newly created drafts',async()=>{
  const storage=memory(),repo=new DraftRepository(storage);storage.values.captureContexts={[owner]:1};
  await repo.create(owner,{capture_generation:1},'new');
  let offline=true;const sync=new CaptureContextSync({storage,repository:repo,api:async()=>{if(offline)throw Error('backend_unavailable');return context;}});
  assert.equal(await sync.sync(cfg,{offline:true}),1);
  await assert.rejects(sync.sync(cfg),/backend_unavailable/);offline=false;
  await sync.sync(cfg);assert.equal((await repo.get(owner,'new')).capture_generation,1);
});

test('HTTP200 empty or malformed capture context is rejected',async()=>{
  for(const data of [{},{schema_version:1,ok:true},{...context,generation:-1},{...context,reading_sources:[{}]},{...context,reading_sources:[null]}]) {
    const fetcher=async()=>new Response(JSON.stringify(data),{headers:{'Content-Type':'application/json'}});
    await assert.rejects(request(cfg,'/api/v1/capture-context',undefined,{fetcher}),/invalid_response|invalid_capture_context/);
  }
});

test('deleted-source rejection offers management and re-extraction instead of connection checks or a pending hint',async()=>{
  const h=await panelHarness();await capture(h);
  const task=h.ctx.tasks.get(h.controller.task.id);task.submission={request_id:task.id};
  h.ctx.entries.set(task.id,{request_id:task.id,state:'rejected',error:'source_deleted'});
  await h.controller.refresh(true);
  assert.equal(h.view.$('receipt-settings').hidden,true);assert.equal(h.view.$('workbench').textContent,'管理已删除来源');
  assert.equal(h.view.$('continue').hidden,false);assert.equal(h.view.$('continue').textContent,'重新提取');
  assert.match(h.view.$('save-hint').textContent,/已被拒绝/);assert.doesNotMatch(h.view.$('save-hint').textContent,/正在核对/);
  h.dispose();
});

test('active popup clears an invalidated preview when worker storage no longer contains it',async()=>{
  const h=await panelHarness();await capture(h);h.ctx.tasks.delete(h.controller.task.id);
  await h.controller.poll();assert.equal(h.controller.task,null);assert.equal(h.controller.form.taskId,null);
  h.dispose();
});
