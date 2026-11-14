import {errorText} from './view.js';

/** Workflow coordinates injected browser, API, storage and view ports. */
export class CaptureController {
  constructor({browser,client,forms,view,location,clock=Date.now}) {
    Object.assign(this,{browser,client,forms,view,location,clock});
    this.cfg={};this.form=null;this.task=null;this.generation=0;this.refreshing=false;this.saving=false;
  }
  guard(action) {return async()=>{try {await action();} catch(e) {this.view.status(errorText(e.message),true);if(e.message==='backend_login_required')this.view.$('connection').open=true;}};}
  async init() {
    this.view.ready(false);
    this.bind();
    this.cfg=await this.client.send({type:'config'});this.view.config(this.cfg);
    const args=new URL(this.location.href).searchParams;
    let tabId=Number(args.get('tab'));
    if(!tabId) tabId=(await this.browser.tabs.query({active:true,currentWindow:true}))[0]?.id;
    if(!tabId) throw Error('page_read_failed');
    let tab;try {tab=await this.browser.tabs.get(tabId);} catch {tab={id:tabId};}
    const stored=await this.forms.load(this.cfg,tabId);
    this.form=stored && (!tab.url || stored.url===tab.url)?stored:{tabId,url:tab.url || '',query:'',taskId:null,phase:'editing'};
    this.tab=tab;this.view.page(tab);this.view.$('query').value=this.form.query;
    this.view.ready(true);
    this.timer=setInterval(()=>{if(this.task && (['queued','running'].includes(this.task.state) || this.receiptPending))this.guard(()=>this.refresh())();},1200);
    if(this.form.phase==='prepared' && this.cfg.uid && await this.browser.permissions.contains({origins:[new URL(this.form.url).origin+'/*']})) await this.dispatch();
    else try {await this.refresh();} catch(e) {
      if(e.message!=='draft_not_found')throw e;
      this.form={...this.form,taskId:null,phase:'editing'};await this.forms.write(this.cfg,this.form);
      this.view.status('上次预览已过期或已删除，条件保留，请重新抓取。');
    }
  }
  bind() {
    const $=id=>this.view.$(id);
    $('query').oninput=()=>{if(!this.form)return;this.generation++;this.form={...this.form,query:$('query').value,taskId:null,phase:'editing'};this.task=null;this.view.clear();this.view.$('results').replaceChildren();this.forms.write(this.cfg,this.form).catch(()=>{});this.view.status('条件已修改，点击抓取生成新预览。');};
    // Called directly in the click handler to retain Chrome's permission user gesture.
    $('capture').onclick=this.guard(()=>this.capture());
    $('save').onclick=this.guard(()=>this.save());
    $('refresh').onclick=this.guard(()=>this.refresh(true));
    $('drafts').onclick=this.guard(()=>this.history());
    $('retry').onclick=this.guard(async()=>{await this.client.send({type:'retry'});await this.refresh(true);});
    $('allow').onclick=this.guard(async()=>{const origin=new URL($('server').value).origin;if(!await this.browser.permissions.request({origins:[origin+'/*']}))throw Error('permission_denied');this.view.status('连接权限已允许，请登录 Campus Radar。');});
    $('login').onclick=this.guard(async()=>{
      try {await this.client.send({type:'login',server:$('server').value,email:$('email').value.trim(),password:$('password').value});}
      finally {$('password').value='';}
      this.cfg=await this.client.send({type:'config'});this.view.config(this.cfg);this.form={...this.form,taskId:null,phase:'editing'};this.task=null;await this.forms.write(this.cfg,this.form);this.view.clear();this.view.status('已连接。学校登录请在原站完成。');
    });
    $('logout').onclick=this.guard(async()=>{await this.client.send({type:'logout'});this.cfg=await this.client.send({type:'config'});this.form={...this.form,query:'',taskId:null,phase:'editing'};this.task=null;this.view.$('query').value='';this.view.clear();this.view.$('results').replaceChildren();this.view.config(this.cfg);});
    $('workbench').onclick=this.guard(()=>this.browser.tabs.create({url:(this.cfg.server || 'http://localhost:8080')+'/#/sources'}));
    $('large').onclick=this.guard(()=>this.browser.tabs.create({url:this.browser.runtime.getURL('workspace.html')+`?tab=${this.form.tabId}`}));
  }
  capture(choice) {
    if(!this.form) throw Error('worker_unavailable');
    const query=this.view.$('query').value.trim();
    if(!query) throw Error('query_required');
    if(query.length>200) throw Error('query_too_long');
    if(!this.cfg.uid) throw Error('backend_login_required');
    if(!/^https?:/.test(this.form.url)) throw Error('unsupported');
    this.generation++;this.task=null;this.view.clear();this.view.$('results').replaceChildren();
    this.form={...this.form,query,choice,taskId:crypto.randomUUID(),phase:'prepared'};
    const generation=this.generation, form={...this.form};
    const persisted=this.forms.write(this.cfg,form);
    const permitted=this.browser.permissions.request({origins:[new URL(this.form.url).origin+'/*']});
    this.view.status('正在确认范围并抓取匹配内容…');
    return Promise.all([persisted,permitted]).then(async([,allowed])=>{if(generation!==this.generation)return;if(!allowed)throw Error('permission_denied');await this.dispatch(form,generation);});
  }
  async dispatch(form={...this.form},generation=this.generation) {
    await this.client.send({type:'extract.start',version:2,request_id:form.taskId,tabId:form.tabId,url:form.url,query:form.query,...(form.choice?{choice:form.choice}:{})});
    if(generation!==this.generation)return;
    this.form.phase='reading';await this.forms.write(this.cfg,this.form);await this.refresh();
  }
  async refresh(receipt=false) {
    if(this.refreshing || !this.form || !this.cfg.uid)return;
    this.refreshing=true;const generation=this.generation;
    try {
      const cfg=await this.client.send({type:'config'});
      if(cfg.uid!==this.cfg.uid || cfg.server!==this.cfg.server) {this.cfg=cfg;this.task=null;this.form={...this.form,query:'',taskId:null,phase:'editing'};this.view.$('query').value='';this.view.clear();this.view.$('results').replaceChildren();this.view.config(cfg);throw Error('backend_account_changed');}
      if(!this.form.taskId)return;
      const task=await this.client.send({type:'extract.get',id:this.form.taskId});
      if(generation!==this.generation)return;
      this.task=task;this.view.task(task,{stale:task.query!==this.view.$('query').value.trim(),saving:this.saving,onChoice:id=>this.guard(()=>this.capture(id))()});
      if(task.state==='succeeded') {
        const r=task.result;const outcome=r.outcome?.status || (r.candidates.length?'matched':r.navigation?.length?'navigation_required':'no_match');
        this.view.status(outcome==='navigation_required'?'已定位课程，需打开详情才能读取所需内容。':outcome==='no_match'?'页面结构已识别，当前条件没有匹配内容。':`已按条件读取 ${r.candidates.length} 条，请核对预览及完整度。`);
      }
      if(task.state==='needs_choice')this.view.status('请确认课程范围，再继续抓取。');
      if(['failed','interrupted'].includes(task.state))this.view.status(errorText(task.error || 'page_read_failed'),true);
      if(task.submission || receipt) {
        const data=await this.client.send({type:'status'});
        if(generation!==this.generation)return;
        const requestId=task.submission?.request_id || task.id;
        const entry=data.entries.find(e=>e.response?.request_id===requestId || e.request_id===requestId || e.body?.request_id===requestId);
        const intent=data.intents?.find(e=>e.id===requestId);
        this.receiptPending=Boolean(task.submission && (!entry || entry.state==='pending') && intent?.state!=='failed');
        this.view.receipt(entry,this.cfg);
        if(!entry && intent?.state==='failed')this.view.status(errorText(intent.error),true);
      }
    } finally {this.refreshing=false;}
  }
  async history() {
    const {tasks}=await this.client.send({type:'extract.list'}), root=this.view.$('history');root.replaceChildren();
    for(const t of tasks) {
      const row=this.view.node('p',`${t.query || '旧版预览'} · ${t.state} `);
      if(t.schema_version===2)row.append(this.view.button('查看预览',this.guard(async()=>{this.generation++;this.form={tabId:t.tabId,url:t.url,query:t.query,taskId:t.id,phase:'reading'};this.view.$('query').value=t.query;this.view.page({url:t.url});await this.forms.write(this.cfg,this.form);await this.refresh(true);})));
      row.append(this.view.button('删除预览',this.guard(async()=>{await this.client.send({type:'extract.delete',id:t.id});if(this.form.taskId===t.id){this.form.taskId=null;this.task=null;this.view.clear();await this.forms.write(this.cfg,this.form);}await this.history();})));
      root.append(row);
    }
    if(!tasks.length)root.append(this.view.node('p','没有本地预览记录。'));
  }
  async save() {
    if(this.saving || !this.task)return;
    const task=this.task,query=this.view.$('query').value.trim(),generation=this.generation;
    if(query!==task.query)throw Error('query_changed');
    try {const tab=await this.browser.tabs.get(this.form.tabId);if(tab.url!==this.form.url)throw Error('route_mismatch');}catch(e){if(e.message==='route_mismatch')throw e; /* closed original tab: frozen preview remains valid */}
    if(generation!==this.generation)return;
    this.saving=true;this.view.$('save').disabled=true;
    try {
      const result=await this.client.send({type:'extract.save',id:task.id,query});
      if(generation!==this.generation)return;
      this.task={...task,submission:result};this.view.status('已进入持久提交队列，正在查询后端确认。');
      await this.refresh(true);
    } finally {this.saving=false;}
  }
  dispose() {clearInterval(this.timer);}
}
