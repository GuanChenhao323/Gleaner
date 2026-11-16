import {LoginRequirementPolicy} from '../identity/login-requirement.js';
import {ExtractionPipeline} from '../extraction/pipeline.js';
import {WebCapturePayload} from '../extraction/web-payload.js';
import {TimelineCapturePayload} from '../extraction/timeline-summary.js';

/** Account proof is independent of rendering and extraction. */
export class SourceSessionVerifier {
  constructor(accountKey) {this.accountKey=accountKey;}
  async verify(recipe,result) {
    if(recipe.binding.account_key==='unverified')throw Error('account_unknown');
    if(result.source!==recipe.source)throw Error('route_mismatch');
    if(recipe.source==='generic') {
      if(recipe.binding.account_key==='public') {
        if(new LoginRequirementPolicy().requiresLogin(recipe.url,result.account))throw Error('private_source_required');
        return 'public';
      }
      if(recipe.account_probe?.kind!=='account-control-email-v1' || result.account?.state!=='known' || result.account.probe!==recipe.account_probe.kind)throw Error('account_unknown');
      const key=await this.accountKey('generic',result.account.native);
      if(key!==recipe.binding.account_key)throw Error('account_mismatch');
      return key;
    }
    if(result.account.state==='unknown')throw Error('account_unknown');
    const key=await this.accountKey(result.source,result.account.native);
    if(key!==recipe.binding.account_key)throw Error('account_mismatch');
    return key;
  }
}

/** Own only temporary tabs created by this executor; preserve tabs the user adopts. */
export class PageReentry {
  constructor(browser,storage,reader,{pause=ms=>new Promise(r=>setTimeout(r,ms)),clock=Date.now,timeout=18000}={}) {
    Object.assign(this,{browser,storage,reader,pause,clock,timeout});
  }
  canClose(tab,url) {
    if(tab.active)return false;
    if(tab.url===url || tab.url?.startsWith(this.browser.runtime.getURL('runner.html')))return true;
    try {return new URL(tab.url).origin===new URL(url).origin && /\/(login|auth|sso)(\/|\.|$)/i.test(new URL(tab.url).pathname);}catch{return false;}
  }
  async cleanup() {
    const tabs=(await this.storage.get('readingTabs')).readingTabs || {};
    for(const [id,url] of Object.entries(tabs)) {
      try {if(this.canClose(await this.browser.tabs.get(Number(id)),url))await this.browser.tabs.remove(Number(id));}catch{/* closed */}
    }
    await this.storage.set({readingTabs:{}});
  }
  async read(recipe,jobId,beforeRead) {
    if(recipe.binding.account_key==='unverified')throw Error('account_unknown');
    const origin=new URL(recipe.url).origin;
    if(!(await this.browser.permissions.contains({origins:[origin+'/*']})))throw Error('permission_denied');
    const times=(await this.storage.get('originTimes')).originTimes || {};
    const delay=2100-(Date.now()-(times[origin] || 0));
    if(delay>0)await this.pause(delay);
    times[origin]=Date.now();await this.storage.set({originTimes:times});
    const tab=await this.browser.tabs.create({url:this.browser.runtime.getURL('runner.html')+'#reading-'+jobId,active:false});
    await this.storage.set({readingTabs:{[tab.id]:recipe.url}});
    try {
      await this.browser.tabs.update(tab.id,{url:recipe.url});
      const deadline=this.clock()+this.timeout;let accountPending=false;
      while(this.clock()<deadline) {
        const current=await this.browser.tabs.get(tab.id);
        if(current.status==='complete') {
          const meta=await this.reader.metadata(tab.id,Math.max(1,deadline-this.clock()));
          if(meta.login)throw Error('need_login');
          if(meta.url!==recipe.url)throw Error('route_mismatch');
          try {await beforeRead?.(meta);}
          catch(e) {
            if(e.message!=='account_unknown')throw e;
            accountPending=true;await this.pause(250);continue;
          }
          return await this.reader.read(tab.id,recipe.intent,recipe.choice || undefined);
        }
        await this.pause(250);
      }
      throw Error(accountPending?'account_unknown':'render_timeout');
    } finally {
      try {if(this.canClose(await this.browser.tabs.get(tab.id),recipe.url))await this.browser.tabs.remove(tab.id);}catch{/* closed */}
      await this.storage.set({readingTabs:{}});
    }
  }
}

/** Calls the same scoped DOM port as preview, then projects the strict save contract. */
export class ConditionalPageReader {
  constructor(reentry,verifier,{pipeline=new ExtractionPipeline()}={}) {Object.assign(this,{reentry,verifier,pipeline});}
  async read(job) {
    const recipe=job.recipe;
    const snapshot=await this.reentry.read(recipe,job.id,meta=>this.verifier.verify(recipe,meta));
    if(snapshot.url!==recipe.url)throw Error('route_mismatch');
    const result=this.pipeline.extract(snapshot,recipe.intent);
    const account_key=await this.verifier.verify(recipe,result);
    if(result.state==='needs_choice')throw Error('view_mismatch');
    if(!result.candidates.length)throw Error('no_match');
    if(result.candidates.length>30 || result.candidates.some(c=>!c.save_allowed))throw Error('preview_only');
    for(const candidate of result.candidates)for(const [key,value] of Object.entries(recipe.view)) {
      if((candidate.target?.locator.view?.[key] ?? candidate.raw.fields?.[key])!==value)throw Error('view_mismatch');
    }
    if(recipe.representation==='timeline_summary') {
      const payload=new TimelineCapturePayload().create({id:crypto.randomUUID(),query:recipe.query,result:{...result,binding:recipe.binding}});
      return {account_key,snapshot:payload};
    }
    if(result.save_mode==='timeline_summary')throw Error('view_mismatch');
    if(recipe.source==='generic') {
      const binding=recipe.binding.account_key==='public'?{kind:'public',label:recipe.source_label}:{kind:'labeled',label:recipe.source_label,identity:{version:1,probe:recipe.account_probe.kind,display:recipe.account_probe.display,account_key}};
      const payload=new WebCapturePayload().create({id:crypto.randomUUID(),query:recipe.query,result},binding);
      // The backend retains the initial title and source identity. Only content changes.
      return {account_key,snapshot:payload};
    }
    return {account_key,snapshot:{binding:recipe.binding,targets:result.candidates.map(c=>({...c.target,candidate_id:c.candidate_id}))}};
  }
}
