import {t} from './i18n.js';
export function bindPageControl(document,browser,client) {
  const panel=document.getElementById('page-control-panel'),select=document.getElementById('protocol-source');
  const message=document.getElementById('protocol-message');
  const labels={account_confirmation_required:'本地服务已重启。请在原作业页确认同一账号。',not_authorized:'尚未授权',needs_credentials:'等待本地授权会话',unverified:'等待验证网站账号',valid:'网站会话有效',auth_required:'请在网站重新登录',revoked:'已撤销'};
  let sources=[];
  document.getElementById('protocol-open').addEventListener('click',async()=>{
    const row=sources.find(s=>s.id===Number(select.value));
    if(row && /^https:\/\/moodle\.must\.edu\.mo\/mod\/assign\/view\.php\?id=\d+$/.test(row.url))await browser.tabs.create({url:row.url});
  });
  panel.addEventListener('toggle',async()=>{
    if(!panel.open)return;
    try {
      const rows=await client.send({type:'page-control.sources'});
      sources=rows;
      select.replaceChildren(...rows.map(row=>new Option(row.query+' · '+row.url,row.id)));
      message.textContent=rows.length?t('页面关闭后，已授权的本地服务可检查作业。'):t('还没有已验证的 Moodle 作业来源。');
    } catch(e){message.textContent=e.message;}
  });
  for(const action of ['authorize','status','revoke']) {
    document.getElementById('protocol-'+action).addEventListener('click',async()=>{
      if(!select.value)return;
      try {
        if(!await browser.permissions.request({origins:['http://127.0.0.1/*']}))throw Error(t('未授权连接本地服务'));
        const [tab]=await browser.tabs.query({active:true,currentWindow:true});
        const state=await client.send({type:'page-control.run',source_id:Number(select.value),action,tabId:tab.id});
        message.textContent=state.next_allowed_at>Date.now()/1000 ? t`${t(labels[state.state] || state.state)} · 最早检查 ${new Date(state.next_allowed_at*1000).toLocaleString()}` : t(labels[state.state] || state.state);
      }catch(e){message.textContent=e.message;}
    });
  }
}
