(() => {
  const R=globalThis.CampusScoped;
  class MoodleAssignmentExtractor {
    extract(page,catalog,intent,selected) {
      const {dom}=page,records=[],seen=new Set();
      const titleTerm=selected?intent.keyword:intent.keyword || (intent.kind==='assignments'?'':intent.target);
      if (page.activityId) {
        if ((intent.current || intent.kind==='assignments' && intent.target) && !selected) return records;
        const title=dom.label(page.root.querySelector('h1,h2')) || page.meta.title;
        if (!dom.match(title,titleTerm)) return records;
        const node=page.root.querySelector('#intro.activity-description,.activity-description');
        if (!node) {
          const links=[...page.root.querySelectorAll('a[href]')].filter(a=>dom.visible(a) && dom.url(a)?.pathname.includes('/mod_assign/introattachment/'));
          if (!links.length) throw Error('selection_missing');
          const text=links.map(a=>`${dom.label(a)}\n${dom.url(a).href}`).join('\n');
          records.push(dom.record(`assignment:${page.activityId}`,title,text,links[0],{record_type:'assignment',complete:false,preview_reason:'attachments_only',fields:{course:selected?.title || ''}}));
          return records;
        }
        records.push(dom.record(`assignment:${page.activityId}`,title,dom.content(node),node,{record_type:'assignment',fields:{course:selected?.title || '',datetime_text:dom.label(page.root.querySelector('[data-region="activity-dates"],.activity-dates'))}}));
        return records;
      }
      for (const a of page.root.querySelectorAll('a[href]')) {
        const u=page.assignmentLink(a);if (!u) continue;
        const id=u.searchParams.get('id'),title=dom.label(a),owner=catalog.ownerOf(a);
        if (seen.has(id) || selected && owner?.id!==selected.id || intent.kind==='assignments' && intent.target && !selected || !dom.match(title,titleTerm)) continue;
        const item=a.closest(`[data-assignment-id="${id}"],.activity`);
        const description=item?.querySelector('.activity-description,[data-field="description"]');
        const complete=Boolean(description && dom.visible(description));
        seen.add(id);records.push(dom.record(`assignment:${id}`,title,complete?dom.content(description):title,a,{url:u.href,complete,record_type:'assignment',fields:{course:owner?.title || ''}}));
      }
      return records;
    }
  }
  class MoodleCoursePreviewExtractor {
    extract(page,course) {
      const {dom}=page,node=course.node;
      // Activity records are shown separately; keep their bodies out of the course overview.
      const exclude=[...node.querySelectorAll('.activity,[data-assignment-id]')];
      const text=page.root.contains(node) && dom.visible(node)?dom.content(node,{exclude}):course.title;
      return dom.record(`course:${course.id}`,course.title,text,node,{url:course.url,record_type:'course_entry',complete:false,preview_reason:'navigation_only',fields:{course:course.title}});
    }
  }
  class MoodleSectionExtractor {
    extract(page,intent,selected) {
      const term=intent.keyword || intent.target;
      if (!term) return [];
      const currentCourse=selected && page.courseId===selected.id && !intent.keyword;
      const matches=page.sections().filter(s=>currentCourse || page.dom.match(s.title,term));
      // Prefer the deepest explicit matching block; never serialize an enclosing whole page.
      return matches.filter(s=>!matches.some(other=>other!==s && s.node.contains(other.node))).map(s=>page.dom.record(null,s.title,page.dom.content(s.node),s.node,{record_type:'page_section',complete:false,preview_reason:'section_preview_only',fields:{subtype:'page_section'}}));
    }
  }
  Object.assign(R,{MoodleAssignmentExtractor,MoodleCoursePreviewExtractor,MoodleSectionExtractor});
})();
