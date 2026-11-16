import {accountIdentity} from '../identity/account-binding.js';
/** A source label is a user declaration, never an authenticated website account. */
export function sourceBinding(value) {
  if(!value || !['public','labeled'].includes(value.kind) || typeof value.label!=='string')throw Error('source_label_required');
  const label=value.label.normalize('NFKC').trim();
  if(!label || label.length>80 || value.kind==='public' && label!=='公开网页')throw Error('source_label_required');
  if(value.identity && value.kind!=='labeled')throw Error('invalid_account_proof');
  return {kind:value.kind,label,...(value.identity?{identity:accountIdentity(value.identity)}:{})};
}

export class WebCapturePayload {
  create(task,binding) {
    const r=task.result;
    if(r?.source!=='generic' || !r.candidates?.length || r.candidates.length>30 || r.candidates.some(c=>c.record_type!=='web_fragment' || !c.save_allowed))throw Error('invalid_selection');
    const fragments=r.candidates.map(c=>({candidate_id:c.candidate_id,title:c.raw.title,text:c.raw.text,evidence:c.evidence[0],context:c.context}));
    const text=fragments.map((f,i)=>`【片段 ${i+1}】${f.title}\n${f.text}`).join('\n\n');
    if(text.length>20000)throw Error('content_too_large');
    return {schema_version:1,request_id:task.id,source:{url:r.url,title:(r.title || new URL(r.url).hostname).slice(0,300)},query:task.query,match_scope:r.intent.match_scope || 'content',observed_at:r.observed_at,source_binding:sourceBinding(binding),fragments};
  }
}
