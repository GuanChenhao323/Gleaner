const owner=cfg=>`${cfg.server}|${cfg.uid}`;
const UUID=/^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/;
export function residentDescriptor(value) {
  if(!value || Object.keys(value).sort().join(',')!=='interval_s,page_id,refresh,session_id,version' || value.version!==1 || !UUID.test(value.session_id || '') || !UUID.test(value.page_id || '') || value.refresh!=='reload' || ![1800,3600,7200].includes(value.interval_s))throw Error('invalid_resident');
  return {version:1,session_id:value.session_id,page_id:value.page_id,refresh:'reload',interval_s:value.interval_s};
}
/** Authentication-bearing location stays in Chrome; stable identity excludes transient tokens. */
export function stablePageUrl(value) {
  const u=new URL(value);
  if(!['http:','https:'].includes(u.protocol) || u.username || u.password)throw Error('unsupported');
  for(const key of [...u.searchParams.keys()])if(/token|ticket|session|password|secret|authorization|^(sid|auth|access_key)$/i.test(key))u.searchParams.delete(key);
  return u.href;
}
export class ResidentTabRegistry {
  constructor(browser,storage,reader,accountKey,{session=browser.storage?.session || storage}={}) {Object.assign(this,{browser,storage,reader,accountKey,session});this.chain=Promise.resolve();}
  async epoch() {
    let value=(await this.session.get('residentEpoch')).residentEpoch;
    if(!value){value=crypto.randomUUID();await this.session.set({residentEpoch:value});}
    return value;
  }
  async presence(cfg) {
    const rows=(await this.storage.get('residentSites')).residentSites || [];
    const sites=rows.filter(site=>site.owner===owner(cfg));
    if(!sites.length)return {};
    const epoch=await this.epoch();
    const tabs=await this.browser.tabs.query({});
    const pages={};
    for(const site of sites)for(const page of site.pages) {
      const tab=tabs.find(t=>t.id===page.tabId);
      let state='unknown';
      if(epoch===page.epoch) {
        if(!tab)state='absent';
        else if(tab.url) {
          try {state=stablePageUrl(tab.url)===page.url?'present':'absent';}
          catch {state='unknown';}
        }
        if(state==='absent' && tabs.some(t=>{
          try{return stablePageUrl(t.url)===page.url;}catch{return false;}
        }))state='unknown';
      }
      pages[page.page_id]=state;
    }
    return pages;
  }
  async inspect(tabId) {
    try {
      await this.browser.scripting.executeScript({target:{tabId,frameIds:[0]},files:['content/resident-guard.js']});
      const [r]=await this.browser.scripting.executeScript({target:{tabId,frameIds:[0]},func:()=>globalThis.CampusResidentGuard.inspect()});
      if(typeof r?.result?.busy!=='boolean' || typeof r.result.view!=='string' || typeof r.result.document_id!=='string')throw Error('invalid_snapshot');
      const hash=[...new Uint8Array(await crypto.subtle.digest('SHA-256',new TextEncoder().encode(r.result.view)))].map(b=>b.toString(16).padStart(2,'0')).join('');
      return {busy:r.result.busy,view:hash,document_id:r.result.document_id};
    } catch(e) {if(['invalid_snapshot'].includes(e.message))throw e;throw Error('permission_denied');}
  }
  bind(cfg,task,recipe,interval=1800) {
    const next=this.chain.then(()=>this.bindPage(cfg,task,recipe,interval));this.chain=next.catch(()=>{});return next;
  }
  async bindPage(cfg,task,recipe,interval) {
    const tab=await this.browser.tabs.get(task.tabId).catch(()=>{throw Error('tab_missing');});
    const url=stablePageUrl(task.url),origin=new URL(url).origin;
    if(stablePageUrl(tab.url)!==url)throw Error('route_mismatch');
    const meta=await this.reader.metadata(tab.id);
    if(meta.login)throw Error('need_login');
    const key=meta.account?.state==='known'?await this.accountKey(meta.source,meta.account.native):null;
    if(recipe.binding.account_key!=='unverified' && recipe.binding.account_key!=='public' && key!==recipe.binding.account_key)throw Error(key?'account_mismatch':'account_unknown');
    if(recipe.binding.account_key==='public' && key)throw Error('private_source_required');
    const rows=(await this.storage.get('residentSites')).residentSites || [];
    let site=rows.find(r=>r.owner===owner(cfg)&&r.origin===origin);
    if(site?.account && key && site.account!==key)throw Error('single_account_conflict');
    if(!site){site={owner:owner(cfg),origin,session_id:crypto.randomUUID(),account:key,pages:[]};rows.push(site);}
    if(!site.account && key)site.account=key;
    const view=JSON.stringify(Object.fromEntries(Object.entries(recipe.view || {}).filter(([k])=>k!=='projection').sort(([a],[b])=>a.localeCompare(b))));
    let page=site.pages.find(p=>p.url===url&&p.recipeView===view);
    if(page && page.tabId!==tab.id && page.epoch===await this.epoch()) {
      const old=await this.browser.tabs.get(page.tabId).catch(()=>null);
      if(old && stablePageUrl(old.url)===url && !task.rebind)throw Error('monitor_tab_exists');
    }
    if(!page){page={page_id:crypto.randomUUID(),url,recipeView:view};site.pages.push(page);}
    const guard=await this.inspect(tab.id);
    if(task.recoverPageId){
      if(page.page_id!==task.recoverPageId || page.epoch!==await this.epoch())throw Error('tab_rebind_required');
      if(guard.busy)throw Error('user_busy');
      if(guard.view!==page.view)throw Error('view_mismatch');
    }
    Object.assign(page,{tabId:tab.id,epoch:await this.epoch(),view:guard.view,rawUrl:tab.url});
    await this.storage.set({residentSites:rows});
    return residentDescriptor({version:1,session_id:site.session_id,page_id:page.page_id,refresh:'reload',interval_s:interval});
  }
  async adopt(cfg,recipe,interval=1800) {
    const matches=(await this.browser.tabs.query({})).filter(t=>{try{return stablePageUrl(t.url)===recipe.url;}catch{return false;}});
    if(matches.length!==1)throw Error(matches.length?'tab_ambiguous':'tab_missing');
    return this.bind(cfg,{tabId:matches[0].id,url:matches[0].url,rebind:true},recipe,interval);
  }
  async locate(cfg,recipe) {
    const r=residentDescriptor(recipe.resident),rows=(await this.storage.get('residentSites')).residentSites || [];
    const site=rows.find(s=>s.owner===owner(cfg)&&s.session_id===r.session_id&&s.origin===new URL(recipe.url).origin);
    const page=site?.pages.find(p=>p.page_id===r.page_id&&p.url===recipe.url);
    if(!page || page.epoch!==await this.epoch())throw Error('tab_rebind_required');
    let tab=await this.browser.tabs.get(page.tabId).catch(()=>null);
    const matches=t=>{try{return stablePageUrl(t.url)===page.url;}catch{return false;}};
    if(!tab || !matches(tab)) {
      // A labeled, unverified account is tied to its original tab.
      if(!site.account || recipe.binding.account_key!==site.account)throw Error(tab?'route_mismatch':'tab_missing');
      const candidates=(await this.browser.tabs.query({})).filter(matches);
      if(candidates.length!==1)throw Error(candidates.length?'tab_ambiguous':'waiting_page');
      tab=candidates[0];
      await this.bind(cfg,{tabId:tab.id,url:tab.url,recoverPageId:r.page_id},recipe,r.interval_s);
    }
    return {site,page,tab};
  }
  async verify(site,meta) {
    if(meta.login)throw Error('need_login');
    if(site.account) {
      if(meta.account?.state!=='known')throw Error('account_unknown');
      if(await this.accountKey(meta.source,meta.account.native)!==site.account)throw Error('account_mismatch');
    }
  }
}
