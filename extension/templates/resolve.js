/** Packaged templates contain CSS selectors only. All ancestors must match. */
export function resolveTemplates(catalog, purpose, host) {
  const entries=new Map(catalog.map(template=>[template.id,template]));
  if(entries.size!==catalog.length)throw Error('模板编号重复');
  const matched=[];
  for(const entry of catalog) {
    const chain=[],seen=new Set();
    let current=entry;
    while(current) {
      if(seen.has(current.id))throw Error('模板继承形成循环');
      chain.unshift(current);
      seen.add(current.id);
      if(!current.extends)break;
      current=entries.get(current.extends);
      if(!current)throw Error('缺少父模板');
    }
    if(chain[0].id!==purpose || chain.some(t=>t.host && t.host!==host))continue;
    matched.push({
      depth:chain.length,
      matches:chain.map(t=>t.match).filter(Boolean),
      fields:Object.assign({},...chain.map(t=>t.overrides))
    });
  }
  return matched.sort((a,b)=>b.depth-a.depth);
}

// Injected into the current top frame. Keep the user's selection ahead of page defaults.
export function projectPage(templates,purpose) {
  const rule=templates.find(t=>t.matches.every(selector=>document.querySelector(selector)));
  if(!rule)throw Error('用途模板不存在');
  const node=key=>rule.fields[key]?document.querySelector(rule.fields[key]):null;
  const text=key=>node(key)?.innerText?.trim() || '';
  const date=node('date');
  const url=new URL(location.href);
  if(!['https:','http:'].includes(url.protocol)||url.username||url.password)throw Error('仅支持网页');
  if(url.hash && !/^#[/\w.-]+$/.test(url.hash))url.hash='';
  for(const key of [...url.searchParams.keys()]) {
    if(/token|ticket|session|password|secret|authorization|^(sid|auth|code|access_key|sesskey)$/i.test(key))url.searchParams.delete(key);
  }
  const selection=window.getSelection();
  const anchor=selection?.anchorNode?.parentElement?.closest('a[href]');
  const selectedUrl=anchor?new URL(anchor.href,url):null;
  const activityUrl=purpose==='todo' && (url.pathname==='/mod/assign/view.php'?url:selectedUrl);
  let activity=null;
  if(activityUrl && activityUrl.origin===url.origin && activityUrl.pathname==='/mod/assign/view.php' &&
     /^\d+$/.test(activityUrl.searchParams.get('id') || '') && !activityUrl.searchParams.has('action')) {
    const profile=document.querySelector('.usermenu a[href*="/user/profile.php"],.logininfo a[href*="/user/profile.php"]');
    const profileUrl=profile?new URL(profile.href,url):null;
    const accountNode=document.querySelector('body[data-account-id],body[data-userid],.usermenu[data-userid],.usermenu [data-userid]');
    const principal=accountNode?.getAttribute('data-account-id') || accountNode?.getAttribute('data-userid') ||
      (profileUrl?.origin===url.origin?profileUrl.searchParams.get('id'):null);
    if(/^\d+$/.test(principal || '')) {
      activity={id:activityUrl.searchParams.get('id'),principal,detail:activityUrl===url};
    }
  }
  return {
    activity,url:activity?url.origin+'/mod/assign/view.php?id='+activity.id:url.href,title:(activity && !activity.detail?anchor.innerText:text('title') || document.title || url.hostname).slice(0,300),
    text:(window.getSelection()?.toString().trim() || text('text')).slice(0,20000),
    date:date?.getAttribute('datetime') || date?.getAttribute('content') || date?.innerText?.trim() || '',
    publisher:text('publisher').slice(0,200)
  };
}
