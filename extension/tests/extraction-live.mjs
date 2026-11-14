// Real local HTTP + simulated rendered DOM, never production-school or real-Chrome evidence.
import assert from 'node:assert/strict';
import {rendered,storage} from './scoped-fixture.mjs';
import {request} from '../lib/api.js';
import {Outbox} from '../lib/outbox.js';
import {DraftRepository} from '../extraction/drafts.js';
import {PageExtractionService} from '../extraction/service.js';
const server='http://127.0.0.1:8080',origin='http://127.0.0.1:8098',url=origin+'/capture/moodle-dashboard';
const login=await request({server},'/api/auth/login',{email:'demo@gleaner.test',password:'demo12345'},{login:true});
const cfg={server,uid:login.user.id,token:login.token},store=storage(),outbox=new Outbox(store),queued=[];
const service=new PageExtractionService({browser:{tabs:{get:async id=>({id,url})},permissions:{contains:async()=>true}},repository:new DraftRepository(store),config:async()=>cfg,accountKey:async()=> 'synthetic-intent-v2-account',
  reader:{read:async(_,intent,choice)=>{const r=await fetch(url,{headers:{Cookie:'fixture_account=student-a'}});assert.equal(r.status,200);return rendered(await r.text(),url).read(intent.query,choice);}},
  enqueue:async(_,body)=>{const payload={schema_version:1,request_id:body.request_id,device_id:'intent-v2-live-device',binding:body.binding,targets:body.selected.map(({needs_detail,...r})=>r)};queued.push(payload);await outbox.add(cfg,'/api/v1/captures',payload);return {request_id:body.request_id};},
});
const ordinary=await service.start(cfg,{type:'extract.start',version:2,request_id:crypto.randomUUID(),tabId:1,url,query:'网络编程'});await service.queue;
const preview=await service.handle(cfg,{type:'extract.get',id:ordinary.id});assert.equal(preview.result.candidates.length,3);assert.equal(preview.result.candidates[0].record_type,'course_entry');
await assert.rejects(service.handle(cfg,{type:'extract.save',id:ordinary.id,query:'网络编程'}),/preview_only/);assert.equal(queued.length,0);
const query='网络编程的作业',m={type:'extract.start',version:2,request_id:crypto.randomUUID(),tabId:1,url,query};
const {id}=await service.start(cfg,m);await service.queue;
const task=await service.handle(cfg,{type:'extract.get',id});assert.equal(task.state,'succeeded');assert.equal(task.result.candidates.length,2);assert.equal(queued.length,0);
assert.ok(!JSON.stringify(task.result).includes('数据科学'));assert.ok(!JSON.stringify(task.result).includes('操作系统'));
await service.handle(cfg,{type:'extract.save',id,query});await outbox.flush(cfg);const entry=(await outbox.all())[0];assert.equal(entry.state,'confirmed');const saved=entry.response.results;
assert.deepEqual(queued[0].targets.map(c=>c.entity_id),['assignment:1101','assignment:1102']);assert.notEqual(saved[0].item_id,saved[1].item_id);
assert.deepEqual(await request(cfg,'/api/v1/captures',queued[0]),entry.response);
const repeat={...queued[0],request_id:crypto.randomUUID()};assert.deepEqual((await request(cfg,'/api/v1/captures',repeat)).results.map(r=>r.status),['unchanged','unchanged']);
repeat.request_id=crypto.randomUUID();repeat.targets=structuredClone(repeat.targets);repeat.targets[0].raw.text='用户重新预览后明确保存的合成变化 '+repeat.request_id;
const changed=await request(cfg,'/api/v1/captures',repeat);assert.equal(changed.results[0].item_id,saved[0].item_id);assert.equal(changed.results[0].status,'changed');assert.equal(changed.results[1].status,'unchanged');
const auth={headers:{Authorization:`Bearer ${cfg.token}`}};
const detail=await fetch(server+`/api/items/${saved[0].item_id}`,auth).then(r=>r.json());assert.equal(detail.body,repeat.targets[0].raw.text);assert.equal(detail.browser_monitor.supported,false);
const versions=await fetch(server+`/api/items/${saved[0].item_id}/versions`,auth).then(r=>r.json());assert.equal(versions.versions[0].changed_fields.body[1],repeat.targets[0].raw.text);
console.log(JSON.stringify({evidence:'simulated DOM + real local HTTP, not Chrome',query,content_aside:true,ordinary_preview:3,preview_only_not_submitted:true,matched:2,excluded_courses:2,items:saved.map(r=>r.item_id),same_request_idempotent:true,duplicate_unchanged:true,same_url_independent:true,change_updates_original:true,version:detail.version,monitor_supported:false}));
