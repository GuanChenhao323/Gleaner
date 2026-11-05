// Executes the actual MV3 worker with simulated Chrome APIs; this is not a Chrome acceptance test.
import test from 'node:test';
import assert from 'node:assert/strict';
import { webcrypto } from 'node:crypto';
globalThis.crypto ??= webcrypto;
const cfg = {server:'http://localhost:8080', uid:1, token:'test-token'};
const clone = v => v === undefined ? undefined : structuredClone(v);
async function boot(data, fetcher) {
  let listener;
  const removed = [];
  const storage = {
    get: async keys => Object.fromEntries((Array.isArray(keys) ? keys : [keys]).map(k => [k, clone(data[k])])),
    set: async patch => Object.assign(data, clone(patch)),
    remove: async k => { delete data[k]; },
  };
  globalThis.fetch = fetcher;
  globalThis.chrome = {
    storage:{local:storage},
    runtime:{ id:'test-extension', getURL:p=>'chrome-extension://test-extension/'+p,
      onInstalled:{addListener(){}},onStartup:{addListener(){}},onMessage:{addListener(fn){listener=fn;}} },
    alarms:{get:async()=>({name:'campus-radar'}),create(){throw Error('must not reset existing alarm');},onAlarm:{addListener(){}}},
    tabs:{query:async()=>[],get:async id=>({id,url:data.ownedTabs?.[id]}),remove:async id=>removed.push(id)},
  };
  await import(`../background.js?test=${crypto.randomUUID()}`);
  const send = value => new Promise(resolve=>listener(value,{id:'test-extension',url:'chrome-extension://test-extension/popup.html'},resolve));
  await send({type:'config'}); // drains the startup queue
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
  await worker.send({type:'config'}); // no popup/target tab is needed after acceptance
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
