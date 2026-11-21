import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import {parseHTML} from 'linkedom';
import {rendered,parser,storage} from './scoped-fixture.mjs';
import {event,timeline,columns} from './dashboard-fixture.mjs';
import {ExtractionPipeline} from '../extraction/pipeline.js';
import {PageExtractionService} from '../extraction/service.js';
import {DraftRepository} from '../extraction/drafts.js';
import {TimelineSummaryPolicy} from '../extraction/timeline-summary.js';
import {ReadingRecipeFactory} from '../monitoring/recipe.js';
import {ConditionalPageReader,SourceSessionVerifier} from '../monitoring/page-session.js';
import {request} from '../lib/api.js';
import {Outbox} from '../lib/outbox.js';
import {CaptureView} from '../ui/view.js';
import {ReceiptPresenter} from '../ui/receipt-view.js';

const cfg={server:'http://localhost:8080',uid:1,email:'test@example.test',token:'fixture'};
const url='https://moodle.must.edu.mo/my/';
function fixture(known=true) {
  const p=rendered(columns('',timeline(event()+event(9002,{name:'模拟测验',time:'00:00'}))));
  if(known)p.document.body.setAttribute('data-userid','7');
  return p;
}
function harness(known=true) {
  const page=fixture(known),store=storage(),repository=new DraftRepository(store),sent=[];
  const service=new PageExtractionService({browser:{tabs:{get:async id=>({id,url})},permissions:{contains:async()=>true}},repository,
    reader:{read:async(_,intent)=>page.read(intent.query)},config:async()=>cfg,accountKey:async()=> 'key-7',
    enqueue:async()=>{throw Error('must not create native assignments');},enqueueWeb:async()=>{throw Error('must not bypass campus guard');},
    enqueueTimeline:async(_,body)=>{sent.push(body);return {request_id:body.request_id,device_id:'device'};}});
  return {page,store,repository,service,sent};
}
async function preview(h) {
  const {id}=await h.service.start(cfg,{version:2,request_id:crypto.randomUUID(),tabId:1,url,query:'Timeline'});
  await h.service.queue;
  return {id,task:await h.service.handle(cfg,{type:'extract.get',id})};
}

test('authenticated Timeline saves two summary rows as one frozen collection, never native tasks',async()=>{
  const h=harness(),{id,task}=await preview(h);
  assert.equal(task.result.save_mode,'timeline_summary');assert.equal(task.result.candidates.length,2);
  assert.ok(task.result.candidates.every(c=>c.save_allowed && c.entity_id===null && c.target===null && c.completeness==='summary'));
  const input={type:'extract.save',id,query:'Timeline'};
  await h.service.handle(cfg,input);await h.service.handle(cfg,input);
  assert.equal(h.sent.length,1);const body=h.sent[0];
  assert.equal(body.collection_type,'timeline_summary');assert.equal(body.fragments.length,2);
  assert.equal(body.fragments[1].fields.datetime_text,'00:00');assert.equal(body.source_binding.account_key,'key-7');
  assert.equal(body.reading.representation,'timeline_summary');assert.equal(body.reading.query,'Timeline');
  assert.ok(!JSON.stringify(body).includes('entity_id'));
  await assert.rejects(h.service.handle(cfg,{...input,source_binding:{kind:'public',label:'公开网页'}}),/invalid_request/);
});

