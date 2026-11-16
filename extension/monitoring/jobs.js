const failures=new Set(['need_login','account_unknown','account_mismatch','route_mismatch','view_mismatch','permission_denied','render_timeout','selection_missing','no_match','unsupported','preview_only','worker_interrupted','private_source_required','tab_missing','tab_rebind_required','tab_ambiguous','user_busy','single_account_conflict']);
const owner=cfg=>`${cfg.server}|${cfg.uid}`;

/** Owns one persisted intent/receipt, never an independent periodic schedule. */
export class ReadingJobExecutor {
  constructor({storage,api,outbox,reader,reentry,config,device}) {Object.assign(this,{storage,api,outbox,reader,reentry,config,device});}
  async wake(cfg) {
    if(!cfg.token || !cfg.uid)return;
    await this.reentry.cleanup();
    const device_id=(await this.device()).device;
    await this.api(cfg,'/api/v1/reading-devices/heartbeat',{device_id});
    await this.outbox.flush(cfg);
    const active=(await this.storage.get('readingActiveJob')).readingActiveJob;
    if(active) {
      if(active.owner===owner(cfg)) {
        for(const job of active.jobs || [active.job]) {
          const path=`/api/v1/reading-jobs/${job.id}/result`;
          const rows=await this.outbox.all();
          if(!rows.some(r=>r.scope===owner(cfg)&&r.path===path))await this.outbox.add(cfg,path,{schema_version:1,device_id,lease:job.lease,revision:job.revision,status:'worker_interrupted'});
        }
      }
      await this.storage.remove('readingActiveJob');
      await this.outbox.flush(cfg);
    }
    const {job}=await this.api(cfg,'/api/v1/reading-jobs/claim',{device_id});
    if(!job)return;
    const jobs=[job,...job.companions || []];
    await this.storage.set({readingActiveJob:{owner:owner(cfg),jobs}});
    let prepareError;
    try {await this.reader.begin?.(job);}catch(e){prepareError=e;}
    try {
      for(const item of jobs) {
        let payload={schema_version:1,device_id,lease:item.lease,revision:item.revision};
        try {if(prepareError)throw prepareError;payload={...payload,status:'success',...await this.reader.read(item)};}
        catch(e){payload.status=failures.has(e.message)?e.message:'failed';}
        if(owner(await this.config())!==owner(cfg))return;
        await this.outbox.add(cfg,`/api/v1/reading-jobs/${item.id}/result`,payload);
      }
    } finally {this.reader.end?.();}
    await this.storage.remove('readingActiveJob');
    await this.outbox.flush(cfg);
  }
}
