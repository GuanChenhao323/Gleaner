import {projectPage,resolveTemplates} from '../templates/resolve.js';

export function bindIntentPanel(document,browser,client) {
  const el=name=>document.getElementById('intent-'+name);
  const dates={todo:'截止时间',event:'开始时间',notice:'发布时间'};
  let draft,owner,version=0;
  function reset() {
    version++;
    draft=null;
    el('form').hidden=true;
    el('status').textContent='';
  }
  el('kind').addEventListener('change',reset);
  el('preview').addEventListener('click',async()=>{
    reset();
    const current=version,purpose=el('kind').value;
    try {
      const cfg=await client.send({type:'config'});
      if(!cfg.uid)throw Error('请先登录工作台');
      const [tab]=await browser.tabs.query({active:true,currentWindow:true});
      const response=await fetch(browser.runtime.getURL('templates/catalog.json'));
      const rules=resolveTemplates(await response.json(),purpose,new URL(tab.url).hostname);
      const [entry]=await browser.scripting.executeScript({target:{tabId:tab.id,frameIds:[0]},func:projectPage,args:[rules,purpose]});
      if(current!==version)return;
      const page=entry.result;
      if(!page || new URL(page.url).origin!==new URL(tab.url).origin)throw Error('页面已变化，请重新读取');
      owner={uid:cfg.uid,server:cfg.server};
      draft={request_id:crypto.randomUUID(),purpose,url:page.url,activity:page.activity};
      el('title').value=page.title;
      el('text').value=page.text;
      el('url').textContent=page.url;
      el('date-row').hidden=!dates[purpose];
      el('date-label').textContent=dates[purpose] || '';
      el('original-date').textContent=dates[purpose] && page.date?'页面原文 '+page.date:'';
      el('date').value='';
      // Preserve local wall time only when the page supplies it unambiguously.
      if(/^\d{4}-\d\d-\d\dT\d\d:\d\d$/.test(page.date))el('date').value=page.date;
      else if(/^\d{4}-\d\d-\d\dT\d\d:\d\d(?::\d\d(?:\.\d+)?)?(?:Z|[+-]\d\d:\d\d)$/.test(page.date)) {
        const instant=new Date(page.date);
        if(Number.isFinite(+instant))el('date').value=new Date(+instant-instant.getTimezoneOffset()*60000).toISOString().slice(0,16);
      }
      el('publisher-row').hidden=purpose!=='notice';
      el('publisher').value=page.publisher;
      el('form').hidden=false;
    } catch(e) {if(current===version)el('status').textContent=e.message;}
  });
  el('save').addEventListener('click',async()=>{
    if(!draft || el('save').disabled)return;
    const current=version;
    el('save').disabled=true;
    try {
      const result=await client.send({type:'intent.save',owner,capture:{...draft,title:el('title').value,text:el('text').value,
        date:dates[draft.purpose] && el('date').value?new Date(el('date').value).getTime()/1000:null,
        publisher:draft.purpose==='notice'?el('publisher').value:''}});
      if(!Number.isInteger(result.item_id))throw Error('未收到保存回执');
      if(current===version){reset();el('status').textContent='已保存到收件箱';}
    } catch(e) {if(current===version)el('status').textContent=e.message;}
    finally {el('save').disabled=false;}
  });
}
