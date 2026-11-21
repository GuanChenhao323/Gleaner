/** Persist consent and the local host's epoch, without retaining site credentials. */
export class PageRecovery {
  constructor(storage,control) {this.storage=storage;this.control=control;this.chain=Promise.resolve();this.pending=new Map();}
  key(cfg){return 'page-grants:'+cfg.server+'|'+cfg.uid;}
  async grants(cfg){const key=this.key(cfg);return (await this.storage.get(key))[key] || {};}
  serialize(fn) {
    const result=this.chain.then(fn,fn);
    this.chain=result.catch(()=>{});
    return result;
  }
  remember(cfg,id,result) {return this.serialize(()=>this.saveGrant(cfg,id,result));}
  async saveGrant(cfg,id,result) {
    const grants=await this.grants(cfg);
    if(result.state==='revoked' || result.state==='not_authorized')delete grants[id];
    else grants[id]={epoch:result.epoch,state:result.state,sequence:grants[id]?.sequence || 0};
    await this.storage.set({[this.key(cfg)]:grants});
  }
  wake(cfg) {
    const key=this.key(cfg);
    if(!this.pending.has(key))this.pending.set(key,this.serialize(()=>this.renew(cfg)).finally(()=>this.pending.delete(key)));
    return this.pending.get(key);
  }
  stop(cfg) {
    return this.serialize(async()=>{
      const grants=await this.grants(cfg);
      for(const [id,grant] of Object.entries(grants)) {
        try {
          await this.control.run(cfg,{source_id:Number(id),action:'revoke'});
          delete grants[id];
        } catch(e) {if(e.message==='source_missing')delete grants[id];else grant.pending_revoke=true;}
      }
      await this.storage.set({[this.key(cfg)]:grants});
      if(Object.keys(grants).length)throw Error('page_revoke_pending');
    });
  }
  async renew(cfg) {
    if(!cfg.token || !cfg.uid)return;
    const grants=await this.grants(cfg);
    if(!Object.keys(grants).length)return;
    for(const [id,grant] of Object.entries(grants)) {
      // Reserve before sending: worker interruption cannot reuse an old presence sequence.
      grant.sequence=Math.max(Date.now(),grant.sequence+1);
      await this.storage.set({[this.key(cfg)]:grants});
      try {
        const result=await this.control.run(cfg,{action:grant.pending_revoke?'revoke':'presence',source_id:Number(id),sequence:grant.sequence});
        if(['revoked','not_authorized'].includes(result.state))delete grants[id];
        else {
          grant.state=result.state;
          grant.epoch=result.epoch;
          grant.next_allowed_at=result.next_allowed_at;
        }
      } catch(e) {
        if(e.message==='source_missing')delete grants[id];
        else grant.state=e.message==='unauthorized'?'login_required':'local_service_unavailable';
      }
    }
    await this.storage.set({[this.key(cfg)]:grants});
  }
}
