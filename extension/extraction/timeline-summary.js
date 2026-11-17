import {normalize} from './intent.js';

/** Collection eligibility never invents an event ID or promotes summaries to details. */
export class TimelineSummaryPolicy {
  apply(candidates,intent,account,source,url) {
    if(source!=='moodle' || !/^(timeline|时间线)$/.test(normalize(intent.target)) || intent.kind!=='auto' || intent.fields.length || !candidates.length || !candidates.every(c=>c.record_type==='timeline_event'))return {candidates};
    const page=new URL(url);
    const supported=page.hostname==='moodle.must.edu.mo' && page.protocol==='https:' && page.pathname==='/my/' || ['localhost','127.0.0.1'].includes(page.hostname) && ['/my/','/capture/moodle-dashboard'].includes(page.pathname);
    if(!supported)return {candidates};
    const known=account.state==='known';
    return {save_mode:'timeline_summary',candidates:candidates.map(c=>({...c,
      save_allowed:known,save_reason:known?'':'account_unknown',target:null,entity_id:null,completeness:'summary'}))};
  }
}

/** A frozen group is one reference, not one assignment per timeline row. */
export class TimelineCapturePayload {
  text(candidates) {
    return candidates.map((c,i)=>`【活动摘要 ${i+1}】${c.raw.title}\n课程：${c.raw.fields?.course || ''}\n日期原文：${c.raw.fields?.date_text || ''}\n时间原文：${c.raw.fields?.datetime_text || ''}\n${c.raw.text}\n详情：${c.url}`).join('\n\n');
  }
  create(task) {
    const r=task.result;
    if(r?.save_mode!=='timeline_summary' || !r.binding || !r.candidates?.length || r.candidates.length>30 || r.candidates.some(c=>c.record_type!=='timeline_event' || !c.save_allowed))throw Error('preview_only');
    if(this.text(r.candidates).length>20000)throw Error('content_too_large');
    const fragments=r.candidates.map(c=>({candidate_id:c.candidate_id,title:c.raw.title,text:c.raw.text,url:c.url,
      fields:Object.fromEntries(['course','date_text','datetime_text'].map(k=>[k,c.raw.fields?.[k] || ''])),
      evidence:c.evidence[0],context:{frame_url:r.url,region:'Timeline',completeness:'summary'}}));
    return {schema_version:1,collection_type:'timeline_summary',request_id:task.id,
      source:{url:r.url,title:(r.title || 'Moodle Timeline').slice(0,300)},query:task.query,
      match_scope:'content',observed_at:r.observed_at,source_binding:r.binding,fragments};
  }
}
