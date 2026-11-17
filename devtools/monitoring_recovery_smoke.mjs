// Isolated loopback backend + actual extraction/resident/executor modules; browser APIs are simulated.
import assert from 'node:assert/strict';
import {rendered} from '../extension/tests/scoped-fixture.mjs';
import {PageExtractionService} from '../extension/extraction/service.js';
import {DraftRepository} from '../extension/extraction/drafts.js';
import {CaptureContextSync} from '../extension/lifecycle/capture-context.js';
import {request} from '../extension/lib/api.js';
import {Outbox} from '../extension/lib/outbox.js';
import {ResidentTabRegistry} from '../extension/monitoring/resident-registry.js';
import {ResidentCycleReader} from '../extension/monitoring/resident-reader.js';
import {SourceSessionVerifier} from '../extension/monitoring/page-session.js';
import {ReadingJobExecutor} from '../extension/monitoring/jobs.js';

let input='';for await(const part of process.stdin)input+=part;
const cfg=JSON.parse(input),host=new URL(cfg.server).hostname;
assert.ok(['localhost','127.0.0.1','[::1]'].includes(host),'local fixture only');
const memory=()=>{const values={};return {values,get:async k=>k===null?structuredClone(values):{[k]:structuredClone(values[k])},set:async v=>Object.assign(values,structuredClone(v)),remove:async keys=>{for(const k of Array.isArray(keys)?keys:[keys])delete values[k];}};};
const storage=memory(),session=memory(),url='http://127.0.0.1:8098/generic?recovery='+crypto.randomUUID(),device=crypto.randomUUID();
let revision=1,documentId=1,reloads=0;
const snapshot=intent=>JSON.parse(JSON.stringify(rendered(`<main><p>项目会议：模拟版本 ${revision}</p><p>不应采集的其他资料</p></main>`,url).context.CampusScoped.execute({intent})));
const reader={metadata:async()=>({url,source:'generic',login:false,account:{state:'unknown'}}),read:async(_tab,intent)=>snapshot(intent)};
const browser={storage:{session},permissions:{contains:async()=>true},tabs:{get:async id=>({id,url,status:'complete'}),query:async()=>[{id:7,url,status:'complete'}],reload:async()=>{reloads++;documentId++;}},scripting:{executeScript:async x=>x.files?[]:[{result:{document_id:String(documentId),busy:false,view:'[]'}}]}};
const registry=new ResidentTabRegistry(browser,storage,reader,async()=>{throw Error('no account guessing');});
const box=new Outbox(storage),repository=new DraftRepository(storage),context=new CaptureContextSync({storage,repository,api:request});
box.beforeFlush=()=>context.sync(cfg);
const local=async(path,body,method=body===undefined?'GET':'POST')=>{
  if(path.startsWith('/api/v1/'))return request(cfg,path,body,{fetcher:(u,o)=>fetch(u,{...o,method})});
  const response=await fetch(cfg.server+path,{headers:{Authorization:'Bearer '+cfg.token}});
  assert.equal(response.status,200);return response.json();
};
const extraction=new PageExtractionService({browser,repository,reader,residents:registry,config:async()=>cfg,accountKey:async()=>{throw Error('unknown account');},enqueueWeb:async(_cfg,body)=>{
  assert.ok(Object.hasOwn(body,'capture_generation'));
  await box.add(cfg,'/api/v1/web-captures',{...body,device_id:device});return {request_id:body.request_id};
}});
const query='项目会议',id=crypto.randomUUID();
await extraction.start(cfg,{version:2,request_id:id,tabId:7,url,query,capture_generation:await context.sync(cfg)});
await extraction.queue;
await extraction.handle(cfg,{type:'extract.save',id,query,monitoring:{mode:'resident',interval_s:1800}});
await box.flush(cfg);
const saved=(await box.all()).find(r=>r.request_id===id);assert.equal(saved.state,'confirmed',saved.error);
const sid=saved.response.reading_source_id,iid=saved.response.results[0].item_id;
const source=async()=>(await local('/api/v1/reading-sources')).sources.find(s=>s.id===sid);
const cycle=new ResidentCycleReader({browser,registry,reader,config:async()=>cfg,verifier:new SourceSessionVerifier(async()=>{throw Error('no account guessing');}),legacy:{}});
const executor=new ReadingJobExecutor({storage,api:request,outbox:box,reader:cycle,reentry:{cleanup:async()=>{}},config:async()=>cfg,device:async()=>({device})});
// Preserve the gateway's production rate limiter while exercising several cycles quickly.
const runCycle=async()=>{await new Promise(resolve=>setTimeout(resolve,700));await executor.wake(cfg);};
await runCycle();
assert.equal((await source()).last_result,'unchanged');assert.equal((await source()).verified,true);
assert.ok((await source()).last_success_at);assert.equal((await local(`/api/items/${iid}`)).version,1);
revision=2;
for(const expected of ['changed','unchanged']) {
  const s=await source();await local(`/api/v1/reading-sources/${sid}/check`,{revision:s.revision,purpose:'check'});
  await runCycle();assert.equal((await source()).last_result,expected);
}
assert.equal((await local(`/api/items/${iid}`)).version,2);
const goodRead=cycle.read.bind(cycle);cycle.read=async job=>{const result=await goodRead(job);result.snapshot.query='out of scope';return result;};
let s=await source();await local(`/api/v1/reading-sources/${sid}/check`,{revision:s.revision,purpose:'check'});
await runCycle();s=await source();assert.equal(s.last_result,'result_rejected');assert.equal(s.active_job,null);assert.equal(s.paused,true);
assert.ok((await box.all()).some(r=>r.state==='failed'&&r.error==='scope_mismatch'&&!r.body));
const checks=await local(`/api/v1/reading-sources/${sid}/checks`);assert.equal(checks.checks[0].detail.error,'scope_mismatch');
cycle.read=goodRead;
await local(`/api/v1/reading-sources/${sid}/activate`,{revision:s.revision,interval_s:1800});
await runCycle();s=await source();assert.equal(s.verified,true);assert.equal(s.last_result,'unchanged');
assert.equal((await local(`/api/items/${iid}`)).version,2);
assert.equal(s.items[0].id,iid);assert.equal((await local(`/api/items/${iid}/versions`)).versions.length,2);
process.stdout.write(JSON.stringify({first_check:true,original_updated:true,unchanged_version:true,rejection_visible:true,recovery_same_item:true,reloads}));
