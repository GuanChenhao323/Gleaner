(() => {
  const R=globalThis.CampusScoped;
  R.metadata=()=>new R.DomAccess().metadata();
  R.execute=({intent,choice}={})=>{
    if(intent?.version!==2 || typeof intent.query!=='string' || !intent.query.trim() || !Array.isArray(intent.fields)) throw Error('invalid_intent');
    const dom=new R.DomAccess(), meta=dom.metadata();
    if(meta.login) throw Error('need_login');
    if(!meta.source) throw Error('unsupported');
    if(meta.ready==='loading' || [...document.querySelectorAll('#app,#root,main,[aria-busy="true"]')].some(n=>dom.visible(n) && (n.getAttribute('aria-busy')==='true' || !n.firstElementChild && /^(loading|正在加载|載入中)[.…\s]*$/i.test([...n.childNodes].filter(c=>c.nodeType===3).map(c=>c.textContent.slice(0,80)).join('').trim())))) throw Error('page_not_ready');
    const adapter=R.adapters.find(a=>a.supports(meta)); if(!adapter) throw Error('unsupported_dom');
    const found=adapter.run(dom,meta,intent,choice);
    if(found.records.length>100) throw Error('candidate_limit');
    return {...meta,...found,channel:'dom',intent,observed_at:Date.now(),coverage:{scope:'current_rendered_view',match_basis:meta.source==='moodle'?'course_identity_and_activity_title':meta.source==='fie'?'person_name_and_requested_fields':'loaded_titles_or_course_blocks',count:found.records.length},
      // Diagnostic count contains no non-matching content or locators.
      extraction:{body_reads:dom.contentReads.length}};
  };
})();
