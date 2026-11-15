// Executes the actual MV3 worker with simulated Chrome APIs; this is not a Chrome acceptance test.
import test from 'node:test';
import assert from 'node:assert/strict';
import { webcrypto } from 'node:crypto';
globalThis.crypto ??= webcrypto;
const cfg = {server:'http://localhost:8080', uid:1, token:'test-token'};
const clone = v => v === undefined ? undefined : structuredClone(v);
async function boot(data, fetcher, {drain=true}={}) {
  let listener;
  const removed = [];
  const storage = {
    get: async keys => Object.fromEntries((Array.isArray(keys) ? keys : [keys]).map(k => [k, clone(data[k])])),
    set: async patch => Object.assign(data, clone(patch)),
    remove: async k => { delete data[k]; },
  };
  globalThis.fetch = (url,options)=>url.endsWith('/reading-devices/heartbeat')
    ? Promise.resolve(json(envelope({device_id:JSON.parse(options.body).device_id}))) : fetcher(url,options);
  globalThis.chrome = {
    storage:{local:storage},
    runtime:{ id:'test-extension', getURL:p=>'chrome-extension://test-extension/'+p,
      onInstalled:{addListener(){}},onStartup:{addListener(){}},onMessage:{addListener(fn){listener=fn;}} },
    alarms:{get:async()=>({name:'campus-radar'}),create(){throw Error('must not reset existing alarm');},onAlarm:{addListener(){}}},
    tabs:{query:async()=>[],get:async id=>({id,url:data.ownedTabs?.[id]}),remove:async id=>removed.push(id)},
  };
  await import(`../background.js?test=${crypto.randomUUID()}`);
  const send = value => new Promise(resolve=>listener(value,{id:'test-extension',url:'chrome-extension://test-extension/popup.html'},resolve));
  if(drain) await send({type:'status'}); // serialized maintenance drains startup
  return {send, removed};
}
const json = obj => new Response(JSON.stringify(obj), {headers:{'Content-Type':'application/json'}});
const envelope = obj => ({schema_version:1,ok:true,...obj});
const candidate = id => ({candidate_id:id,entity_id:id,needs_detail:false,supported:true,
  locator:{url:'http://localhost:8098/portal#news',frame_url:'http://localhost:8098/portal#news',view:{}},
  recipe:{adapter:'student',version:1,entity_id:id,url:'http://localhost:8098/portal#news',view:{},selector:`[data-notice-id="${id}"]`},
  raw:{title:id,text:'User previewed exactly this snapshot',fields:{}}});

test('persisted submission survives popup loss and worker replacement; lost response replays same batch', async()=>{
  const data={config:cfg,device:'device-a',salt:'salt-a'}, committed=new Map(); let lose=true;
  const fetcher=async(url, options)=>{
    if(url.endsWith('/claim')) return json(envelope({job:null}));
    const body=JSON.parse(options.body);
    if(!committed.has(body.request_id)) committed.set(body.request_id, envelope({request_id:body.request_id,results:body.targets.map((t,i)=>({candidate_id:t.candidate_id,status:'new',item_id:i+1,monitor_id:i+1}))}));
    if(lose){lose=false;throw Error('response lost after server commit');}
    return json(committed.get(body.request_id));
  };
  let worker=await boot(data,fetcher);
  const selected=[candidate('notice:a'),candidate('notice:b')];
  const accepted=await worker.send({type:'submit',selected,binding:{adapter:'student',origin:'http://localhost:8098',account_key:'account-a'},enabled:true,tabId:999});
  assert.equal(accepted.ok,true);
  await worker.send({type:'status'}); // no popup/target tab is needed after acceptance
  assert.equal(data.outbox[0].state,'pending');
  const payload=clone(data.outbox[0].body);
  assert.deepEqual(payload.targets.map(t=>t.entity_id),['notice:a','notice:b']);
  assert.equal(payload.targets[0].raw.text,selected[0].raw.text);
  data.outbox[0].next=0;
  worker=await boot(data,fetcher);
  const status=await worker.send({type:'status'});
  assert.equal(status.value.entries[0].state,'confirmed');
  assert.equal(committed.size,1);
  assert.equal(data.outbox[0].body,undefined);
  assert.equal(data.intents[0].selected,undefined);
});

test('unpreviewed detail is rejected; recovery reports interrupted lease and cleans only owned tabs',async()=>{
  const job={id:91,device_id:'device-a',lease:'lease-a',revision:1}; const sent=[];
  const data={config:cfg,device:'device-a',salt:'salt-a',ownedTabs:{51:'http://localhost:8098/portal#news'},activeJob:{scope:cfg.server+'|1',job,queued:false}};
  const worker=await boot(data,async(url,options)=>{
    if(url.endsWith('/claim'))return json(envelope({job:null}));
    sent.push(JSON.parse(options.body));return json(envelope({job_id:91,status:'failed',result:'failed'}));
  });
  assert.deepEqual(worker.removed,[51]);
  assert.equal(sent[0].status,'failed');assert.equal(data.activeJob,undefined);
  const invalid=await worker.send({type:'submit',selected:[{...candidate('notice:a'),needs_detail:true}],binding:{}});
  assert.equal(invalid.ok,false);assert.equal(invalid.error,'preview_required');
});


