import fs from 'node:fs';
import {parseHTML} from 'linkedom';
import {CaptureController} from '../ui/controller.js';
import {CaptureView} from '../ui/view.js';
import {CaptureFormStore} from '../ui/form-store.js';
import {storage} from './scoped-fixture.mjs';

export async function panelHarness(options = {}) {
  const store = storage(), forms = new CaptureFormStore(store), messages = [], tasks = new Map(), entries = new Map(), controllers = [];
  const ctx = {cfg: {server:'http://localhost:8080', uid:1, email:'demo@example.test'}, connectionError:null, entries, tasks, messages, onMessage:options.onMessage};
  let tab = {id:1, url:'https://unregistered.example.test/inbox#loaded', title:'合成收件箱'};
  const browser = {tabs:{query:async()=>[{id:1}], get:async()=>{if(!tab)throw Error('No tab');return {...tab};},create:async input=>messages.push({type:'tabs.create',...input})},permissions:{contains:async()=>true,request:async()=>true}};
  const client = {send:async m=>{
    messages.push(structuredClone(m));
    const custom = await ctx.onMessage?.(m,ctx);if(custom!==undefined)return custom;
    if(m.type==='config')return structuredClone(ctx.cfg);
    if(m.type==='connection.check'){if(ctx.connectionError)throw Error(ctx.connectionError);return {state:'connected',uid:ctx.cfg.uid,email:ctx.cfg.email};}
    if(m.type==='extract.start'){
      const task={id:m.request_id,owner:ctx.cfg.uid,schema_version:2,state:'succeeded',tabId:m.tabId,url:m.url,query:m.query,intent:{query:m.query,match_scope:m.match_scope},match_scope:m.match_scope,result:{source:'generic',url:m.url,title:'合成收件箱',observed_at:Date.now(),intent:{query:m.query,match_scope:m.match_scope},candidates:[1,2].map(i=>({candidate_id:'candidate-'+i,record_type:'web_fragment',url:m.url,raw:{title:`项目会议 ${i}`,text:'匹配的原文片段 '+i+'。'.repeat(300),fields:{}},evidence:[{locator:'div:nth-child('+i+')',text:'原文依据'}],save_allowed:true}))}};
      tasks.set(task.id,task);return {id:task.id};
    }
    if(m.type==='extract.get'){const task=tasks.get(m.id);if(!task || task.owner!==ctx.cfg.uid)throw Error('draft_not_found');return structuredClone(task);}
    if(m.type==='extract.save'){
      const task=tasks.get(m.id);task.save_binding=m.source_binding;task.submission={request_id:m.id};
      entries.set(m.id,{request_id:m.id,state:'confirmed',response:{results:[{candidate_id:'collection',capture_id:'fixture-collection',status:'new',item_id:41,source_id:42,fragment_count:2,version:1}]}});
      if(ctx.loseSaveReply){ctx.loseSaveReply=false;throw Error('worker_timeout');}
      return structuredClone(task.submission);
    }
    if(m.type==='extract.list')return {tasks:[...tasks.values()].filter(t=>t.owner===ctx.cfg.uid).map(({result,...t})=>structuredClone(t))};
    if(m.type==='status')return {entries:structuredClone([...entries.values()]),intents:[]};
    if(m.type==='retry'){const e=entries.get(m.request_id);e.state='confirmed';return {};}
    if(m.type==='login'){ctx.cfg={server:m.server,uid:ctx.cfg.uid || 1,email:m.email};ctx.connectionError=null;for(const e of entries.values())e.state='confirmed';return {};}
    if(m.type==='logout'){ctx.cfg={server:ctx.cfg.server};return {};}
    if(m.type==='extract.delete'){tasks.delete(m.id);return {};}
    throw Error('unexpected message: '+m.type);
  }};
  async function boot() {
    const {document}=parseHTML(fs.readFileSync(new URL('../popup.html',import.meta.url),'utf8'));
    const view=new CaptureView(document),controller=new CaptureController({browser,client,forms,view,location:{href:'chrome-extension://test/popup.html'}});
    controllers.push(controller);await controller.init();clearInterval(controller.timer);await new Promise(r=>setImmediate(r));
    return {document,view,controller};
  }
  const ui=await boot();
  return {...ui,ctx,forms,store,browser,client,messages,boot,setTab:value=>{tab=value;},dispose:()=>controllers.forEach(c=>c.dispose())};
}
export async function capture(h) {h.view.$('query').value='项目会议';h.view.$('query').oninput();await h.controller.capture();}
export async function declareSource(h) {h.view.select('source-kind','labeled');h.view.$('source-kind').onchange();h.view.$('source-label').value='学校邮箱';h.view.$('source-label').oninput();await h.controller.confirmBinding();}
