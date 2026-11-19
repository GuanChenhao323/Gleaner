(() => {
  const R=globalThis.CampusScoped;
  /** Separate the native activity name from icon labels and course context. */
  class MoodleActivityProjection {
    read(page,a,catalog,dom=page.dom) {
      const recent=a.closest('.block_recentlyaccesseditems');
      const info=recent?a.querySelector('.course-info-container'):null;
      const primary=info?info.querySelector('h6,h5,[data-region="activity-name"]'):a.querySelector('.activityname,[data-region="activity-name"]') || a;
      if(!primary) throw Error('unsupported_region');
      const context=info?.querySelector('.small,small');
      const title=page.label(primary,dom);
      const owner=catalog.ownerOf(a);
      return {title,owner,course:owner?.title || page.label(context,dom),region:recent?'Recently accessed items':'当前课程内容'};
    }
  }
  function matchesAssignment(dom,title,term) {
    const lab=/^lab\s*[-_]?\s*(\d+)$/i.exec(term || '');
    return lab ? new RegExp('\\blab[\\s_-]*0*'+lab[1].replace(/^0+(?=\d)/,'')+'(?!\\d)','i').test(title) : dom.match(title,term);
  }

  function assignmentUrl(url) {
    const canonical=new URL(url);
    canonical.searchParams.delete('forceview');
    canonical.hash='';
    return canonical.href;
  }

  function assignmentDetail(page,title,course) {
    const {dom,root}=page;
    const heading=root.querySelector('h1,h2');
    const intro=root.querySelector('#intro.activity-description,.activity-description,#intro');
    const body=intro && dom.label(intro)?dom.content(intro):'';
    const fields={course,subtype:'moodle_assignment'};
    const dates=root.querySelector('[data-region="activity-dates"],.activity-dates');
    const lines=[];
    for(const node of dates?.querySelectorAll('strong,b') || []) {
      const label=dom.label(node).replace(/[:：]\s*$/,'').trim();
      if(!/^(due(?: date)?|截止(?:时间|時間|日期)?)$/i.test(label)) continue;
      const row=dom.label(node.parentElement);
      const value=row.slice(dom.label(node).length).replace(/^\s*[:：]?\s*/,'');
      if(value) fields.due_text=value;
    }
    for(const row of root.querySelectorAll('table tr')) {
      const [key,value]=row.children;
      if(!key || !value || !key.matches('th,[scope="row"]')) continue;
      const name=dom.label(key).replace(/[:：]$/,'').trim();
      const field=({'submission status':'submission_status','grading status':'grading_status','time remaining':'time_remaining','due date':'due_text','提交状态':'submission_status','提交狀態':'submission_status','评分状态':'grading_status','評分狀態':'grading_status','剩余时间':'time_remaining','剩餘時間':'time_remaining','截止日期':'due_text'})[name.toLowerCase()];
      if(field && !fields[field] && dom.label(value)) fields[field]=dom.label(value);
    }
    if(fields.due_text) lines.push('Due: '+fields.due_text);
    for(const [field,label] of [['submission_status','提交状态'],['grading_status','评分状态'],['time_remaining','剩余时间']]) {
      if(fields[field]) lines.push(label+'：'+fields[field]);
    }
    if(body) lines.push(body);
    const links=[...root.querySelectorAll('a[href]')].filter(a=>{
      const url=dom.url(a);
      return dom.visible(a) && url?.origin===page.url.origin && url.pathname.includes('/mod_assign/introattachment/');
    });
    for(const a of links) lines.push('附件（未读取正文）：'+dom.label(a)+'\n'+dom.url(a).href);
    if(!lines.length) {
      fields.subtype='assignment_link';
      lines.push(title);
    }
    return dom.record('assignment:'+page.activityId,title,lines.join('\n'),heading || intro || root,{url:assignmentUrl(page.url),record_type:'assignment',complete:fields.subtype!=='assignment_link',fields});
  }

  class MoodleAssignmentExtractor {
    constructor(projection=new MoodleActivityProjection()) {this.projection=projection;}
    extract(page,catalog,intent,selected) {
      const {dom}=page,records=[],seen=new Set();
      const titleTerm=selected?intent.keyword:intent.keyword || (intent.kind==='assignments'?'':intent.target);
      if (page.activityId) {
        if ((intent.current || intent.kind==='assignments' && intent.target) && !selected) return records;
        const title=dom.label(page.root.querySelector('h2') || page.root.querySelector('h1')) || page.meta.title;
        if (!matchesAssignment(dom,title,titleTerm)) return records;
        const record=assignmentDetail(page,title,selected?.title || '');
        record.presentation={group:'assignments',region:'作业详情',matched_by:selected?'course_identity':'activity_title',course_relation:selected?'native':'unconfirmed'};
        records.push(record);
        return records;
      }
      for (const a of page.root.querySelectorAll('a[href]')) {
        if(a.closest('.block_timeline,[data-block="timeline"]')) continue;
        const u=page.assignmentLink(a);if (!u) continue;
        const id=u.searchParams.get('id'),{title,owner,course,region}=this.projection.read(page,a,catalog);
        if (seen.has(id) || selected && owner?.id!==selected.id || intent.kind==='assignments' && intent.target && !selected || !matchesAssignment(dom,title,titleTerm)) continue;
        const item=a.closest(`[data-assignment-id="${id}"],.activity`);
        const description=item?.querySelector('.activity-description,[data-field="description"]');
        const complete=Boolean(description && dom.visible(description));
        if(!title) throw Error('unsupported_region');
        seen.add(id);const text=complete?dom.content(description):title;
        records.push(dom.record(`assignment:${id}`,title,text,a,{url:assignmentUrl(u),complete,record_type:'assignment',fields:complete?{course}:{course,subtype:'assignment_link'},evidence:dom.evidence(a,complete?text:dom.label(a)),presentation:{group:'assignments',region,matched_by:selected?'course_identity':'activity_title',course_relation:owner?'native':'unconfirmed'}}));
      }
      return records;
    }
  }
  class MoodleCoursePreviewExtractor {
    extract(page,course) {
      const {dom}=page,node=course.node;
      // Activity records are shown separately; keep their bodies out of the course overview.
      const exclude=[...node.querySelectorAll('.activity,[data-assignment-id],.sr-only,.accesshide')];
      const text=page.root.contains(node) && dom.visible(node)?dom.content(node,{exclude}):course.title;
      return dom.record(`course:${course.id}`,course.title,text,node,{url:course.url,record_type:'course_entry',complete:false,preview_reason:'navigation_only',fields:{course:course.title},presentation:{group:'courses',region:'课程概览',matched_by:'course_identity',course_relation:'native'}});
    }
  }
  class MoodleSectionExtractor {
    extract(page,intent,selected) {
      const term=intent.keyword || intent.target;
      if (!term) return [];
      const currentCourse=selected && page.courseId===selected.id && !intent.keyword;
      const matches=page.sections().filter(s=>!s.node.matches('.block_timeline,[data-block="timeline"]') && (currentCourse || page.dom.match(s.title,term)));
      // Prefer the deepest explicit matching block; never serialize an enclosing whole page.
      return matches.filter(s=>!matches.some(other=>other!==s && s.node.contains(other.node))).map(s=>page.dom.record(null,s.title,page.dom.content(s.node),s.node,{record_type:'page_section',complete:false,preview_reason:'section_preview_only',fields:{subtype:'page_section'},presentation:{group:'sections',region:s.title,matched_by:'section_heading',course_relation:currentCourse?'native':'none'}}));
    }
  }
  Object.assign(R,{matchesAssignment,MoodleActivityProjection,MoodleAssignmentExtractor,MoodleCoursePreviewExtractor,MoodleSectionExtractor});
})();
