import {ReadingRecipeFactory} from './recipe.js';
import {stablePageUrl} from './resident-registry.js';

/** Projects browser-local location into a safe persisted page, without changing selected text. */
export class ResidentCaptureContext {
  constructor(registry) {this.registry=registry;}
  async prepare(cfg,task,binding,monitoring) {
    if(!this.registry)throw Error('resident_unavailable');
    const url=stablePageUrl(task.url),copy=structuredClone(task);
    copy.url=url;copy.result.url=url;
    for(const c of copy.result.candidates) {
      c.url=stablePageUrl(c.url);
      if(c.context)c.context.frame_url=url;
    }
    const recipe=new ReadingRecipeFactory().create(copy,binding);
    if(!recipe)throw Error('invalid_reading_recipe');
    recipe.resident=await this.registry.bind(cfg,task,recipe,monitoring.interval_s);
    return {task:copy,reading:recipe};
  }
}
