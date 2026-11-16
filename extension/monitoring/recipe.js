/** Freeze the user's query and context, never cookies or provisional DOM selectors. */
export class ReadingRecipeFactory {
  create(task, sourceBinding) {
    const result=task.result, generic=result.source==='generic';
    const intent=task.intent || result.intent;
    if(intent?.version!==2)return null; // Old frozen previews remain saveable, without inventing a recipe.
    const keys=['projection','semester','week','weekday','period'];
    const candidates=result.candidates || [];
    const view={};
    for(const key of keys) {
      const values=candidates.map(c=>c.target?.locator.view?.[key] ?? c.raw.fields?.[key]).filter(v=>v!==undefined && v!=='');
      if(values.length && values.every(v=>v===values[0]))view[key]=values[0];
    }
    return {version:1,url:task.url,query:task.query,match_scope:task.match_scope || 'content',
      ...(result.save_mode==='timeline_summary'?{representation:'timeline_summary'}:{}),
      intent,choice:task.choice || '',source:result.source,view,
      source_label:generic?sourceBinding.label:'',
      ...(generic && sourceBinding.identity?{account_probe:{version:1,kind:sourceBinding.identity.probe,display:sourceBinding.identity.display}}:{}),
      binding:generic?{adapter:'generic',origin:new URL(task.url).origin,account_key:sourceBinding.kind==='public'?'public':sourceBinding.identity?.account_key || 'unverified'}:result.binding};
  }
}
