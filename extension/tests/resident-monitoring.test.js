import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import vm from 'node:vm';
import {webcrypto} from 'node:crypto';
import {ResidentTabRegistry,stablePageUrl} from '../monitoring/resident-registry.js';
import {ResidentRefreshStrategy,ResidentCycleReader} from '../monitoring/resident-reader.js';
import {SourceSessionVerifier} from '../monitoring/page-session.js';
import {ReadingRecipeFactory} from '../monitoring/recipe.js';
import {ReadingJobExecutor} from '../monitoring/jobs.js';
import {Outbox} from '../lib/outbox.js';
import {PageExtractionService} from '../extraction/service.js';
import {ExtractionPipeline} from '../extraction/pipeline.js';
import {LiteralIntentParser} from '../extraction/intent.js';
import {rendered} from './scoped-fixture.mjs';
import {panelHarness,capture} from './panel-fixture.mjs';
globalThis.crypto??=webcrypto;
const cfg={server:'http://localhost:8080',uid:7,token:'test'};
const url='https://mail.example.test/home?sid=browser-local-secret#/inbox';
const memory=()=>{const values={};return {values,get:async k=>({[k]:structuredClone(values[k])}),set:async p=>Object.assign(values,structuredClone(p)),remove:async k=>{delete values[k];}};};
function harness() {
  const storage=memory(),session=memory(),tabs=new Map([[7,{id:7,url,status:'complete'}]]);
  let documentId=1,busy=false,view='[]',account={state:'unknown'},login=false,reloads=0,bodyReads=0;
  const page=()=>rendered('<main><p>项目会议：当前已加载的内容。</p><p>无关隐私不应读取。</p></main>',url);
  const intent=new LiteralIntentParser().parse('项目会议','content');
  const snapshot=page().context.CampusScoped.execute({intent});
  const reader={metadata:async()=>({url,source:'generic',login,account}),read:async()=>{bodyReads++;return structuredClone(snapshot);}};
  const browser={storage:{session},tabs:{get:async id=>{if(!tabs.has(id))throw Error('closed');return tabs.get(id);},query:async()=>[...tabs.values()],reload:async()=>{reloads++;documentId++;}},scripting:{executeScript:async input=>input.files?[]:[{result:{document_id:String(documentId),busy,view}}]}};
  const registry=new ResidentTabRegistry(browser,storage,reader,async(_source,native)=>native);
  const result=new ExtractionPipeline().extract(JSON.parse(JSON.stringify(snapshot)),intent);
  const task={tabId:7,url,query:intent.query,intent,match_scope:'content',result};
  const recipe=new ReadingRecipeFactory().create({...task,url:stablePageUrl(url)},{kind:'labeled',label:'当前网页会话'});
  return {browser,storage,session,tabs,reader,registry,recipe,task,setBusy:v=>{busy=v;},setView:v=>{view=v;},setAccount:v=>{account=v;},setLogin:v=>{login=v;},counts:()=>({reloads,bodyReads})};
}

test('browser registry stores raw location only locally; same page rules share one session and tab',async()=>{
  const h=harness();
  const a=await h.registry.bind(cfg,h.task,h.recipe),b=await h.registry.bind(cfg,h.task,{...h.recipe,query:'第二条件',view:{projection:'email'}});
  assert.equal(a.page_id,b.page_id);assert.equal(a.session_id,b.session_id);
  assert.equal(stablePageUrl(url),'https://mail.example.test/home#/inbox');
  assert.ok(!JSON.stringify(a).includes('secret'));
  assert.match(h.storage.values.residentSites[0].pages[0].rawUrl,/browser-local-secret/);
  h.tabs.set(8,{id:8,url,status:'complete'});
  await assert.rejects(h.registry.bind(cfg,{...h.task,tabId:8},h.recipe),/monitor_tab_exists/);
  await assert.rejects(h.registry.adopt(cfg,h.recipe),/tab_ambiguous/);
});

test('worker replacement recovers existing binding; browser restart requires explicit rebind',async()=>{
  const h=harness();h.recipe.resident=await h.registry.bind(cfg,h.task,h.recipe);
  const replacement=new ResidentTabRegistry(h.browser,h.storage,h.reader,async(_,a)=>a);
  assert.equal((await replacement.locate(cfg,h.recipe)).tab.id,7);
  await h.session.remove('residentEpoch');
  await assert.rejects(replacement.locate(cfg,h.recipe),/tab_rebind_required/);
  const again=await replacement.adopt(cfg,h.recipe);
  assert.equal(again.page_id,h.recipe.resident.page_id);
  h.tabs.clear();await assert.rejects(replacement.locate(cfg,h.recipe),/tab_missing/);
});

test('known account switch is blocked before body read; unknown account remains explicitly a tab session',async()=>{
  const h=harness();h.setAccount({state:'known',native:'account-a'});
  h.recipe.resident=await h.registry.bind(cfg,h.task,h.recipe);
  h.setAccount({state:'known',native:'account-b'});
  await assert.rejects(new ResidentRefreshStrategy(h.browser,h.registry,h.reader).prepare(cfg,h.recipe),/account_mismatch/);
  await assert.rejects(h.registry.bind(cfg,h.task,h.recipe),/single_account_conflict/);
  assert.equal(h.counts().bodyReads,0);assert.equal(h.counts().reloads,0);
});

