(() => {
  const R=globalThis.CampusScoped;
  const BLOCKS='section.block,section[id],article[data-section],[data-region="block"]';
  const CARDS='[data-course-id],.dashboard-card,.coursebox,.course-card,.list-group-item,[data-region="course-content"]';

  /** Only recognized semantic blocks may cross the main-content boundary. */
  class MoodleRegionIndex {
    constructor(page) {
      this.page=page;this.regions=[];
      const side=document.querySelector('aside#block-region-side-pre[data-blockregion="side-pre"]');
      const nodes=[...page.root.querySelectorAll('section.block')];
      if(side) nodes.push(...side.querySelectorAll('section.block'));
      for(const node of new Set(nodes)) {
        const dom=page.root.contains(node)?page.dom:page.pageDom.within(node,[side]);
        if(!dom.visible(node)) continue;
        const title=dom.label(node.querySelector('h1,h2,h3,h4,h5,h6,[role="heading"]'));
        const id=node.matches('.block_timeline,[data-block="timeline"]')?'timeline':node.matches('.block_html,[data-block="html"]') && R.normalize(title)==='moodle support'?'support':'';
        if(id) this.regions.push({id,node,dom,title});
      }
    }
    find(id) {return this.regions.filter(r=>r.id===id);}
    target(intent) {
      const term=R.normalize(intent.target || intent.keyword);
      return /^(timeline|时间线)$/.test(term)?'timeline':/^(moodle support|moodle支持)$/.test(term)?'support':'';
    }
    require(id) {
      const regions=this.find(id);if(!regions.length) throw Error('unsupported_region');
      for(const r of regions) if([...r.node.querySelectorAll('[aria-busy="true"],[data-region*="loading-placeholder"]')].some(n=>r.dom.visible(n))) throw Error('page_not_ready');
      return regions;
    }
  }

  /** Discovers bounded page structure, never serializes course/activity bodies. */
  class MoodlePageModel {
    constructor(pageDom,meta) {
      this.meta=meta;this.url=new URL(meta.url);this.pageDom=pageDom;
      if (!meta.fixture && !/^\/(my\/?|course\/view\.php|mod\/assign\/view\.php)$/.test(this.url.pathname)) throw Error('unsupported');
      this.root=document.querySelector('#region-main') || document.querySelector('main,[role="main"]');
      if (!this.root) throw Error(meta.frames?'frame_unsupported':'unsupported_dom');
      this.dom=pageDom.within(this.root,[...this.root.querySelectorAll('aside#block-region-content[data-blockregion="content"]')],
        [...this.root.querySelectorAll('.block_myoverview .block-myoverview[data-region="myoverview"][role="navigation"]')]);
      this.courseRoute=this.url.pathname.endsWith('/course/view.php');
      this.assignmentRoute=this.url.pathname.endsWith('/mod/assign/view.php');
      this.courseId=this.courseRoute && /^\d+$/.test(this.url.searchParams.get('id') || '')?this.url.searchParams.get('id'):'';
      this.activityId=this.assignmentRoute && /^\d+$/.test(this.url.searchParams.get('id') || '')?this.url.searchParams.get('id'):'';
      this.pageType=this.courseRoute?'moodle_course':this.assignmentRoute?'moodle_assignment':'moodle_dashboard';
      this.regions=new MoodleRegionIndex(this);
    }
    label(node,dom=this.dom) {return node?dom.label(node,false,{exclude:[...node.querySelectorAll('.sr-only,.accesshide,.icon,img')]}):'';}
    courseLinks(root=this.root) {
      return [...root.querySelectorAll('a[href*="/course/view.php"]')].map(a=>({a,u:this.pageDom.url(a)})).filter(({u})=>u && u.origin===this.url.origin && /^\d+$/.test(u.searchParams.get('id') || ''));
    }
    card(anchor,id) {
      const candidates=[];
      for (let p=anchor.parentElement;p && p!==this.root;p=p.parentElement) if (p.matches(CARDS) && this.dom.visible(p)) {
        const ids=new Set(this.courseLinks(p).map(({u})=>u.searchParams.get('id')));
        if (ids.size===1 && ids.has(id)) candidates.push(p);
      }
      return candidates.find(n=>n.matches('[data-course-id],.dashboard-card,.coursebox,.course-card,.list-group-item')) || candidates[0] || anchor;
    }
    sections() {
      return [...this.root.querySelectorAll(BLOCKS)].filter(n=>this.dom.visible(n) && !n.matches('[data-course-id],.coursebox,.course-card,.dashboard-card')).map(node=>{
        const heading=node.querySelector('h1,h2,h3,h4,h5,h6,[role="heading"]');
        if (!heading || heading.closest(BLOCKS+',.activity,'+CARDS)!==node) return null;
        const title=this.dom.label(heading);
        return title?{node,title}:null;
      }).filter(Boolean);
    }
    recognized(catalog) {
      if(catalog.blockedOverview) throw Error('unsupported_dom');
      const busy=[...this.root.querySelectorAll('[aria-busy="true"],[data-region="loading-placeholder"]')].some(n=>this.dom.visible(n));
      if (!catalog.courses.size && busy) throw Error('page_not_ready');
      if (catalog.courses.size || this.regions.regions.length || this.activityId && this.dom.label(this.root.querySelector('h1,h2'))) return true;
      if (this.dom.visible(this.root.querySelector('.block_myoverview,.block_timeline,[data-region="myoverview"]')) || this.sections().length) return true;
      return [...this.root.querySelectorAll('a[href]')].some(a=>this.assignmentLink(a));
    }
    assignmentLink(a,dom=this.dom) {
      const u=dom.url(a);
      return dom.visible(a) && u?.origin===this.url.origin && u.pathname.endsWith('/mod/assign/view.php') && /^\d+$/.test(u.searchParams.get('id') || '') && !u.searchParams.has('action')?u:null;
    }
  }

  class MoodleCourseCatalog {
    constructor(page) {
      this.page=page;this.courses=new Map();this.stats={native_links:0,excluded_boundary:0,excluded_visibility:0,empty_titles:0};
      for (const {a,u} of page.courseLinks(document)) {
        this.stats.native_links++;
        const breadcrumb=a.closest('.breadcrumb,nav[aria-label*="breadcrumb"]');
        if (page.assignmentRoute && !breadcrumb) continue;
        const allowed=breadcrumb?page.pageDom.visible(a,true):page.dom.visible(a);
        if(!allowed) {
          if(!page.dom.visibility.allows(a))this.stats.excluded_visibility++;
          else {
            this.stats.excluded_boundary++;
            if(a.matches('.coursename') && a.closest('.block_myoverview') && !a.closest('nav,header,footer,form'))this.blockedOverview=true;
          }
        }
        const title=breadcrumb?(a.getAttribute('title')?.trim() || page.pageDom.label(a,true)):page.label(a);
        const id=u.searchParams.get('id');
        if(allowed && !title)this.stats.empty_titles++;
        if (allowed && title && !this.courses.has(id)) this.courses.set(id,{id,title,url:u.href,node:page.card(a,id)});
      }
      if (page.courseId) {
        const title=page.dom.label(page.root.querySelector('[data-course-name],h1'));
        if (title) this.courses.set(page.courseId,{id:page.courseId,title,url:page.url.href,node:page.root.querySelector('[data-course-name],h1')});
      }
      this.stats.indexed_courses=this.courses.size;
    }
    ownerOf(node) {
      const {page}=this;
      if (page.courseId) return this.courses.get(page.courseId);
      if (page.assignmentRoute) return this.courses.size===1?[...this.courses.values()][0]:null;
      for (let p=node;p && p!==page.root && p!==document.body;p=p.parentElement) {
        const explicit=p.getAttribute('data-course-id');
        if (explicit && this.courses.has(explicit)) return this.courses.get(explicit);
        if (p.matches(CARDS) && !p.matches('[data-region="event-list-container"]')) {
          const ids=new Set(page.courseLinks(p).map(({u})=>u.searchParams.get('id')));
          if (ids.size===1) return this.courses.get([...ids][0]);
        }
      }
      return null;
    }
  }

  class CourseScopeResolver {
    resolve(page,catalog,intent,choice) {
      let matching=[...catalog.courses.values()].filter(c=>page.dom.match(c.title,intent.target));
      // Only visible bilingual aliases give an exact-name priority. Partial names
      // and multiple class sections still require native course scope confirmation.
      const exact=matching.filter(c=>{
        const title=R.normalize(c.title),target=R.normalize(intent.target);
        const prefix=title.split('(')[0].trim();
        const aliases=/[a-z]/.test(prefix)?[...title.matchAll(/\(([^()]*[\u3400-\u9fff][^()]*)\)/g)].map(m=>m[1]):[];
        if(aliases.length) aliases.push(prefix);
        return target && aliases.includes(target);
      });
      if(exact.length) matching=exact;
      if (intent.current && !intent.target) matching=page.courseId?[catalog.courses.get(page.courseId)].filter(Boolean):page.assignmentRoute && catalog.courses.size===1?[...catalog.courses.values()]:[];
      if (choice && !matching.some(c=>c.id===choice)) throw Error('invalid_choice');
      if (matching.length>1 && (intent.target || intent.current) && !choice) return {choices:matching.map(c=>({id:c.id,title:c.title,context:c.node.closest('[data-semester]')?.getAttribute('data-semester') || ''}))};
      const selected=choice?matching.find(c=>c.id===choice):intent.target || intent.current?matching[0]:page.courseId?catalog.courses.get(page.courseId):page.assignmentRoute && catalog.courses.size===1?[...catalog.courses.values()][0]:null;
      return {selected,choices:[],currentUnknown:intent.current && !selected};
    }
  }
  Object.assign(R,{MoodleRegionIndex,MoodlePageModel,MoodleCourseCatalog,CourseScopeResolver});
})();
