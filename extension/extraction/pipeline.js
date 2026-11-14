import {SiteRegistry, safeUrl} from './sites.js';
import {CandidateFactory, uniqueCandidates} from './candidates.js';
import {FragmentPipeline} from './fragments.js';

/** Validate the scoped-reader port and normalize it into the existing save contract. */
export class ExtractionPipeline {
  constructor(sites=new SiteRegistry()) { this.sites=sites; }
  extract(snapshot,intent) {
    const site=this.sites.resolve(snapshot.url,snapshot.fixture);
    if(snapshot.login) throw Error('need_login');
    if(site.source==='generic')return new FragmentPipeline().extract(snapshot,intent);
    if(!Array.isArray(snapshot.records) || snapshot.intent?.query!==intent.query || snapshot.records.length>100) throw Error('invalid_snapshot');
    const account=site.private?snapshot.account:{state:'public',native:'public'};
    const factory=new CandidateFactory({...snapshot,account},site.source);
    const candidates=uniqueCandidates(snapshot.records.map(record=>{
      if(record.preview_reason && !['navigation_only','section_preview_only','attachments_only','timeline_preview_only','contact_preview_only'].includes(record.preview_reason)) throw Error('invalid_snapshot');
      const previewType={course_entry:'navigation_only',page_section:'section_preview_only',timeline_event:'timeline_preview_only',contact_info:'contact_preview_only'}[record.record_type];
      if(previewType && (record.preview_reason!==previewType || record.complete!==false)) throw Error('invalid_snapshot');
      const p=record.presentation;
      if(p && (!['courses','assignments','timeline','contacts','sections'].includes(p.group) || !['native','unconfirmed','none'].includes(p.course_relation) || typeof p.region!=='string' || p.region.length>300 || !['course_identity','activity_title','section_heading','requested_fields'].includes(p.matched_by))) throw Error('invalid_snapshot');
      const candidate=factory.create({entity:record.entity_id,title:record.title,text:record.text,url:record.url,fields:record.fields,
        evidence:record.evidence,complete:record.complete,view:record.view,missing:record.missing_fields,previewReason:record.preview_reason,recordType:record.record_type,presentation:p && {group:p.group,region:p.region,matched_by:p.matched_by,course_relation:p.course_relation}});
      if(!candidate) throw Error('invalid_snapshot');
      return candidate;
    }));
    const choices=(snapshot.choices || []).map(c=>{
      if(!/^\d+$/.test(c.id) || typeof c.title!=='string' || c.title.length>300) throw Error('invalid_snapshot');
      return {id:c.id,title:c.title,context:c.context || ''};
    });
    return {source:site.source,url:snapshot.url,channel:'dom',intent,account,candidates,choices,
      state:snapshot.state==='needs_choice'?'needs_choice':'succeeded',
      outcome:snapshot.outcome || {status:candidates.length?'matched':snapshot.navigation?.length?'navigation_required':'no_match',page_type:site.source},
      navigation:(snapshot.navigation || []).map(n=>({title:n.title,url:safeUrl(n.url,snapshot.url)})).filter(n=>n.url),
      coverage:{...snapshot.coverage,scope:'current_rendered_view',candidates:candidates.length}, observed_at:snapshot.observed_at,
      warnings:[...(snapshot.warnings || []),...(site.private && account.state!=='known'?['无法可靠识别学校账号：可预览，暂不能保存。']:[]),
        ...(snapshot.frames?['当前仅处理主页面，未采集嵌入页面。']:[])]};
  }
}
