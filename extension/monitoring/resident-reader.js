import {ConditionalPageReader} from './page-session.js';
import {stablePageUrl} from './resident-registry.js';

/** Refresh policy owns navigation and readiness, never extraction or persistence. */
export class ResidentRefreshStrategy {
  constructor(browser,registry,reader,{pause=ms=>new Promise(r=>setTimeout(r,ms)),clock=Date.now,timeout=18000}={}) {Object.assign(this,{browser,registry,reader,pause,clock,timeout});}
  async prepare(cfg,recipe) {
    const context=await this.registry.locate(cfg,recipe),id=context.tab.id;
    const before=await this.reader.metadata(id);
    await this.registry.verify(context.site,before);
    const guard=await this.registry.inspect(id);
    if(guard.busy)throw Error('user_busy');
    if(guard.view!==context.page.view)throw Error('view_mismatch');
    await this.browser.tabs.reload(id,{bypassCache:false});
    const until=this.clock()+this.timeout;let identityPending=false;
    while(this.clock()<until) {
      const tab=await this.browser.tabs.get(id).catch(()=>{throw Error(context.site.account && context.site.account===recipe.binding.account_key?'waiting_page':'tab_missing');});
      if(tab.status==='complete') {
        const fresh=await this.registry.inspect(id);
        if(fresh.document_id===guard.document_id){await this.pause(250);continue;}
        if(fresh.busy)throw Error('user_busy');
        const meta=await this.reader.metadata(id,Math.max(1,until-this.clock()));
        if(meta.login)throw Error('need_login');
        if(stablePageUrl(meta.url)!==recipe.url)throw Error('route_mismatch');
        try {await this.registry.verify(context.site,meta);}
        catch(e){if(e.message!=='account_unknown')throw e;identityPending=true;await this.pause(250);continue;}
        return {...context,id};
      }
      await this.pause(250);
    }
    throw Error(identityPending?'account_unknown':'render_timeout');
  }
}

/** A batch reuses exactly one refreshed page; each rule retains an independent receipt. */
export class ResidentCycleReader {
  constructor({browser,registry,reader,verifier,config,legacy,strategy=new ResidentRefreshStrategy(browser,registry,reader)}) {Object.assign(this,{browser,registry,reader,verifier,config,legacy,strategy});}
  async begin(job) {
    const cfg=await this.config();let recipe=job.recipe;
    if(!recipe.resident) {
      if(job.purpose!=='activate'){this.context=null;return;}
      recipe={...recipe,resident:await this.registry.adopt(cfg,recipe,job.interval_s || 1800)};
    } else if(job.purpose==='activate') {
      // Explicit rebind may adopt an already open matching page after a closed/recycled tab.
      try {await this.registry.locate(cfg,recipe);}
      catch(e) {
        if(!['tab_missing','tab_rebind_required','route_mismatch'].includes(e.message))throw e;
        recipe={...recipe,resident:await this.registry.adopt(cfg,recipe,job.interval_s || recipe.resident.interval_s)};
      }
    }
    this.context=await this.strategy.prepare(cfg,recipe);this.recipe=recipe;
  }
  async read(job) {
    if(!job.recipe.resident && job.purpose!=='activate')return this.legacy.read(job);
    if(!this.context)await this.begin(job);
    const effective={...job,recipe:{...job.recipe,resident:this.recipe.resident}};
    if(effective.recipe.url!==this.recipe.url)throw Error('scope_mismatch');
    const context=this.context;
    const port={read:async(recipe,_id,beforeRead)=>{
      const meta=await this.reader.metadata(context.id);
      await this.registry.verify(context.site,meta);await beforeRead({...meta,url:stablePageUrl(meta.url)});
      const snapshot=await this.reader.read(context.id,recipe.intent,recipe.choice || undefined);
      await this.registry.verify(context.site,await this.reader.metadata(context.id));
      const guard=await this.registry.inspect(context.id);
      if(guard.busy)throw Error('user_busy');
      if(guard.view!==context.page.view)throw Error('view_mismatch');
      return normalizeSnapshot(snapshot);
    }};
    const result=await new ConditionalPageReader(port,this.verifier).read(effective);
    return {...result,...(job.purpose==='activate'?{resident:this.recipe.resident}:{})};
  }
  end(){this.context=null;this.recipe=null;}
}

export function normalizeSnapshot(snapshot) {
  const url=stablePageUrl(snapshot.url);
  return {...snapshot,url,records:snapshot.records?.map(r=>({...r,url:stablePageUrl(r.url || snapshot.url),...(r.context?{context:{...r.context,frame_url:url}}:{})}))};
}
