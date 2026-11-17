import test from 'node:test';
import assert from 'node:assert/strict';
import {rendered,storage} from './scoped-fixture.mjs';
import {AccountBindingService} from '../identity/account-binding.js';
import {SourceSessionVerifier,ConditionalPageReader,PageReentry} from '../monitoring/page-session.js';
import {ReadingRecipeFactory} from '../monitoring/recipe.js';
import {WebCapturePayload} from '../extraction/web-payload.js';
import {PageExtractionService} from '../extraction/service.js';
import {DraftRepository} from '../extraction/drafts.js';
import {webcrypto} from 'node:crypto';
globalThis.crypto??=webcrypto;
const url='https://example.test/inbox',key='a'.repeat(64);
const intent={version:2,query:'项目会议',mode:'literal',match_scope:'content',fields:[]};
function page(account='student-a@example.test') {
  return rendered(`<header><button aria-label="Current account: ${account}">账号</button></header><main><article><h2>项目会议</h2><p>项目会议，合成版本1。正文收件人 other@example.test</p></article></main>`,url);
}
const meta=p=>JSON.parse(JSON.stringify(p.context.CampusScoped.metadata()));
const snapshot=p=>JSON.parse(JSON.stringify(p.context.CampusScoped.execute({intent})));
test('account probe reads explicit controls, ignores body addresses and rejects ambiguous or hidden controls',()=>{
  const p=page();assert.equal(meta(p).account.native,'student-a@example.test');
  p.document.querySelector('button').remove();assert.equal(meta(p).account.state,'unknown');
  p.document.querySelector('header').innerHTML='<span data-account-email="student-a@example.test">账号</span>';
  assert.equal(meta(p).account.state,'known');
  p.document.querySelector('header').insertAdjacentHTML('beforeend','<button aria-label="Current account: student-b@example.test">账号2</button>');assert.equal(meta(p).account.state,'unknown');
  p.document.querySelector('button').setAttribute('hidden','');assert.equal(meta(p).account.native,'student-a@example.test');
});
test('binding is salted, masked and must correspond to the originally observed account',async()=>{
  const p=page(), service=new AccountBindingService({metadata:async()=>meta(p)},async(_,email)=>email.startsWith('student-a')?key:'b'.repeat(64));
  const proof=await service.verify({tabId:1,url,observed_account_key:key});assert.equal(proof.display,'s***@example.test');assert.equal(proof.account_key,key);
  assert.ok(!JSON.stringify(proof).includes('student-a@'));
  await assert.rejects(service.verify({tabId:1,url}),/account_reextract_required/);
  p.document.querySelector('button').setAttribute('aria-label','Current account: student-b@example.test');
  await assert.rejects(service.verify({tabId:1,url,observed_account_key:key}),/account_mismatch/);
});
test('verified private recipe reuses identity in backend payload and verifies before and after body read',async()=>{
  const p=page(), s=snapshot(p);
  const identity=await new AccountBindingService({metadata:async()=>meta(p)},async()=>key).verify({tabId:1,url,observed_account_key:key});
  const {ExtractionPipeline}=await import('../extraction/pipeline.js');
  const result=new ExtractionPipeline().extract(s,intent),binding={kind:'labeled',label:'学校邮箱',identity};
  const task={id:crypto.randomUUID(),url,query:intent.query,intent,result};
  const recipe=new ReadingRecipeFactory().create(task,binding);
  assert.equal(recipe.binding.account_key,key);assert.equal(recipe.account_probe.kind,identity.probe);
  let reads=0,tab;
  const browser={runtime:{getURL:p=>'chrome-extension://test/'+p},permissions:{contains:async()=>true},tabs:{create:async v=>(tab={id:1,...v,status:'complete'}),update:async(_,v)=>Object.assign(tab,v),get:async()=>tab,remove:async()=>{}}};
  const reader={metadata:async()=>meta(p),read:async()=>{reads++;return snapshot(p);}};
  const conditional=new ConditionalPageReader(new PageReentry(browser,storage(),reader),new SourceSessionVerifier(async(_,email)=>email.startsWith('student-a')?key:'b'.repeat(64)));
  const data=await conditional.read({id:1,recipe});assert.equal(reads,1);assert.deepEqual(data.snapshot.source_binding,binding);
  p.document.querySelector('button').setAttribute('aria-label','Current account: student-b@example.test');
  await assert.rejects(conditional.read({id:2,recipe}),/account_mismatch/);assert.equal(reads,1);
  await assert.rejects(new SourceSessionVerifier(async()=>key).verify({...recipe,binding:{account_key:'public'}},meta(p)),/private_source_required/);
  assert.deepEqual(new WebCapturePayload().create(task,binding).source_binding,binding);
});

