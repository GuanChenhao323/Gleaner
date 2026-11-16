const failures=new Set(['need_login','account_unknown','account_mismatch','route_mismatch','view_mismatch','permission_denied','render_timeout','selection_missing','no_match','unsupported','preview_only','worker_interrupted','private_source_required']);
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
        const path=`/api/v1/reading-jobs/${active.job.id}/result`;
        const rows=await this.outbox.all();
        if(!rows.some(r=>r.scope===owner(cfg)&&r.path===path))await this.outbox.add(cfg,path,{schema_version:1,device_id,lease:active.job.lease,revision:active.job.revision,status:'worker_interrupted'});
      }
      await this.storage.remove('readingActiveJob');
      await this.outbox.flush(cfg);
    }
    const {job}=await this.api(cfg,'/api/v1/reading-jobs/claim',{device_id});
    if(!job)return;
    await this.storage.set({readingActiveJob:{owner:owner(cfg),job}});
    let payload={schema_version:1,device_id,lease:job.lease,revision:job.revision};
    try {payload={...payload,status:'success',...await this.reader.read(job)};}
    catch(e){payload.status=failures.has(e.message)?e.message:'failed';}
    if(owner(await this.config())!==owner(cfg))return; // Resume only in the same owner namespace.
    await this.outbox.add(cfg,`/api/v1/reading-jobs/${job.id}/result`,payload);
    await this.storage.remove('readingActiveJob');
    await this.outbox.flush(cfg);
  }
}
