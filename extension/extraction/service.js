import {ExtractionPipeline} from './pipeline.js';
import {safeUrl, SiteRegistry} from './sites.js';
import {IntentParser,LiteralIntentParser} from './intent.js';
import {WebCapturePayload,sourceBinding} from './web-payload.js';

const UUID=/^[0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i;

/** Orchestrates ports; source DOM rules and UI state do not live in this service. */
export class PageExtractionService {
  constructor({browser,repository,reader,config,accountKey,enqueue,enqueueWeb,pipeline=new ExtractionPipeline(),parser=new IntentParser()}) {
    Object.assign(this,{browser,repository,reader,config,accountKey,enqueue,enqueueWeb,pipeline,parser});
    this.ready=repository.recover(); this.queue=Promise.resolve();
  }
  owner(cfg) { if(!cfg.uid || !cfg.token) throw Error('backend_login_required'); return `${cfg.server}|${cfg.uid}`; }
  async start(cfg,input) {
    await this.ready;
    if(input.version!==2 || !UUID.test(input.request_id || '') || !Number.isInteger(input.tabId) || typeof input.url!=='string' || input.channel || input.section) throw Error('invalid_request');
    if(input.choice!==undefined && !/^\d+$/.test(input.choice)) throw Error('invalid_choice');
    let tab;try {tab=await this.browser.tabs.get(input.tabId);}catch {throw Error('page_read_failed');}
    const url=safeUrl(tab.url);
    if(!url) throw Error('unsupported');
    if(url!==input.url) throw Error('route_mismatch');
    const host=new URL(url).hostname;
    const site=new SiteRegistry().resolve(url);
    if(host==='login.must.edu.mo' || site.source!=='generic' && /\/(login|sso|auth)(\/|\.|$)/i.test(new URL(url).pathname)) throw Error('need_login');
    const scope=input.match_scope || 'content';
    if(!['content','title'].includes(scope))throw Error('invalid_request');
    let intent;
    if(site.source==='generic' && !site.local)intent=new LiteralIntentParser().parse(input.query,scope);
    else {try {intent={...this.parser.parse(input.query),match_scope:scope};}catch(e){if(!site.local)throw e;intent=new LiteralIntentParser().parse(input.query,scope);}}
    if(site.source!=='generic' && scope!=='content')throw Error('unsupported_query');
    if(!(await this.browser.permissions.contains({origins:[new URL(url).origin+'/*']}))) throw Error('permission_denied');
    const values={schema_version:2,tabId:tab.id,url,query:intent.query,match_scope:scope,intent,choice:input.choice || ''};
    const task=await this.repository.create(this.owner(cfg),{...values,signature:JSON.stringify(values)},input.request_id);
    if(task.fresh) this.queue=this.queue.then(()=>this.run(cfg,task)).catch(()=>{});
    return {id:task.id};
  }
  async run(cfg,task) {
    const owner=this.owner(cfg);
    try {
      await this.repository.update(owner,task.id,{state:'running'});
      if(this.owner(await this.config())!==owner) throw Error('backend_account_changed');
      const snapshot=await this.reader.read(task.tabId,task.intent,task.choice || undefined);
      if(snapshot.url!==task.url) throw Error('route_mismatch');
      if(this.owner(await this.config())!==owner) throw Error('backend_account_changed');
      const result=this.pipeline.extract(snapshot,task.intent);
      const key=result.account.state==='unknown'?'':await this.accountKey(result.source,result.account.native);
      result.binding=key?{adapter:result.source,origin:new URL(result.url).origin,account_key:key}:null;
      result.account={state:result.account.state};
      await this.repository.update(owner,task.id,{state:result.state,result});
    } catch(error) { try { await this.repository.update(owner,task.id,{state:'failed',error:error.message}); } catch { /* deleted / expired */ } }
  }
  async handle(cfg,input) {
    await this.ready;
    const owner=this.owner(cfg);
    if(input.type==='extract.start') return this.start(cfg,input);
    if(input.type==='extract.list') return {tasks:await this.repository.list(owner)};
    if(input.type==='extract.get') { const {owner:_,signature,fresh,...task}=await this.repository.get(owner,input.id); return task; }
    if(input.type==='extract.delete') return this.repository.remove(owner,input.id);
    if(input.type==='extract.save') {
      if(Object.keys(input).some(key=>!['type','id','query','source_binding'].includes(key))) throw Error('invalid_request');
      const task=await this.repository.get(owner,input.id);
      if(task.schema_version!==2 || task.state!=='succeeded') throw Error('preview_required');
      if(typeof input.query!=='string' || input.query.trim()!==task.query) throw Error('query_changed');
      if(task.result?.source==='generic') {
        const binding=sourceBinding(input.source_binding);
        if(task.save_binding && JSON.stringify(binding)!==JSON.stringify(task.save_binding))throw Error('idempotency_conflict');
        if(task.submission)return task.submission;
        const payload=new WebCapturePayload().create(task,binding);
        await this.repository.update(owner,task.id,{save_binding:binding});
        if(!this.enqueueWeb)throw Error('worker_unavailable');
        const submission=await this.enqueueWeb(cfg,payload);
        await this.repository.update(owner,task.id,{submission});return submission;
      }
      if(input.source_binding)throw Error('invalid_request');
      if(!task.result?.binding) throw Error('account_unknown');
      const candidates=task.result.candidates;
      if(!candidates.length || candidates.length>30) throw Error('invalid_selection');
      if(candidates.some(c=>!c.save_allowed || !c.target)) throw Error('preview_only');
      if(task.submission) return task.submission;
      const result=await this.enqueue(cfg,{request_id:task.id,tabId:task.tabId,binding:task.result.binding,
        selected:candidates.map(c=>({...c.target,candidate_id:c.candidate_id,needs_detail:false})),enabled:false});
      await this.repository.update(owner,task.id,{submission:result}); return result;
    }
    throw Error('unknown_message');
  }
}
