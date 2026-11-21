import test from 'node:test';
import assert from 'node:assert/strict';
import {webcrypto} from 'node:crypto';
import {rendered,courses,parser} from './scoped-fixture.mjs';
import {ReadingRecipeFactory} from '../monitoring/recipe.js';
import {ConditionalPageReader,SourceSessionVerifier,PageReentry} from '../monitoring/page-session.js';
import {ReadingJobExecutor} from '../monitoring/jobs.js';
import {ExtractionPipeline} from '../extraction/pipeline.js';
import {Outbox} from '../lib/outbox.js';
import {request} from '../lib/api.js';
globalThis.crypto??=webcrypto;
const cfg={server:'http://localhost:8080',uid:1,token:'test'},url='https://moodle.must.edu.mo/my/';
const memory=()=>{const values={};return {values,get:async k=>({[k]:structuredClone(values[k])}),set:async p=>Object.assign(values,structuredClone(p)),remove:async k=>{delete values[k];}};};
function native() {
  const page=rendered(courses());page.document.body.setAttribute('data-userid','7');
  const intent={...parser.parse('网络编程的作业'),match_scope:'content'},snapshot=page.read(intent.query);
  const result=new ExtractionPipeline().extract(snapshot,intent);
  result.binding={adapter:'moodle',origin:new URL(url).origin,account_key:'key-7'};
  const task={url,query:intent.query,intent,match_scope:'content',choice:'',result};
  return {page,snapshot,recipe:new ReadingRecipeFactory().create(task)};
}
test('frozen recipe preserves original query, view, route and hashed binding without cookies',()=>{
  const {recipe}=native();assert.equal(recipe.query,'网络编程的作业');assert.equal(recipe.binding.account_key,'key-7');assert.equal(recipe.intent.kind,'assignments');
  assert.ok(!JSON.stringify(recipe).includes('Cookie'));
});
test('same scoped DOM reader returns only matched native activities and verifies account before upload',async()=>{
  const {snapshot,recipe}=native();const reader=new ConditionalPageReader({read:async()=>snapshot},new SourceSessionVerifier(async()=> 'key-7'));
  const data=await reader.read({id:1,recipe});assert.deepEqual(data.snapshot.targets.map(t=>t.entity_id),['assignment:1101','assignment:1102']);
  assert.ok(data.snapshot.targets.every(t=>t.recipe.version===2&&!t.enabled));assert.ok(!JSON.stringify(data).includes('数据科学'));
  await assert.rejects(new ConditionalPageReader({read:async()=>snapshot},new SourceSessionVerifier(async()=> 'other')).read({id:1,recipe}),/account_mismatch/);
});
test('empty, partial and changed-view reads fail without creating a successful snapshot',async()=>{
  const {snapshot,recipe}=native(),verifier=new SourceSessionVerifier(async()=> 'key-7');
  await assert.rejects(new ConditionalPageReader({read:async()=>({...snapshot,records:[]})},verifier).read({id:1,recipe}),/no_match/);
  const partial=structuredClone(snapshot);partial.records[0].complete=false;
  await assert.rejects(new ConditionalPageReader({read:async()=>partial},verifier).read({id:1,recipe}),/preview_only/);
  await assert.rejects(new ConditionalPageReader({read:async()=>snapshot},verifier).read({id:1,recipe:{...recipe,view:{semester:'wrong'}}}),/view_mismatch/);
});
test('unknown private source is not promoted from a label into an authenticated account',async()=>{
  await assert.rejects(new SourceSessionVerifier(async()=>{throw Error('must not guess');}).verify({source:'generic',binding:{account_key:'unverified'}},{source:'generic'}),/account_unknown/);
});
test('background reentry creates its own tab and preserves a tab adopted by the user',async()=>{
  const store=memory(),{recipe}=native(),removed=[];let tab,adopt=false;
  const browser={runtime:{getURL:p=>'chrome-extension://test/'+p},permissions:{contains:async()=>true},tabs:{create:async input=>(tab={id:22,...input,status:'complete'}),update:async(_,p)=>Object.assign(tab,p),get:async()=>({...tab,active:adopt}),remove:async id=>removed.push(id)}};
  const port={metadata:async()=>({url,login:false}),read:async()=>{adopt=true;return {url};}};
  const reentry=new PageReentry(browser,store,port,{pause:async()=>{}});
  assert.equal((await reentry.read(recipe,1)).url,url);assert.deepEqual(removed,[]);assert.deepEqual(store.values.readingTabs,{});
  adopt=false;port.read=async()=>({url});await reentry.read(recipe,2);assert.deepEqual(removed,[22]);
});
test('wrong account is rejected before reading private body content',async()=>{
  const store=memory(),{recipe}=native();let tab,bodyReads=0;
  const browser={runtime:{getURL:p=>'chrome-extension://test/'+p},permissions:{contains:async()=>true},tabs:{create:async p=>(tab={id:31,...p,status:'complete'}),update:async(_,p)=>Object.assign(tab,p),get:async()=>tab,remove:async()=>{}}};
  const port={metadata:async()=>({url,source:'moodle',login:false,account:{state:'known',native:'other'}}),read:async()=>{bodyReads++;throw Error('private body must not be read');}};
  const reentry=new PageReentry(browser,store,port);
  const reader=new ConditionalPageReader(reentry,new SourceSessionVerifier(async()=> 'key-other'));
  await assert.rejects(reader.read({id:1,recipe}),/account_mismatch/);assert.equal(bodyReads,0);
});
test('strict job response rejects empty objects, wrong devices and unconfirmed result codes',async()=>{
  const fetcher=async()=>new Response(JSON.stringify({schema_version:1,ok:true,job:{}}),{headers:{'Content-Type':'application/json'}});
  await assert.rejects(request(cfg,'/api/v1/reading-jobs/claim',{device_id:'d'},{fetcher}),/invalid_job_response/);
  const invalid=async()=>new Response(JSON.stringify({schema_version:1,ok:true,job_id:1,status:'unchanged'}),{headers:{'Content-Type':'application/json'}});
  await assert.rejects(request(cfg,'/api/v1/reading-jobs/1/result',{},{fetcher:invalid}),/invalid_result_response/);
});
test('saved content without required source association cannot be announced as a complete save',async()=>{
  const body={request_id:'r',reading:{version:1},targets:[{candidate_id:'c'}]};
  const fetcher=async()=>new Response(JSON.stringify({schema_version:1,ok:true,request_id:'r',results:[{candidate_id:'c',status:'new',item_id:1,monitor_id:1}]}),{headers:{'Content-Type':'application/json'}});
  await assert.rejects(request(cfg,'/api/v1/captures',body,{fetcher}),/invalid_capture_response/);
});
test('interrupted worker recovers via a durable failure and never asserts successful execution',async()=>{
  const storage=memory(),calls=[],job={id:6,device_id:'d',lease:'l',revision:1};
  await storage.set({readingActiveJob:{owner:cfg.server+'|1',job}});
  const api=async(_,path,body)=>{calls.push([path,body]);return path.endsWith('/claim')?{job:null}:path.endsWith('/result')?{schema_version:1,ok:true,job_id:6,status:'failed',result:'worker_interrupted'}:{device_id:'d'};};
  const executor=new ReadingJobExecutor({storage,api,outbox:new Outbox(storage,api),reentry:{cleanup:async()=>{}},reader:{read:async()=>{throw Error('not expected');}},config:async()=>cfg,device:async()=>({device:'d'})});
  await executor.wake(cfg);assert.equal(storage.values.readingActiveJob,undefined);
  assert.equal(calls.find(([p])=>p.endsWith('/result'))[1].status,'worker_interrupted');assert.equal(storage.values.outbox[0].state,'confirmed');
});
test('lost result acknowledgement survives executor replacement and reuses the same payload',async()=>{
  const storage=memory(),job={id:8,device_id:'d',lease:'l',revision:2,recipe:{}},bodies=[];let offered=false,lost=true;
  const api=async(_,path,body)=>{
    if(path.endsWith('/claim')){if(offered)return {job:null};offered=true;return {job};}
    if(path.endsWith('/result')){bodies.push(structuredClone(body));if(lost){lost=false;throw Error('lost response');}return {job_id:8,status:'unchanged',result:'unchanged'};}
    return {device_id:'d'};
  };
  const deps={storage,api,outbox:new Outbox(storage,api),reentry:{cleanup:async()=>{}},reader:{read:async()=>({account_key:'public',snapshot:{fragments:['only matches']}})},config:async()=>cfg,device:async()=>({device:'d'})};
  await new ReadingJobExecutor(deps).wake(cfg);assert.equal(storage.values.outbox[0].state,'pending');storage.values.outbox[0].next=0;
  await new ReadingJobExecutor(deps).wake(cfg);assert.equal(storage.values.outbox[0].state,'confirmed');assert.deepEqual(bodies[0],bodies[1]);
});
