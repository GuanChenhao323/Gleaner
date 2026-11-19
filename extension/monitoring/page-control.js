/** A one-use ticket authorizes one local operation without forwarding the workbench token. */
export class PageControl {
  constructor({api,browser,device,reader,accountKey}) {
    Object.assign(this,{api,browser,device,reader,accountKey});
  }
  async run(cfg,{action,source_id,tabId}) {
    if(!['authorize','status','revoke','presence'].includes(action))throw Error('invalid_control');
    const server=new URL(cfg.server);
    if(!['localhost','127.0.0.1','[::1]'].includes(server.hostname))throw Error('local_service_required');
    const {sources}=await this.api(cfg,'/api/v1/reading-sources');
    const source=sources.find(s=>s.id===source_id);
    const {device}=await this.device();
    if(!source || source.device_id!==device || source.recipe.source!=='moodle')throw Error('source_missing');
    const params={source_id,action,device_id:device,revision:source.revision};
    let principal;
    if(action==='authorize') {
      const meta=await this.reader.metadata(tabId);
      if(meta.url!==source.recipe.url || meta.login || meta.account?.state!=='known')throw Error('account_unknown');
      principal=meta.account.native;
      if(await this.accountKey('moodle',principal)!==source.recipe.binding.account_key)throw Error('account_mismatch');
    }
    const local=async(values)=>{
      const ticket=await this.api(cfg,'/api/v1/page-control-ticket',{source_id,action:values.action});
      if(!Number.isInteger(ticket.port)||ticket.port<1||ticket.port>65535||!ticket.ticket)throw Error('invalid_response');
      if(values.action==='authorize'){
        const bytes=new TextEncoder().encode(ticket.epoch+'|'+source_id+'|moodle|'+principal);
        values.account_proof=[...new Uint8Array(await crypto.subtle.digest('SHA-256',bytes))].map(b=>b.toString(16).padStart(2,'0')).join('');
      }
      const res=await fetch('http://127.0.0.1:'+ticket.port+'/api/monitor/v2/session',{
        method:'POST',credentials:'omit',redirect:'error',cache:'no-store',signal:AbortSignal.timeout(10000),
        headers:{'Content-Type':'application/json','X-Gleaner-Page-Ticket':ticket.ticket},body:JSON.stringify({...values,epoch:ticket.epoch})});
      const data=await res.json();
      if(!res.ok||data.ok!==true)throw Error(data.error || 'local_service_unavailable');
      return data;
    };
    if(action==='revoke'){
      const state=await local({...params,action:'status'});
      if(state.state==='not_authorized')return state;
      params.auth_revision=state.auth_revision;
    }
    if(action==='presence')params.sequence=Date.now();
    return local(params);
  }
}
