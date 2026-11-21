// Generic DOM port. No page fetch, private API, input values or AX access.
(() => {
  const R=globalThis.CampusScoped;
  const parent=n=>n.parentElement || n.getRootNode?.().host || null;
  const ROW='tr,li,[role="row"],[role="listitem"]';
  const BLOCK='p,h1,h2,h3,h4,h5,h6,pre,blockquote,dt,dd,div,article,section,td,th';
  const TITLE='h1,h2,h3,h4,h5,h6,a,[role="heading"]';

  /** Eligibility is independent of school navigation boundaries. */
  class FragmentVisibility {
    constructor() {this.cache=new WeakMap();}
    allows(node) {
      if(this.cache.has(node))return this.cache.get(node);
      let allowed=true;
      for(let n=node;n;n=parent(n)) {
        if(n.matches('script,style,noscript,template,input,textarea,select,option,button,[hidden],[aria-hidden="true"],[inert]') || n.hasAttribute('contenteditable') && n.getAttribute('contenteditable')!=='false' || n.isContentEditable) {allowed=false;break;}
        const style=globalThis.getComputedStyle?getComputedStyle(n):n.style;
        if(style && (style.display==='none' || ['hidden','collapse'].includes(style.visibility))) {allowed=false;break;}
      }
      this.cache.set(node,allowed);return allowed;
    }
  }

  /** Projects only visible text, retaining separators and open-shadow evidence. */
  class FragmentText {
    constructor(visibility) {this.visibility=visibility;this.visited=0;this.scanned=0;this.openShadows=0;}
    walk(node,visit,depth=0) {
      if(++this.visited>150000 || depth>160) throw Error('page_too_large');
      if(node.nodeType===3) {
        this.scanned+=node.textContent.length;if(this.scanned>3000000)throw Error('page_too_large');
        visit(node);return;
      }
      if(node.nodeType!==1 || !this.visibility.allows(node))return;
      if(node.shadowRoot) {
        this.openShadows++;
        for(const child of node.shadowRoot.childNodes)this.walk(child,visit,depth+1);
      } else if(node.localName==='slot' && node.assignedNodes?.().length) {
        for(const child of node.assignedNodes({flatten:true}))this.walk(child,visit,depth+1);
      } else for(const child of node.childNodes)this.walk(child,visit,depth+1);
    }
    read(node,depth=0) {
      if(depth>160)throw Error('page_too_large');
      if(node.nodeType===3)return node.textContent;
      if(node.nodeType!==1 || !this.visibility.allows(node))return '';
      const children=node.shadowRoot?.childNodes || (node.localName==='slot' && node.assignedNodes?.().length?node.assignedNodes({flatten:true}):node.childNodes);
      return [...children].map(n=>this.read(n,depth+1)).join('')+(/^(p|div|h[1-6]|li|dt|dd|tr|td|th|br|article|section)$/.test(node.localName)?'\n':'');
    }
    clean(node) {return this.read(node).split('\n').map(s=>s.replace(/\s+/g,' ').trim()).filter(Boolean).join('\n');}
  }

  /** Rows remain coherent even when subjects contain several nested text nodes. */
  class FragmentBoundary {
    choose(node) {
      let fallback=null;
      for(let n=node;n && n!==document.body;n=parent(n)) {
        if(n.matches(ROW))return n;
        if(!fallback && n.matches(BLOCK))fallback=n;
      }
      return fallback || node;
    }
    kind(node) {return node.nodeType!==1?'text':node.matches('tr,[role="row"]')?'table_row':node.matches('li,[role="listitem"]')?'list_row':node.matches('p,blockquote,pre,dt,dd')?'paragraph':node.matches('div,article,section')?'section':'text';}
    locator(node) {
      const parts=[];
      if(node.nodeType===3) {parts.unshift(`::text(${[...node.parentNode.childNodes].indexOf(node)})`);node=node.parentElement;}
      for(let n=node;n && parts.length<24;n=parent(n)) {
        const root=n.getRootNode?.();
        parts.unshift(`${n.localName}:nth-child(${[...n.parentNode?.children || []].indexOf(n)+1})`);
        if(!n.parentElement && root?.host)parts.unshift('::shadow');
      }
      return parts.join(' > ');
    }
  }

  class GenericFragmentExtractor {
    constructor({visibility=new FragmentVisibility(),boundary=new FragmentBoundary()}={}) {
      this.visibility=visibility;this.boundary=boundary;this.text=new FragmentText(visibility);
    }
    run(dom,meta,intent) {
      const scope=intent.match_scope || 'content';
      if(!['content','title'].includes(scope))throw Error('invalid_intent');
      const blocks=new Map(),query=R.normalize(intent.query);
      this.text.walk(document.body,node=>{
        const element=node.parentElement || node.getRootNode?.().host;if(!element || !node.textContent.trim())return;
        let block=this.boundary.choose(element);
        // A bare text node must never authorize serializing body/main or a
        // mixed container's unrelated child blocks as one matching fragment.
        if(block.matches('body,html,main') || !block.matches(ROW) && [...block.children].some(c=>c.matches(BLOCK+','+ROW)))block=node;
        if(scope==='title') {
          let title=null;
          for(let n=element;n;n=parent(n)) {if(n.matches(TITLE)){title=n;break;}if(n===block || n===document.body)break;}
          if(!title || !R.normalize(this.text.clean(title)).includes(query))return;
        }
        if(!blocks.has(block))blocks.set(block,null);
      });
      const records=[];let total=0;
      for(const node of blocks.keys()) {
        const text=this.text.clean(node);
        if(!R.normalize(text).includes(query))continue;
        if(text.length>20000 || (total+=text.length)>500000)throw Error('content_too_large');
        if(records.length>=100)throw Error('candidate_limit');
        const titleNode=node.nodeType===1?(node.matches(TITLE)?node:[...node.querySelectorAll(TITLE)].find(n=>this.visibility.allows(n))):null;
        const title=(titleNode?this.text.clean(titleNode):text.split('\n')[0]).slice(0,200) || meta.title || '网页片段';
        records.push({entity_id:null,record_type:'web_fragment',title,text,url:meta.url,fields:{},complete:false,
          evidence:{channel:'dom',locator:this.boundary.locator(node),text},
          context:{frame_url:meta.url,boundary:this.boundary.kind(node),completeness:'fragment',matched_by:'literal'}});
      }
      if(!blocks.size && !document.body?.children.length)throw Error('page_not_ready');
      return {records,coverage:{scope:'current_rendered_view',match_scope:scope,open_shadow_roots:this.text.openShadows,frames_excluded:meta.frames || 0},
        warnings:['仅提取当前已加载的匹配片段，不代表完整文章或邮件；未打开详情。','不读取嵌入页面、关闭的 Shadow DOM、图片或画布；网站账号未自动确认。'],
        outcome:{status:records.length?'matched':'no_match',page_type:'generic'}};
    }
  }
  Object.assign(R,{FragmentVisibility,FragmentText,FragmentBoundary,GenericFragmentExtractor});
  R.adapters.push({supports:meta=>meta.source==='generic',run:(dom,meta,intent)=>new GenericFragmentExtractor().run(dom,meta,intent)});
})();
