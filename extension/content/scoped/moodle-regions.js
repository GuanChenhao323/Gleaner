(() => {
  const R=globalThis.CampusScoped;
  /** Reads loaded events, never pagination, actions or activity detail requests. */
  class MoodleTimelineExtractor {
    date(item,region) {
      for(let p=item;p && p!==region.node;p=p.parentElement) {
        for(let previous=p.previousElementSibling;previous;previous=previous.previousElementSibling) {
          if(previous.matches('h3,h4,h5,h6,[data-region="event-list-date"]') && region.dom.visible(previous)) return previous;
        }
      }
      return null;
    }
    extract(page,catalog,intent,selected,{required=false}={}) {
      const regions=required?page.regions.require('timeline'):page.regions.find('timeline'),records=[],coverage=[];
      for(const region of regions) {
        const {node,dom,title}=region;
        const items=[...node.querySelectorAll('[data-region="event-list-item"]')].filter(n=>dom.visible(n));
        const loading=[...node.querySelectorAll('[aria-busy="true"],[data-region*="loading-placeholder"]')].some(n=>dom.visible(n));
        if(loading) {if(required) throw Error('page_not_ready');coverage.push({id:'timeline',title,status:'not_ready'});continue;}
        const empty=[...node.querySelectorAll('[data-region="empty-message"]')].some(n=>dom.visible(n));
        if(!items.length && !empty) {if(required) throw Error('unsupported_region');coverage.push({id:'timeline',title,status:'unsupported'});continue;}
        const before=records.length;
        for(const item of items) {
          const a=[...item.querySelectorAll('.event-name-container a[href]')].find(link=>dom.visible(link) && dom.url(link) && !dom.url(link).searchParams.has('action'));
          if(!a) {if(required) throw Error('unsupported_region');continue;}
          const url=dom.url(a);if(url.origin!==page.url.origin) continue;
          const owner=catalog.ownerOf(item),name=page.label(a,dom),course=owner?.title || page.label(item.querySelector('.event-name-container small'),dom);
          // A course name displayed next to an event is context, never native ownership.
          if(selected && owner?.id!==selected.id || !required && !selected && !dom.match(name,intent.keyword || intent.target) || intent.keyword && !dom.match(name,intent.keyword)) continue;
          const date=this.date(item,region),dateText=date?dom.label(date):'',time=page.label(item.querySelector('small.text-right,time'),dom),original=dom.content(item);
          if(!name) throw Error('unsupported_region');
          const evidence=dom.evidence(item,original);
          if(dateText) {evidence.locator+=` ; date: ${dom.locator(date)}`;evidence.text=dateText+'\n'+original;}
          // An activity URL identifies its detail page, not a distinct calendar
          // occurrence. Preserve separate loaded rows until a native event ID exists.
          records.push(dom.record(null,name,original,item,{url:url.href,record_type:'timeline_event',complete:false,preview_reason:'timeline_preview_only',fields:{course,date_text:dateText,datetime_text:time},evidence,presentation:{group:required?'timeline':'assignments',region:title,matched_by:required?'section_heading':selected?'course_identity':'activity_title',course_relation:owner?'native':'unconfirmed'}}));
        }
        coverage.push({id:'timeline',title,status:records.length>before?'matched':'no_match'});
      }
      return {records,coverage};
    }
  }

  /** Bounded contact information, intentionally not a task or a person entity. */
  class MoodleSupportExtractor {
    extract(page,intent) {
      const records=[],coverage=[];
      for(const region of page.regions.require('support')) {
        const {dom,node,title}=region,body=node.querySelector('.content') || node.querySelector('.card-text');
        if(!body || !dom.visible(body)) throw Error('unsupported_region');
        const names={email:'邮箱',phone:'电话',office:'办公室',role:'职务',department:'部门'},fields={};
        const requested=intent.fields.length?intent.fields:Object.keys(names);
        const mappings={email:/邮箱|电邮|email/,phone:/电话|phone/,office:/办公室|office/,role:/职称|职务/,department:/部门/};
        const labels=dom.labels(body,Object.fromEntries(requested.map(key=>[key,mappings[key]])));
        const mail=[...body.querySelectorAll('a[href^="mailto:"]')].find(a=>dom.visible(a));
        // A native email anchor needs no serialization of the other contact fields.
        if(requested.includes('email')) labels.email ||= mail?.getAttribute('href')?.slice(7).split('?')[0] || dom.label(body).match(/[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}/i)?.[0] || '';
        if(requested.includes('phone')) labels.phone ||= dom.label(body).match(/(?:\+\d{1,3}[ -]?)?\d{4}[ -]\d{4}/)?.[0] || '';
        if(requested.includes('office')) labels.office ||= dom.label(body).match(/(?:IT\s+)?Office\s+[A-Z]?\d+[A-Z]?/i)?.[0] || '';
        for(const key of requested) if(labels[key]) fields[key]=labels[key];
        const missing=intent.fields.filter(key=>!labels[key]);
        const text=intent.fields.length?intent.fields.filter(key=>labels[key]).map(key=>`${names[key]}：${labels[key]}`).join('\n') || '联系区块中未找到所需字段。':dom.content(body);
        records.push(dom.record(null,title,text,body,{record_type:'contact_info',complete:false,preview_reason:'contact_preview_only',fields,missing_fields:missing,evidence:dom.evidence(body,text),presentation:{group:'contacts',region:title,matched_by:intent.fields.length?'requested_fields':'section_heading',course_relation:'none'}}));
        coverage.push({id:'support',title,status:missing.length?'fields_missing':'matched'});
      }
      return {records,coverage};
    }
  }
  Object.assign(R,{MoodleTimelineExtractor,MoodleSupportExtractor});
})();
