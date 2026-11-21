// Real loopback HTTP + real lifecycle modules with simulated extension storage.
// Input on stdin: {server,token,uid,payload}; use only isolated fixture accounts.
import {request} from '../extension/lib/api.js';
import {CaptureContextSync} from '../extension/lifecycle/capture-context.js';
import {DraftRepository} from '../extension/extraction/drafts.js';
let input='';for await(const chunk of process.stdin)input+=chunk;
const {server,token,uid,payload}=JSON.parse(input),cfg={server,token,uid},owner=`${server}|${uid}`;
if(!['localhost','127.0.0.1','[::1]'].includes(new URL(server).hostname))throw Error('local fixture only');
const data={};
const storage={get:async k=>k===null?structuredClone(data):{[k]:structuredClone(data[k])},set:async p=>Object.assign(data,structuredClone(p)),remove:async keys=>{for(const k of Array.isArray(keys)?keys:[keys])delete data[k];}};
const repo=new DraftRepository(storage),sync=new CaptureContextSync({storage,repository:repo,api:request});
await sync.sync(cfg);
const old=await request(cfg,'/api/v1/web-captures',payload),sid=old.reading_source_id;
await repo.create(owner,{capture_generation:0,result:{private:'fixture old body'}},payload.request_id);
data.outbox=[{scope:owner,path:'/api/v1/web-captures',state:'pending',body:payload}];
await request(cfg,`/api/v1/reading-sources/${sid}`,{revision:1,trash_items:false},{fetcher:(url,options)=>fetch(url,{...options,method:'DELETE'})});
const preview=await request(cfg,`/api/v1/reading-sources/${sid}/purge-preview`);
await request(cfg,`/api/v1/reading-sources/${sid}/purge`,{...preview,schema_version:undefined,ok:undefined,confirm:true});
let rejected=false;
try {await request(cfg,'/api/v1/web-captures',payload);}catch(e){rejected=e.status===409&&e.code==='capture_context_changed';}
const generation=await sync.sync(cfg);
if(!rejected || data.extractionDrafts.length || data.outbox.length)throw Error('old content survived erasure');
const fresh=await request(cfg,'/api/v1/web-captures',{...payload,request_id:crypto.randomUUID(),capture_generation:generation});
if(fresh.results[0].item_id===old.results[0].item_id || fresh.results[0].version!==1)throw Error('old history resurrected');
process.stdout.write(JSON.stringify({generation,old_submission_rejected:rejected,local_previews:0,local_outbox:0,fresh_saved:true}));
