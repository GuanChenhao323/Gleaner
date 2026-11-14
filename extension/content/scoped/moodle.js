(() => {
  const R=globalThis.CampusScoped;
  /** Adapter composes source-specific policies/extractors through one stable run port. */
  class MoodleScopeAdapter {
    source='moodle';
    constructor({resolver=new R.CourseScopeResolver(),assignments=new R.MoodleAssignmentExtractor(),courses=new R.MoodleCoursePreviewExtractor(),sections=new R.MoodleSectionExtractor()}={}) {
      Object.assign(this,{resolver,assignments,courses,sections});
    }
    supports(meta) { return meta.source===this.source; }
    run(dom,meta,intent,choice) {
      if (!['auto','assignments'].includes(intent.kind) || intent.fields.length) throw Error('wrong_section');
      const page=new R.MoodlePageModel(dom,meta),catalog=new R.MoodleCourseCatalog(page);
      if (!page.recognized(catalog)) throw Error('unsupported_dom');
      const scope=this.resolver.resolve(page,catalog,intent,choice),records=[],navigation=[];
      const outcome=status=>({status,page_type:page.pageType});
      if (scope.choices.length) return {records,navigation,choices:scope.choices,state:'needs_choice',outcome:outcome('needs_choice'),warnings:['发现同名或相近课程，请确认课程范围后继续；尚未提取正文。']};
      if (scope.currentUnknown) return {records,navigation,outcome:outcome('no_match'),warnings:['当前页无法可靠确定唯一课程，请进入具体课程页或输入课程名。']};
      const selected=scope.selected;
      if (intent.kind==='auto' && selected && !intent.keyword && !page.assignmentRoute) records.push(this.courses.extract(page,selected));
      records.push(...this.assignments.extract(page,catalog,intent,selected));
      if (intent.kind==='auto' && !page.assignmentRoute) records.push(...this.sections.extract(page,intent,selected));
      if (selected && !records.length) navigation.push({title:selected.title,url:selected.url});
      return {records,navigation,outcome:outcome(records.length?'matched':navigation.length?'navigation_required':'no_match'),warnings:[
        '仅当前页已加载内容；未自动进入课程、打开详情、展开控件或翻页。',
        ...(navigation.length?['已识别目标课程，但当前页没有可读取的匹配正文，请打开课程／活动详情后重试。']:[]),
        ...(!records.length && !navigation.length?['页面结构已识别，当前已加载的标题或课程范围内没有匹配内容。']:[]),
      ]};
    }
  }
  R.adapters.push(new MoodleScopeAdapter());
})();
