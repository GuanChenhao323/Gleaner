// Real loopback HTTP and production extraction/executor modules with simulated DOM.
// This is not a real Chrome acceptance test and never contacts a production host.
import assert from 'node:assert/strict';
import {rendered,storage} from '../extension/tests/scoped-fixture.mjs';
import {PageExtractionService} from '../extension/extraction/service.js';
import {DraftRepository} from '../extension/extraction/drafts.js';
import {request} from '../extension/lib/api.js';
import {Outbox} from '../extension/lib/outbox.js';
import {ConditionalPageReader,SourceSessionVerifier} from '../extension/monitoring/page-session.js';
import {ReadingJobExecutor} from '../extension/monitoring/jobs.js';

const server='http://localhost:8080',url='http://localhost:8098/generic?smoke='+crypto.randomUUID(),device='reading-http-fixture';
const login=await request({server},'/api/auth/login',{email:'demo@gleaner.test',password:'demo12345'},{login:true});
const cfg={server,uid:login.user.id,token:login.token},store=storage();
store.remove=async k=>{delete store.data[k];};
const outbox=new Outbox(store);
const local=async(path,body,method=body===undefined?'GET':'POST')=>{
  const res=await fetch(server+path,{method,headers:{'Content-Type':'application/json',Authorization:'Bearer '+cfg.token},body:body===undefined?undefined:JSON.stringify(body)});
  const value=await res.json();assert.equal(res.ok,true,JSON.stringify(value));return value;
};
const read=async(_,intent)=>{
  const res=await fetch(url);assert.equal(res.status,200);
  const page=rendered(await res.text(),url);
  return JSON.parse(JSON.stringify(page.context.CampusScoped.execute({intent})));
};
const extraction=new PageExtractionService({browser:{tabs:{get:async id=>({id,url})},permissions:{contains:async()=>true}},repository:new DraftRepository(store),config:async()=>cfg,reader:{read},accountKey:async()=>{throw Error('not a school identity');},enqueueWeb:async(_,body)=>{await outbox.add(cfg,'/api/v1/web-captures',{...body,device_id:device});return {request_id:body.request_id};}});
const query='项目会议';
const {id}=await extraction.start(cfg,{version:2,request_id:crypto.randomUUID(),url,tabId:999,query});await extraction.queue;
const preview=await extraction.handle(cfg,{type:'extract.get',id});assert.equal(preview.result.candidates.length,2);
assert.ok(!JSON.stringify(preview.result).includes('无关第三条'));
await extraction.handle(cfg,{type:'extract.save',id,query,source_binding:{kind:'public',label:'公开网页'}});await outbox.flush(cfg);
const entry=(await outbox.all())[0];assert.equal(entry.state,'confirmed',entry.error);
const sid=entry.response.reading_source_id,iid=entry.response.results[0].item_id;
const get=async()=>(await local('/api/v1/reading-sources')).sources.find(s=>s.id===sid);
let source=await get();assert.equal(source.verified,false);assert.equal(source.last_success_at,null);
const reentry={cleanup:async()=>{},read:async recipe=>read(null,recipe.intent)};
const executor=new ReadingJobExecutor({storage:store,api:request,outbox,reader:new ConditionalPageReader(reentry,new SourceSessionVerifier(async()=>{throw Error('no account guess');})),reentry,config:async()=>cfg,device:async()=>({device})});
await local(`/api/v1/reading-sources/${sid}/check`,{revision:source.revision,purpose:'verify'});await executor.wake(cfg);
source=await get();assert.equal(source.verified,true);assert.equal(source.last_success_at,null);
await local(`/api/v1/reading-sources/${sid}`,{revision:source.revision,mode:'periodic',paused:false,interval_s:1800},'PUT');source=await get();assert.equal(source.mode,'periodic');
await local(`/api/v1/reading-sources/${sid}/check`,{revision:source.revision,purpose:'check'});await executor.wake(cfg);source=await get();assert.equal(source.last_result,'unchanged');
const before=await local(`/api/items/${iid}`);
assert.equal((await fetch('http://localhost:8098/admin/change',{method:'POST'})).ok,true);
await local(`/api/v1/reading-sources/${sid}/check`,{revision:source.revision,purpose:'check'});await executor.wake(cfg);source=await get();assert.equal(source.last_result,'changed');
const item=await local(`/api/items/${iid}`),versions=await local(`/api/items/${iid}/versions`);
assert.equal(item.version,before.version+1);assert.equal(item.reading_source.id,sid);assert.ok(versions.versions[0].changed_fields.body);
await local(`/api/v1/reading-sources/${sid}`,{revision:source.revision,mode:'manual',paused:false,interval_s:1800},'PUT');
console.log(JSON.stringify({evidence:'simulated DOM and browser port + real local HTTP',owner:cfg.uid,source_id:sid,item_id:iid,matched:2,original_query_preserved:true,verified_without_overwriting_baseline:true,unchanged_without_new_version:true,changed_original_version:item.version,strict_receipt:true,final_mode:'manual'}));
