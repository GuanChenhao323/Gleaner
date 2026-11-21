(() => {
  const R=globalThis.CampusScoped;
  class PeopleScopeAdapter {
    source='fie';
    supports(meta) { return meta.source===this.source; }
    run(dom,meta,intent) {
      if(!['auto','people'].includes(intent.kind)) throw Error('wrong_section');
      const here=new URL(meta.url), id=here.pathname.match(/\/person\/view\/id-(\d+)\.html$/)?.[1], records=[];
      if(!id) {
        const seen=new Set();
        for(const a of document.querySelectorAll('a[href]')) {
          if(!dom.visible(a)) continue;
          const u=dom.url(a), native=u?.origin===here.origin && u.pathname.match(/\/person\/view\/id-(\d+)\.html$/)?.[1],title=dom.label(a);
          if(!native || seen.has(native) || !dom.match(title,intent.target) || !dom.match(title,intent.keyword) || intent.current) continue;
          seen.add(native); records.push(dom.record(`person:${native}`,title,title,a,{url:u.href,complete:false,fields:{subtype:'teacher_profile'}}));
        }
        return {records,navigation:[],warnings:['当前是人员目录，仅匹配本站详情入口。请进入目标人员详情后读取字段；不自动访问外链。']};
      }
      const intro=document.querySelector('.personnel-introduction .intro-detail');
      const fallback=meta.fixture?document.querySelector('[data-person-id],main article,article'):null;
      const root=intro || fallback;
      const title=dom.label(root?.querySelector('.name-position-box .name,h1,h2,h3'));
      if(!root || !title) throw Error('unsupported_dom');
      if(!dom.match(title,intent.target) || !dom.match(title,intent.keyword)) return {records,navigation:[],warnings:['当前人员姓名与条件不匹配。']};
      const labels=dom.labels(root,{email:/邮箱|电邮|email/,office:/办公室|office/,phone:/电话|phone/,role:/职称|职务/,department:/部门/});
      const position=root.querySelector('.name-position-box .position'); if(position) labels.role=dom.label(position);
      if(intent.fields.length) {
        // Inspect only the selected person's contact area. Never serialize the CV.
        const contact=root.querySelector('.other-intro') || root;
        if(intent.fields.includes('email') && !labels.email) {
          const mail=contact.querySelector('a[href^="mailto:"]');
          labels.email=(mail?.getAttribute('href')?.slice(7).split('?')[0] || dom.label(contact).match(/[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}/i)?.[0] || '');
        }
        const names={email:'邮箱',office:'办公室',phone:'电话',role:'职务',department:'部门'};
        const missing=intent.fields.filter(k=>!labels[k]), fields={subtype:'teacher_profile'};
        for(const key of intent.fields) if(labels[key]) fields[key]=labels[key];
        const text=intent.fields.filter(k=>labels[k]).map(k=>`${names[k]}：${labels[k]}`).join('\n') || '当前人员主体中未找到所需字段。';
        records.push(dom.record(`person:${id}`,title,text,root,{fields,complete:!missing.length,missing_fields:missing,view:{projection:intent.fields.join(',')}}));
      } else {
        const parts=intro?[intro,document.querySelector('main .resume-detail.wm-editor')].filter(Boolean):[root];
        const text=parts.map(n=>dom.content(n)).join('\n');
        records.push(dom.record(`person:${id}`,title,text,root,{fields:{subtype:'teacher_profile',...labels},view:{projection:'profile'}}));
      }
      return {records,navigation:[],warnings:intent.fields.length?['只提取指定的人员字段及必要身份，不采集履历或通用页脚。']:['只读取当前人员主体，排除导航与通用页脚。']};
    }
  }
  R.adapters.push(new PeopleScopeAdapter());
})();
