import {SiteRegistry, safeUrl} from './sites.js';
import {CandidateFactory, uniqueCandidates} from './candidates.js';

/** Validate the scoped-reader port and normalize it into the existing save contract. */
export class ExtractionPipeline {
  constructor(sites=new SiteRegistry()) { this.sites=sites; }
  extract(snapshot,intent) {
    const site=this.sites.resolve(snapshot.url,snapshot.fixture);
    if(snapshot.login) throw Error('need_login');
    if(!Array.isArray(snapshot.records) || snapshot.intent?.query!==intent.query || snapshot.records.length>100) throw Error('invalid_snapshot');
    const account=site.private?snapshot.account:{state:'public',native:'public'};
    const factory=new CandidateFactory({...snapshot,account},site.source);
    const candidates=uniqueCandidates(snapshot.records.map(record=>{
      const candidate=factory.create({entity:record.entity_id,title:record.title,text:record.text,url:record.url,fields:record.fields,
        evidence:record.evidence,complete:record.complete,view:record.view,missing:record.missing_fields});
      if(!candidate) throw Error('invalid_snapshot');
      return candidate;
    }));
    const choices=(snapshot.choices || []).map(c=>{
      if(!/^\d+$/.test(c.id) || typeof c.title!=='string' || c.title.length>300) throw Error('invalid_snapshot');
      return {id:c.id,title:c.title,context:c.context || ''};
    });
    return {source:site.source,url:snapshot.url,channel:'dom',intent,account,candidates,choices,
      state:snapshot.state==='needs_choice'?'needs_choice':'succeeded',
      navigation:(snapshot.navigation || []).map(n=>({title:n.title,url:safeUrl(n.url,snapshot.url)})).filter(n=>n.url),
      coverage:{...snapshot.coverage,scope:'current_rendered_view',candidates:candidates.length}, observed_at:snapshot.observed_at,
      warnings:[...(snapshot.warnings || []),...(site.private && account.state!=='known'?['无法可靠识别学校账号：可预览，暂不能保存。']:[]),
        ...(snapshot.frames?['当前仅处理主页面，未采集嵌入页面。']:[])]};
  }
}
