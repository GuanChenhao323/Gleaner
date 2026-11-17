// Actual local HTTP + actual extraction modules in a simulated DOM. Not real Chrome.
import assert from 'node:assert/strict';
import {rendered,storage} from './scoped-fixture.mjs';
import {request} from '../lib/api.js';
import {Outbox} from '../lib/outbox.js';
import {DraftRepository} from '../extraction/drafts.js';
import {PageExtractionService} from '../extraction/service.js';
const server='http://127.0.0.1:8080',url='http://127.0.0.1:8098/generic';
const login=await request({server},'/api/auth/login',{email:'demo@gleaner.test',password:'demo12345'},{login:true});
const cfg={server,uid:login.user.id,token:login.token},store=storage(),box=new Outbox(store),payloads=[];
const service=new PageExtractionService({browser:{tabs:{get:async id=>({id,url})},permissions:{contains:async()=>true}},repository:new DraftRepository(store),config:async()=>cfg,
  reader:{read:async(_,intent)=>{const response=await fetch(url);assert.equal(response.status,200);const page=rendered(await response.text(),url);return JSON.parse(JSON.stringify(page.context.CampusScoped.execute({intent})));}},
  accountKey:async()=>{throw Error('generic account must remain unknown');},enqueueWeb:async(_,body)=>{const payload={...body,device_id:'generic-http-fixture'};payloads.push(payload);await box.add(cfg,'/api/v1/web-captures',payload);return {request_id:body.request_id};}});
const query='项目会议',binding={kind:'labeled',label:'通用 HTTP 集成测试'};
const {id}=await service.start(cfg,{version:2,request_id:crypto.randomUUID(),tabId:1,url,query});await service.queue;
const task=await service.handle(cfg,{type:'extract.get',id});assert.equal(task.state,'succeeded');assert.equal(task.result.source,'generic');assert.equal(task.result.candidates.length,2);assert.ok(!JSON.stringify(task.result.candidates).includes('无关第三条'));assert.equal(payloads.length,0);
await service.handle(cfg,{type:'extract.save',id,query,source_binding:binding});await box.flush(cfg);
const row=(await box.all())[0];assert.equal(row.state,'confirmed');const result=row.response.results[0];
assert.deepEqual(await request(cfg,'/api/v1/web-captures',payloads[0]),row.response);
const repeat={...payloads[0],request_id:crypto.randomUUID()};const again=await request(cfg,'/api/v1/web-captures',repeat);assert.equal(again.results[0].item_id,result.item_id);assert.equal(again.results[0].status,'unchanged');
const changed=structuredClone(repeat);changed.request_id=crypto.randomUUID();changed.fragments=changed.fragments.slice(1);changed.fragments[0].text=changed.fragments[0].evidence.text='项目会议：本轮明确预览并保存的模拟变更 '+changed.request_id;
const update=await request(cfg,'/api/v1/web-captures',changed);assert.equal(update.results[0].item_id,result.item_id);assert.equal(update.results[0].status,'changed');
const auth={headers:{Authorization:`Bearer ${cfg.token}`}},detail=await fetch(server+`/api/items/${result.item_id}`,auth).then(r=>r.json());assert.equal(detail.web_capture.fragments.length,1);assert.equal(detail.browser_monitor,null);assert.equal(detail.web_capture.account_state,'unverified');assert.equal(detail.deadline_at,null);
const versions=await fetch(server+`/api/items/${result.item_id}/versions`,auth).then(r=>r.json());assert.ok(versions.versions[0].changed_fields.body);
const list=await request(cfg,'/api/v1/web-captures');assert.ok(list.collections.some(r=>r.id===result.item_id));
console.log(JSON.stringify({evidence:'simulated DOM + real local HTTP',source:'generic',matched:2,unmatched_excluded:true,explicit_save:true,retry_idempotent:true,same_url_query_updates_same_collection:true,version:update.results[0].version,item_id:result.item_id,capture_id:result.capture_id,fragment_count_after_update:1,no_monitor:true,flutter_detail_contract:true}));
