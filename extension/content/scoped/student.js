(() => {
  const R=globalThis.CampusScoped;
  class InformationScopeAdapter {
    source='student';
    supports(meta) { return meta.source==='student' && !/timetable/.test(new URL(meta.url).hostname+new URL(meta.url).pathname+new URL(meta.url).hash); }
    run(dom,meta,intent) {
      if(!['auto','notices','news'].includes(intent.kind) || intent.fields.length) throw Error('wrong_section');
      const here=new URL(meta.url), records=[], seen=new Set(), term=intent.target, keyword=intent.keyword;
      const matches=title=>dom.match(title,term) && dom.match(title,keyword);
      if(here.pathname==='/detail' && /^\d+$/.test(here.searchParams.get('id')||'')) {
        const roots=[...document.querySelectorAll('article,main,[role="main"]')].filter(n=>dom.visible(n));
        const root=roots.find(n=>n.matches('article')) || roots[0];
        const title=dom.label(root?.querySelector('h1,h2,h3'));
        if(!root || !title) throw Error('unsupported_dom');
        if(matches(title)) {
          const text=dom.content(root).split('\n').filter(t=>!/^(瀏覽|浏览|閱讀|阅读|點讚|点赞|收藏|返回|分享|打印|列印)(量|次數|次数|數|数)?\s*[:：]?\s*[\d,]*$/.test(t)).join('\n');
          records.push(dom.record(`notice:${here.searchParams.get('id')}`,title,text,root,{fields:dom.labels(root,{department:/发布单位|部门/,published_text:/发布时间|发布日期/,valid_until_text:/有效期|有效至/})}));
        }
      } else {
        for(const a of document.querySelectorAll('a[href]')) {
          if(!dom.visible(a)) continue;
          const u=dom.url(a); if(!u || !(u.hostname==='infoportal-web.must.edu.mo' || meta.fixture && u.origin===here.origin) || u.pathname!=='/detail' || !/^\d+$/.test(u.searchParams.get('id')||'')) continue;
          const category=u.searchParams.get('category') || '';
          if(intent.kind==='notices' && !/(^|\.)notice$/.test(category) || intent.kind==='news' && /(^|\.)notice$/.test(category)) continue;
          if(a.closest('[data-calendar],.calendar,[aria-label="我的日程"]')) continue;
          const title=dom.label(a) || a.querySelector('img')?.getAttribute('alt') || '', id=u.searchParams.get('id');
          if(seen.has(id) || !matches(title)) continue;
          seen.add(id); records.push(dom.record(`notice:${id}`,title,title,a,{url:u.href,complete:false}));
        }
        if(meta.fixture==='student') for(const node of document.querySelectorAll('[data-notice-id]')) {
          if(!dom.visible(node)) continue;
          const title=dom.label(node.querySelector('h1,h2,h3')), id=node.getAttribute('data-notice-id');
          if(!id || seen.has(id) || !matches(title)) continue;
          seen.add(id); records.push(dom.record(`notice:${id}`,title,dom.content(node),node));
        }
      }
      return {records,navigation:[],warnings:['关键词匹配当前已加载的标题；未自动读取其他详情或下一页。',...(records.some(r=>!r.complete)?['当前匹配是列表摘要／入口，完整正文未加载，不能保存为完整事项。']:[])]};
    }
  }
  class TimetableScopeAdapter {
    source='student';
    supports(meta) { return meta.source==='student' && /timetable/.test(new URL(meta.url).hostname+new URL(meta.url).pathname+new URL(meta.url).hash); }
    run(dom,meta,intent) {
      if(!['auto','timetable'].includes(intent.kind) || intent.fields.length) throw Error('wrong_section');
      const range=/\b\d{1,2}:\d{2}\s*[-–—~～至]\s*\d{1,2}:\d{2}\b/, roots=new Set(), records=[];
      for(const node of document.querySelectorAll('[data-schedule-id],.fc-event,.vuecal__event,div,li')) {
        if(!dom.visible(node) || node.textContent.length>2000 || !range.test(node.textContent) && !node.hasAttribute('data-schedule-id')) continue;
        if([...node.children].some(c=>range.test(c.textContent))) continue;
        let root=node.closest('[data-schedule-id],.fc-event,.vuecal__event') || node;
        if(!root.matches('[data-schedule-id],.fc-event,.vuecal__event')) for(let i=0;i<3 && root.parentElement && root.parentElement!==document.body;i++) {
          const p=root.parentElement; if(p.textContent.length>1500 || (p.textContent.match(new RegExp(range.source,'g'))||[]).length!==1) break; root=p;
        }
        roots.add(root);
      }
      let semester='';
      const term=[...document.querySelectorAll('[data-semester],select[name="semester"]')].find(n=>dom.visible(n));
      if(term) semester=term.getAttribute('data-semester') || term.value || '';
      for(const label of document.querySelectorAll('label')) if(/^(学期|學期)[:：]?\s*$/.test(label.textContent.trim())) {
        const n=label.htmlFor?document.getElementById(label.htmlFor):label.parentElement?.querySelector('select,[role="combobox"],input:not([type="password"]):not([type="hidden"])');
        if(n) semester=n.value || n.getAttribute('aria-valuetext') || dom.label(n);
      }
      const headers=[...document.querySelectorAll('[data-date],th,[role="columnheader"],div,span,time')].filter(n=>dom.visible(n) && (n.hasAttribute('data-date') || n.textContent.length<70 && /^\s*(?:\d{4}年)?\d{1,2}月\d{1,2}日\s*(?:星期|週|周)[一二三四五六日天]/.test(n.textContent)));
      for(const node of roots) {
        const title=dom.label(node.querySelector('[data-field="course"],h2,h3,.fc-title,.vuecal__event-title')) || dom.label(node.firstElementChild) || dom.label(node);
        if(!dom.match(title,intent.target) || !dom.match(title,intent.keyword)) continue;
        const text=dom.content(node), fields={subtype:'timetable',course:title,semester,datetime_text:text.match(range)?.[0]||'',...dom.labels(node,{week:/周次/,weekday:/星期/,period:/节次/})};
        const rect=node.getBoundingClientRect?.(), ownDate=node.closest('[data-date]')?.getAttribute('data-date');
        const header=rect && headers.find(h=>{const r=h.getBoundingClientRect?.();return r && r.width>0 && r.left<=rect.left+rect.width/2 && r.right>=rect.left+rect.width/2;});
        fields.date_text=ownDate || (header && (header.getAttribute('data-date') || dom.label(header))) || '';
        const id=meta.fixture && node.getAttribute('data-schedule-id');
        records.push(dom.record(id?`timetable:${id}`:null,title,text,node,{fields,missing_fields:[...['semester','week','date_text'].filter(k=>!fields[k]),...(!id?['native_occurrence_id']:[])]}));
      }
      return {records,navigation:[],warnings:['仅当前课表视图；不翻周、不推测缺失日期。正式课次身份未核实，保持仅预览。']};
    }
  }
  R.adapters.push(new InformationScopeAdapter(),new TimetableScopeAdapter());
})();