test('editing defers refresh; view changes and login failure never become a successful snapshot',async()=>{
  const h=harness();h.recipe.resident=await h.registry.bind(cfg,h.task,h.recipe);
  const strategy=new ResidentRefreshStrategy(h.browser,h.registry,h.reader);
  h.setBusy(true);await assert.rejects(strategy.prepare(cfg,h.recipe),/user_busy/);
  h.setBusy(false);h.setView('["changed semester"]');await assert.rejects(strategy.prepare(cfg,h.recipe),/view_mismatch/);
  h.setView('[]');h.setLogin(true);await assert.rejects(strategy.prepare(cfg,h.recipe),/need_login/);
  assert.equal(h.counts().reloads,0);
});

test('reload must produce a fresh document, not merely a complete old tab',async()=>{
  const h=harness();h.recipe.resident=await h.registry.bind(cfg,h.task,h.recipe);
  h.browser.tabs.reload=async()=>{};
  let now=0;
  const strategy=new ResidentRefreshStrategy(h.browser,h.registry,h.reader,{clock:()=>now,pause:async()=>{now+=250;},timeout:1000});
  await assert.rejects(strategy.prepare(cfg,h.recipe),/render_timeout/);
});

test('one batch refreshes once and reads each rule with strict scoped projections',async()=>{
  const h=harness();h.recipe.resident=await h.registry.bind(cfg,h.task,h.recipe);
  const cycle=new ResidentCycleReader({browser:h.browser,registry:h.registry,reader:h.reader,config:async()=>cfg,verifier:new SourceSessionVerifier(async(_,a)=>a),legacy:{read:async()=>{throw Error('legacy not expected');}}});
  const job={id:1,recipe:h.recipe,purpose:'activate',interval_s:1800};
  await cycle.begin(job);
  const a=await cycle.read(job),b=await cycle.read({...job,id:2,purpose:'check'});
  assert.equal(h.counts().reloads,1);assert.equal(h.counts().bodyReads,2);
  assert.equal(a.account_key,'unverified');assert.equal(a.resident.page_id,h.recipe.resident.page_id);
  assert.equal(b.resident,undefined);assert.equal(a.snapshot.source.url,stablePageUrl(url));
  assert.ok(!JSON.stringify(a).includes('browser-local-secret'));assert.ok(!JSON.stringify(a).includes('无关隐私'));
  cycle.end();assert.equal(cycle.context,null);
});

test('persisted batch recovery submits each unreported lease as interrupted',async()=>{
  const storage=memory(),jobs=[{id:1,lease:'a',revision:1},{id:2,lease:'b',revision:2}],calls=[];
  await storage.set({readingActiveJob:{owner:cfg.server+'|7',jobs}});
  const api=async(_cfg,path,body)=>{calls.push([path,body]);return path.endsWith('/claim')?{job:null}:path.endsWith('/result')?{job_id:Number(path.split('/').at(-2)),status:'failed',result:body.status}:{};};
  await new ReadingJobExecutor({storage,api,outbox:new Outbox(storage,api),reader:{},reentry:{cleanup:async()=>{}},config:async()=>cfg,device:async()=>({device:'test-device'})}).wake(cfg);
  assert.equal(calls.filter(([p])=>p.endsWith('/result')).length,2);
  assert.ok(calls.filter(([p])=>p.endsWith('/result')).every(([,b])=>b.status==='worker_interrupted'));
  assert.equal(storage.values.readingActiveJob,undefined);
});

test('popup defaults to save and monitor without forcing an account-email input',async()=>{
  const h=await panelHarness({monitoring:true});
  assert.equal(h.view.$('auto-monitor').checked,true);
  await capture(h);
  assert.equal(h.view.$('save').disabled,false);
  assert.match(h.view.$('save').textContent,/保存并开启定期监测/);
  await h.controller.save();
  assert.deepEqual(h.messages.find(m=>m.type==='extract.save').monitoring,{mode:'resident',interval_s:1800});
  h.dispose();
});

test('content guard keeps editing text out of its result and survives repeated injections',()=>{
  const h=rendered('<form><textarea>private draft</textarea></form>','https://example.test/');
  h.context.crypto=webcrypto;h.context.getComputedStyle=()=>({display:'block',visibility:'visible'});h.document.hasFocus=()=>false;
  const code=fs.readFileSync(new URL('../content/resident-guard.js',import.meta.url),'utf8');
  vm.runInContext(code,h.context);const first=h.context.CampusResidentGuard.inspect();
  vm.runInContext(code,h.context);const second=h.context.CampusResidentGuard.inspect();
  assert.equal(first.document_id,second.document_id);
  assert.ok(!JSON.stringify(first).includes('private draft'));
});

test('submission written before worker loss reconnects to preview even when original tab is closed',async()=>{
  const id=crypto.randomUUID();let value={id,owner:cfg.server+'|7',state:'succeeded',schema_version:2,save_monitoring:{mode:'resident',interval_s:1800}};
  const repository={recover:async()=>{},get:async()=>structuredClone(value),update:async(_owner,_id,p)=>{value={...value,...p};}};
  const service=new PageExtractionService({repository,findSubmission:async()=>({request_id:id,device_id:'persisted-device'}),reader:{metadata:async()=>{throw Error('closed page must not be required');}}});
  const task=await service.handle(cfg,{type:'extract.get',id});
  assert.equal(task.submission.request_id,id);assert.equal(value.submission.device_id,'persisted-device');
});
