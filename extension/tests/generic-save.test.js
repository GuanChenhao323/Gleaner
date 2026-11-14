import test from 'node:test';
import assert from 'node:assert/strict';
import {PageExtractionService} from '../extraction/service.js';
import {DraftRepository} from '../extraction/drafts.js';
import {Outbox} from '../lib/outbox.js';
import {request} from '../lib/api.js';
import {rendered,storage} from './scoped-fixture.mjs';
const cfg={server:'http://localhost:8080',uid:1,token:'fixture-token'};
const url='https://unknown.example.test/mail#inbox', binding={kind:'labeled',label:'学校邮箱'};
const json=data=>new Response(JSON.stringify(data),{headers:{'content-type':'application/json'}});

function harness() {
  const store=storage(),repository=new DraftRepository(store),sent=[];
  const page=rendered('<ul><li>项目会议：第一个摘要</li><li>项目会议：第二个摘要</li><li>无关的第三条</li></ul>',url);
  const service=new PageExtractionService({browser:{tabs:{get:async id=>({id,url})},permissions:{contains:async()=>true}},repository,config:async()=>cfg,
    reader:{read:async(_,intent)=>JSON.parse(JSON.stringify(page.context.CampusScoped.execute({intent})))},accountKey:async()=>{throw Error('not a verified account');},
    enqueue:async()=>{throw Error('must not call native capture');},enqueueWeb:async(_,payload)=>{sent.push(payload);return {request_id:payload.request_id,device_id:'device'};}});
  return {service,repository,sent,store};
}
async function preview(h) {
  const {id}=await h.service.start(cfg,{version:2,request_id:crypto.randomUUID(),tabId:1,url,query:'项目会议',match_scope:'content'});
  await h.service.queue;return id;
}

test('generic preview does not upload; explicit labeled save freezes exactly two matching fragments',async()=>{
  const h=harness(),id=await preview(h);
  assert.equal(h.sent.length,0);assert.equal((await h.repository.get(h.service.owner(cfg),id)).result.candidates.length,2);
  await assert.rejects(h.service.handle(cfg,{type:'extract.save',id,query:'项目会议'}),/source_label_required/);
  const m={type:'extract.save',id,query:'项目会议',source_binding:binding};
  await h.service.handle(cfg,m);await h.service.handle(cfg,m);
  assert.equal(h.sent.length,1);assert.equal(h.sent[0].fragments.length,2);assert.ok(!JSON.stringify(h.sent).includes('无关的第三条'));assert.equal(h.sent[0].binding,undefined);
  await assert.rejects(h.service.handle(cfg,{...m,source_binding:{kind:'labeled',label:'个人邮箱'}}),/idempotency_conflict/);
  await assert.rejects(h.service.handle({...cfg,uid:2},{type:'extract.get',id}),/draft_not_found/);
});

test('worker loss after queue acknowledgement freezes original label and permits same-payload retry',async()=>{
  const h=harness(),id=await preview(h),original=h.repository.update.bind(h.repository);
  h.repository.update=async(...args)=>{if(args[2].submission)throw Error('lost worker');return original(...args);};
  const m={type:'extract.save',id,query:'项目会议',source_binding:binding};
  await assert.rejects(h.service.handle(cfg,m),/lost worker/);
  h.repository.update=original;
  const restarted=new PageExtractionService({...h.service,repository:new DraftRepository(h.store)});
  await assert.rejects(restarted.handle(cfg,{...m,source_binding:{kind:'public',label:'公开网页'}}),/idempotency_conflict/);
  await restarted.handle(cfg,m);assert.deepEqual(h.sent[0],h.sent[1]);
});

test('persistent outbox deduplicates web snapshots before and after confirmation; validates all fragment acknowledgements',async()=>{
  const h=harness(),id=await preview(h);await h.service.handle(cfg,{type:'extract.save',id,query:'项目会议',source_binding:binding});
  const body={...h.sent[0],device_id:'fixture'},store=storage(),box=new Outbox(store),path='/api/v1/web-captures';
  const entry=await box.add(cfg,path,body);assert.equal(await box.add(cfg,path,body),entry);
  await assert.rejects(box.add(cfg,path,{...body,query:'changed'}),/idempotency_conflict/);
  const response={schema_version:1,ok:true,request_id:id,candidate_ids:body.fragments.map(f=>f.candidate_id),results:[{candidate_id:'collection',capture_id:crypto.randomUUID(),source_id:10,item_id:11,version:1,fragment_count:2,status:'new'}]};
  for(const mutate of [r=>({...r,candidate_ids:['candidate-1']}),r=>({...r,results:[]}),r=>({...r,results:[{...r.results[0],item_id:0}]}),()=>({})])
    await assert.rejects(request(cfg,path,body,{fetcher:async()=>json(mutate(response))}),/invalid_.*response/);
  box.api=async(...args)=>request(...args,{fetcher:async()=>json(response)});
  await box.flush(cfg);assert.equal((await box.all())[0].state,'confirmed');assert.equal((await box.all())[0].body,undefined);
  assert.equal(await new Outbox(store).add(cfg,path,body),entry);assert.equal((await box.all()).length,1);
});
