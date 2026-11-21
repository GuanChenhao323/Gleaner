import {safeUrl} from './sites.js';

/** Generic fragments have evidence, not a fabricated native school identity. */
export class FragmentPipeline {
  extract(snapshot,intent) {
    if(snapshot.source!=='generic' || snapshot.login || !safeUrl(snapshot.url) || snapshot.intent?.query!==intent.query || !Array.isArray(snapshot.records) || snapshot.records.length>100)throw Error('invalid_snapshot');
    const candidates=snapshot.records.map((r,i)=>{
      if(r.entity_id!==null || r.record_type!=='web_fragment' || typeof r.title!=='string' || !r.title.trim() || r.title.length>300 || typeof r.text!=='string' || !r.text.trim() || r.text.length>20000 || r.url!==snapshot.url || r.evidence?.channel!=='dom' || r.evidence.text!==r.text || typeof r.evidence.locator!=='string' || r.evidence.locator.length>4000 || r.context?.frame_url!==snapshot.url || r.context.completeness!=='fragment' || r.context.matched_by!=='literal' || !['paragraph','list_row','table_row','section','text'].includes(r.context.boundary))throw Error('invalid_snapshot');
      return {candidate_id:`candidate-${i+1}`,entity_id:null,record_type:r.record_type,raw:{title:r.title,text:r.text,fields:{}},url:r.url,evidence:[r.evidence],context:r.context,completeness:'fragment',save_allowed:true,save_reason:'',missing_fields:[],target:null};
    });
    return {source:'generic',url:snapshot.url,title:snapshot.title,channel:'dom',intent,account:snapshot.account || {state:'unknown'},binding:null,candidates,choices:[],state:'succeeded',outcome:snapshot.outcome,
      coverage:{...snapshot.coverage,scope:'current_rendered_view',match_basis:'literal',candidates:candidates.length},observed_at:snapshot.observed_at,warnings:snapshot.warnings || []};
  }
}
