const scope=cfg=>`${cfg.server}|${cfg.uid}`;
const captures=new Set(['/api/v1/captures','/api/v1/web-captures','/api/v1/timeline-captures']);
/** Account-wide epoch cleanup never exports cookies or keeps erased source identities. */
export class CaptureContextSync {
  constructor({storage,repository,api}) {Object.assign(this,{storage,repository,api});this.chain=Promise.resolve();}
  sync(cfg,{offline=false}={}) {
    const next=this.chain.then(()=>this.update(cfg,offline));this.chain=next.catch(()=>{});return next;
  }
  async update(cfg,offline) {
    const owner=scope(cfg),contexts=(await this.storage.get('captureContexts')).captureContexts || {};
    let context;
    try {context=await this.api(cfg,'/api/v1/capture-context');}
    catch(e){if(offline && ['backend_unavailable','backend_timeout','unauthorized'].includes(e.code || e.message))return contexts[owner] ?? 0;throw e;}
    const generation=context.generation;
    if(generation<(contexts[owner] ?? 0))throw Error('capture_context_changed');
    if(generation>(contexts[owner] ?? 0)) {
      await this.repository.mutate(rows=>{for(let i=rows.length-1;i>=0;i--)if(rows[i].owner===owner && (rows[i].capture_generation || 0)<generation)rows.splice(i,1);});
      const all=await this.storage.get(null);
      const keys=Object.keys(all).filter(k=>k.startsWith(`captureForm.v2:${owner}|`) || k.startsWith(`captureHistoryForm.v1:${owner}|`));
      if(keys.length)await this.storage.remove(keys);
      const reading=new Map(context.reading_sources.map(r=>[r.id,r.revision])),monitors=new Map(context.monitors.map(r=>[r.id,r.revision]));
      const validResult=row=>{
        if(row.context?.reading_source_id)return reading.has(row.context.reading_source_id) && (row.state==='confirmed' || reading.get(row.context.reading_source_id)===row.body?.revision);
        if(row.context?.monitor_id)return monitors.has(row.context.monitor_id) && (row.state==='confirmed' || monitors.get(row.context.monitor_id)===row.body?.revision);
        return false; // Old clients did not retain enough metadata to prove an in-flight result is current.
      };
      const outbox=(all.outbox || []).filter(row=>row.scope!==owner || (captures.has(row.path)?(row.body?.capture_generation || 0)>=generation:row.path.endsWith('/result')?validResult(row):true));
      const intents=(all.intents || []).filter(row=>row.scope!==owner || (row.capture_generation || 0)>=generation);
      const pages=new Set(context.resident_pages);
      const sites=(all.residentSites || []).map(s=>s.owner===owner?{...s,pages:s.pages.filter(p=>pages.has(p.page_id))}:s).filter(s=>s.owner!==owner || s.pages.length);
      await this.storage.set({outbox,intents,residentSites:sites});
      if(all.readingActiveJob?.owner===owner) {
        const active=all.readingActiveJob,jobs=(active.jobs || [active.job]).filter(j=>reading.get(j.source_id)===j.revision);
        if(jobs.length)await this.storage.set({readingActiveJob:{...active,jobs}});else await this.storage.remove('readingActiveJob');
      }
      if(all.activeJob?.scope===owner && monitors.get(all.activeJob.job.monitor_id)!==all.activeJob.job.revision)await this.storage.remove('activeJob');
    }
    contexts[owner]=generation;await this.storage.set({captureContexts:contexts});return generation;
  }
}