test('worker requires its own observation and rechecks identity on save, not just the popup label',async()=>{
  const p=page(), repository=new DraftRepository(storage()),cfg={server:'http://localhost:8080',uid:1,token:'test'},sent=[];
  const service=new PageExtractionService({browser:{tabs:{get:async()=>({id:1,url})},permissions:{contains:async()=>true}},repository,reader:{read:async()=>snapshot(p),metadata:async()=>meta(p)},config:async()=>cfg,accountKey:async(_,email)=>email.startsWith('student-a')?key:'b'.repeat(64),enqueueWeb:async(_,body)=>{sent.push(body);return {request_id:body.request_id};}});
  const {id}=await service.handle(cfg,{type:'extract.start',version:2,request_id:crypto.randomUUID(),tabId:1,url,query:intent.query});await service.queue;
  await assert.rejects(service.handle(cfg,{type:'extract.save',id,query:intent.query,source_binding:{kind:'public',label:'公开网页'}}),/private_source_required/);
  const {identity}=await service.handle(cfg,{type:'extract.verifyAccount',id});
  const binding={kind:'labeled',label:'学校邮箱',identity};
  // Chrome storage round-trips do not preserve nested dictionary key order.
  await repository.update(service.owner(cfg),id,{verified_identity:{account_key:identity.account_key,display:identity.display,probe:identity.probe,version:identity.version}});
  p.document.querySelector('button').setAttribute('aria-label','Current account: student-b@example.test');
  await assert.rejects(service.handle(cfg,{type:'extract.save',id,query:intent.query,source_binding:binding}),/account_mismatch/);assert.equal(sent.length,0);
  p.document.querySelector('button').setAttribute('aria-label','Current account: student-a@example.test');
  await service.handle(cfg,{type:'extract.save',id,query:intent.query,source_binding:binding});assert.equal(sent.length,1);assert.equal(sent[0].reading.binding.account_key,key);
});

test('known webmail is never treated as public when account controls are absent',async()=>{
  await assert.rejects(new SourceSessionVerifier(async()=>key).verify({url:'https://wx.mail.qq.com/home/index',source:'generic',binding:{account_key:'public'}},{source:'generic',account:{state:'unknown'}}),/private_source_required/);
});
test('background waits for delayed account controls before reading, missing identity remains bounded',async()=>{
  let time=0,tab,attempt=0,reads=0;
  const browser={runtime:{getURL:p=>'chrome-extension://test/'+p},permissions:{contains:async()=>true},tabs:{create:async v=>(tab={id:9,...v,status:'complete'}),update:async(_,v)=>Object.assign(tab,v),get:async()=>tab,remove:async()=>{}}};
  const recipe={url,source:'generic',binding:{account_key:key},account_probe:{kind:'account-control-email-v1'}};
  const reader={metadata:async()=>({url,source:'generic',account:++attempt>1?{state:'known',native:'student-a@example.test',probe:'account-control-email-v1'}:{state:'unknown'}}),read:async()=>{reads++;return {ok:true};}};
  const verify=new SourceSessionVerifier(async()=>key);
  const reentry=new PageReentry(browser,storage(),reader,{clock:()=>time,pause:async ms=>{time+=ms;},timeout:1000});
  assert.deepEqual(await reentry.read(recipe,1,m=>verify.verify(recipe,m)),{ok:true});assert.equal(reads,1);
  reader.metadata=async()=>({url,source:'generic',account:{state:'unknown'}});
  await assert.rejects(reentry.read(recipe,2,m=>verify.verify(recipe,m)),/account_unknown/);assert.equal(reads,1);
});