test('config and draft queries remain responsive while monitor navigation is pending',async()=>{
  let release,entered;const waiting=new Promise(r=>release=r),started=new Promise(r=>entered=r);
  const data={config:cfg,device:'device-a',salt:'salt-a'};
  const worker=await boot(data,async()=>{entered();await waiting;return json(envelope({job:null}));},{drain:false});
  await started;
  let timer;try {
    const value=await Promise.race([worker.send({type:'config'}),new Promise((_,reject)=>{timer=setTimeout(()=>reject(Error('config blocked by monitor')),100);})]);
    assert.equal(value.value.uid,1);assert.equal(value.value.token,undefined);
    const tasks=await worker.send({type:'extract.list'});assert.deepEqual(tasks.value.tasks,[]);
  } finally {clearTimeout(timer);release();await worker.send({type:'status'});}
});

test('generic outbox survives popup loss, closed source and worker replacement with the same collection receipt',async()=>{
  const id=crypto.randomUUID(),url='https://unregistered.example.test/inbox#loaded',text='项目会议的列表摘要';
  const fragment={candidate_id:'candidate-1',record_type:'web_fragment',save_allowed:true,raw:{title:'项目会议',text,fields:{}},evidence:[{channel:'dom',locator:'div:nth-child(1)',text}],context:{frame_url:url,boundary:'table_row',completeness:'fragment',matched_by:'literal'}};
  const task={id,owner:cfg.server+'|1',schema_version:2,state:'succeeded',url,tabId:999,query:'项目会议',expires_at:Date.now()+3600000,result:{source:'generic',url,title:'虚构列表',observed_at:Date.now(),intent:{query:'项目会议',match_scope:'content'},candidates:[fragment]}};
  const data={config:cfg,device:'device-a',salt:'salt-a',extractionDrafts:[task]},committed=new Map();let lost=true;
  const fetcher=async(url,options)=>{
    if(url.endsWith('/claim'))return json(envelope({job:null}));
    assert.ok(url.endsWith('/web-captures'));const body=JSON.parse(options.body);
    assert.equal(body.binding,undefined);assert.equal(body.fragments.length,1);
    if(!committed.has(body.request_id))committed.set(body.request_id,envelope({request_id:body.request_id,candidate_ids:['candidate-1'],results:[{candidate_id:'collection',capture_id:crypto.randomUUID(),item_id:91,source_id:92,version:1,fragment_count:1,status:'new'}]}));
    if(lost){lost=false;throw Error('lost acknowledgement');}return json(committed.get(body.request_id));
  };
  let worker=await boot(data,fetcher);
  const message={type:'extract.save',id,query:'项目会议',source_binding:{kind:'labeled',label:'模拟学校邮箱'}};
  assert.equal((await worker.send(message)).ok,true);await worker.send({type:'status'});
  assert.equal(data.outbox[0].state,'pending');data.outbox[0].next=0;
  worker=await boot(data,fetcher);const status=await worker.send({type:'status'});
  assert.equal(status.value.entries[0].state,'confirmed');assert.equal(committed.size,1);
  assert.equal((await worker.send(message)).value.request_id,id);assert.equal(data.outbox.length,1);
  assert.equal((await worker.send({type:'extract.get',id})).value.result.candidates[0].raw.text,text);
});

test('connection probe verifies real profile, rejects empty/expired sessions and never exposes credentials',async()=>{
  const data={config:{...cfg,email:'demo@example.test'},device:'device-a',salt:'salt-a'};
  let mode='valid';
  const worker=await boot(data,async url=>{
    if(url.endsWith('/claim'))return json(envelope({job:null}));
    assert.ok(url.endsWith('/api/me'));
    if(mode==='empty')return json({});
    if(mode==='expired')return new Response(JSON.stringify({error:'unauthorized'}),{status:401,headers:{'Content-Type':'application/json'}});
    if(mode==='mismatch')return json({id:2,email:'other@example.test'});
    return json({id:1,email:'demo@example.test',mqtt_password:'not-for-the-popup'});
  });
  assert.deepEqual((await worker.send({type:'connection.check'})).value,{state:'connected',uid:1,email:'demo@example.test'});
  for(const [next,error] of [['empty','invalid_session_response'],['expired','unauthorized'],['mismatch','backend_account_changed']]){
    mode=next;assert.equal((await worker.send({type:'connection.check'})).error,error);
  }
});

test('connection check remains responsive while monitor claim waits',async()=>{
  let release,entered;const waiting=new Promise(r=>release=r),started=new Promise(r=>entered=r);
  const worker=await boot({config:cfg,device:'device-a',salt:'salt-a'},async url=>{
    if(url.endsWith('/api/me'))return json({id:1,email:'demo@example.test'});
    entered();await waiting;return json(envelope({job:null}));
  },{drain:false});
  await started;let timer;
  try{
    const probe=await Promise.race([worker.send({type:'connection.check'}),new Promise((_,reject)=>{timer=setTimeout(()=>reject(Error('probe blocked by monitor')),200);})]);
    assert.equal(probe.value.state,'connected');
  }finally{clearTimeout(timer);release();await worker.send({type:'status'});}
});

test('connection reply from a previous owner is rejected after config changes',async()=>{
  let release,entered;const waiting=new Promise(r=>release=r),started=new Promise(r=>entered=r);
  const data={config:cfg,device:'device-a',salt:'salt-a'};
  const worker=await boot(data,async url=>{
    if(url.endsWith('/claim'))return json(envelope({job:null}));
    entered();await waiting;return json({id:1,email:'demo@example.test'});
  });
  const probe=worker.send({type:'connection.check'});await started;
  data.config={...cfg,uid:2};release();assert.equal((await probe).error,'backend_account_changed');
});