test('unknown account cannot save summaries; mixed results and old frozen previews are not promoted',async()=>{
  const h=harness(false),{id,task}=await preview(h);
  assert.ok(task.result.candidates.every(c=>!c.save_allowed && c.save_reason==='account_unknown'));
  await assert.rejects(h.service.handle(cfg,{type:'extract.save',id,query:'Timeline'}),/account_unknown/);
  const policy=new TimelineSummaryPolicy(),candidate=task.result.candidates[0];
  assert.equal(policy.apply([candidate,{...candidate,record_type:'course_entry'}],parser.parse('Timeline'),{state:'known'},'moodle').save_mode,undefined);
  assert.equal(policy.apply([candidate],parser.parse('模拟课程'),{state:'known'},'moodle').save_mode,undefined);
  assert.equal(policy.apply([candidate],parser.parse('Timeline'),{state:'known'},'moodle','https://moodle.must.edu.mo/course/view.php?id=1').save_mode,undefined);
  const known=harness(),old=await preview(known);
  delete old.task.result.save_mode;old.task.result.candidates.forEach(c=>{c.save_allowed=false;c.save_reason='timeline_preview_only';});
  await known.repository.update(known.service.owner(cfg),old.id,{result:old.task.result});
  await assert.rejects(known.service.handle(cfg,{type:'extract.save',id:old.id,query:'Timeline'}),/preview_only/);
});

test('background reread preserves original summary representation, time text and account binding',async()=>{
  const h=harness(),{task}=await preview(h),recipe=new ReadingRecipeFactory().create(task);
  const reader=new ConditionalPageReader({read:async()=>h.page.read('Timeline')},new SourceSessionVerifier(async()=> 'key-7'));
  const result=await reader.read({id:1,recipe});
  assert.equal(result.account_key,'key-7');assert.equal(result.snapshot.collection_type,'timeline_summary');
  assert.equal(result.snapshot.fragments.length,2);assert.ok(!result.snapshot.targets);
  assert.equal(result.snapshot.fragments[0].context.completeness,'summary');
});

test('summary outbox survives replacement and refuses a generic or incomplete successful receipt',async()=>{
  const h=harness(),{id}=await preview(h);await h.service.handle(cfg,{type:'extract.save',id,query:'Timeline'});
  const body={...h.sent[0],device_id:'device'},path='/api/v1/timeline-captures';
  const ack={schema_version:1,ok:true,capture_type:'timeline_summary',request_id:id,reading_source_id:1,candidate_ids:body.fragments.map(f=>f.candidate_id),
    results:[{candidate_id:'collection',capture_id:crypto.randomUUID(),item_id:3,source_id:4,version:1,fragment_count:2,status:'new'}]};
  for(const mutate of [r=>({...r,capture_type:undefined}),r=>({...r,reading_source_id:null}),r=>({...r,candidate_ids:['wrong']}),()=>({})]) {
    await assert.rejects(request(cfg,path,body,{fetcher:async()=>new Response(JSON.stringify(mutate(ack)),{headers:{'Content-Type':'application/json'}})}),/invalid_.*response/);
  }
  const api=async(...args)=>request(...args,{fetcher:async()=>new Response(JSON.stringify(ack),{headers:{'Content-Type':'application/json'}})});
  const store=storage();const first=await new Outbox(store,api).add(cfg,path,body);
  await new Outbox(store,api).flush(cfg);assert.equal((await new Outbox(store,api).all())[0].state,'confirmed');
  assert.equal(await new Outbox(store,api).add(cfg,path,body),first);
  const shown=new ReceiptPresenter().present({state:'confirmed',response:ack});
  assert.equal(shown.title,'已保存为 1 份活动摘要资料');assert.match(shown.detail,/2 条活动摘要/);
});

test('popup enables one summary save with truthful scope and blocks oversized groups',async()=>{
  const h=harness(),{task}=await preview(h);
  const {document}=parseHTML(fs.readFileSync(new URL('../popup.html',import.meta.url),'utf8'));
  const view=new CaptureView(document);view.config(cfg);view.connection({state:'connected'});view.task(task);
  assert.equal(view.$('save').disabled,false);assert.match(view.$('save').textContent,/一份活动摘要/);
  assert.match(view.$('preview').textContent,/未读取活动详情/);assert.ok(!view.$('save-hint').textContent.includes('完整且身份明确'));
  task.result.candidates[0].raw.text='x'.repeat(20000);view.task(task);assert.equal(view.$('save').disabled,true);
  assert.match(view.$('save-hint').textContent,/不会截断/);
});
