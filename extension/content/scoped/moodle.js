(() => {
  const R = globalThis.CampusScoped;
  class MoodleScopeAdapter {
    source = 'moodle';
    supports(meta) { return meta.source === this.source; }
    run(dom, meta, intent, choice) {
      if (!['auto','assignments'].includes(intent.kind) || intent.fields.length) throw Error('wrong_section');
      const here = new URL(meta.url), root = document.querySelector('#region-main,main,[role="main"]');
      if (!root) throw Error(meta.frames?'frame_unsupported':'page_not_ready');
      const courses = new Map();
      const add = (id, title, node) => { if (/^\d+$/.test(id || '') && title && !courses.has(id)) courses.set(id,{id,title,node}); };
      for (const a of document.querySelectorAll('a[href*="/course/view.php"]')) {
        const u = dom.url(a); if (!u || u.origin !== here.origin) continue;
        const breadcrumb=a.closest('.breadcrumb,nav[aria-label*="breadcrumb"]');
        if (here.pathname.endsWith('/mod/assign/view.php') && !breadcrumb) continue;
        if (root.contains(a) && dom.visible(a) || breadcrumb && dom.visible(a,true)) add(u.searchParams.get('id'),dom.label(a,true),a);
      }
      if (here.pathname.endsWith('/course/view.php')) {
        const id = here.searchParams.get('id'), title = dom.label(root.querySelector('[data-course-name],h1'));
        if (id && title) courses.set(id,{id,title,node:root});
      }
      let matching = [...courses.values()].filter(c=>dom.match(c.title,intent.target));
      if (intent.current && !intent.target) {
        matching = here.pathname.endsWith('/my/') ? [] : matching;
        if (matching.length !== 1) return {records:[],navigation:[],warnings:['当前页无法可靠确定唯一课程，请进入具体课程页或输入课程名。']};
      }
      if (matching.length > 1 && (intent.target || intent.current)) {
        if (!choice) return {state:'needs_choice',choices:matching.map(({id,title,node})=>({id,title,context:node.closest('[data-semester]')?.getAttribute('data-semester') || ''})),records:[],navigation:[],warnings:['发现同名或相近课程，请确认课程范围后继续。']};
        matching = matching.filter(c=>c.id===choice); if (matching.length!==1) throw Error('invalid_choice');
      } else if (choice && !matching.some(c=>c.id===choice)) throw Error('invalid_choice');
      const selected = intent.target || intent.current || choice ? matching[0]
        : here.pathname.endsWith('/course/view.php') ? courses.get(here.searchParams.get('id'))
        : here.pathname.endsWith('/mod/assign/view.php') && courses.size===1 ? [...courses.values()][0] : undefined;
      if (intent.target && !selected) return {records:[],navigation:[],warnings:['当前已加载页面没有匹配课程；没有扩大到其他课程。']};
      const belong = node => {
        if (!selected) return true;
        if (here.pathname.endsWith('/course/view.php')) return selected.id===here.searchParams.get('id');
        if (here.pathname.endsWith('/mod/assign/view.php')) return courses.size===1 && courses.has(selected.id);
        for (let p=node.parentElement;p && p!==root.parentElement;p=p.parentElement) {
          if (p.getAttribute('data-course-id')===selected.id) return true;
          if (p.matches('section,.coursebox,.course-card,[data-region="course-content"]')) {
            const ids=new Set([...p.querySelectorAll('a[href*="/course/view.php"]')].map(a=>dom.url(a)?.searchParams.get('id')).filter(Boolean));
            if (ids.size===1 && ids.has(selected.id)) return true;
          }
        }
        return false;
      };
      const records=[], seen=new Set();
      if (here.pathname.endsWith('/mod/assign/view.php') && /^\d+$/.test(here.searchParams.get('id')||'')) {
        if (intent.target && !selected) return {records:[],navigation:[],warnings:['无法确认此作业所属课程。']};
        const title=dom.label(root.querySelector('h1,h2')) || document.title;
        if (dom.match(title,intent.keyword)) {
          const node=root.querySelector('#intro.activity-description,.activity-description'); if(!node) throw Error('selection_missing');
          const fields={course:selected?.title || '',datetime_text:dom.label(root.querySelector('[data-region="activity-dates"],.activity-dates'))};
          records.push(dom.record(`assignment:${here.searchParams.get('id')}`,title,dom.content(node),node,{fields}));
        }
      } else for (const a of root.querySelectorAll('a[href]')) {
        if(!dom.visible(a)) continue;
        const u=dom.url(a), title=dom.label(a); if(!u || u.origin!==here.origin || !u.pathname.endsWith('/mod/assign/view.php') || !/^\d+$/.test(u.searchParams.get('id')||'')) continue;
        const id=u.searchParams.get('id'); if(seen.has(id) || !belong(a) || !dom.match(title,intent.keyword)) continue;
        seen.add(id);
        // Inline descriptions are read only after course membership has been proven.
        const item=a.closest(`[data-assignment-id="${id}"],.activity`);
        const description=item?.querySelector('.activity-description,[data-field="description"]');
        const complete=Boolean(description && dom.visible(description));
        records.push(dom.record(`assignment:${id}`,title,complete?dom.content(description):title,a,{url:u.href,complete,fields:{course:selected?.title || ''}}));
      }
      return {records,navigation:!records.length && selected?[{title:selected.title,url:selected.node.matches('a')?selected.node.href:meta.url}]:[],warnings:[
        '只处理当前页已加载且归属已确认的作业；不会进入其他课程或自动打开详情。',
        ...(records.some(r=>!r.complete)?['部分条目只有作业入口，请进入详情或展开正文后重新抓取。']:[]),
        ...(!records.length && selected?['已定位课程，但当前页面没有可读取的匹配作业；请进入课程页面。']:[]),
      ]};
    }
  }
  R.adapters.push(new MoodleScopeAdapter());
})();
