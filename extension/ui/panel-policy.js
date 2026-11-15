import {TimelineCapturePayload} from '../extraction/timeline-summary.js';
/** Presentation eligibility only. The worker remains authoritative for saving. */
export class PanelPolicy {
  evaluate(task, {stale = false, bindingReady = true, saving = false} = {}) {
    const result = task?.result, candidates = result?.candidates || [];
    const generic = result?.source === 'generic';
    const timeline = result?.save_mode==='timeline_summary';
    const valid = task?.schema_version === 2 && task.state === 'succeeded' && !stale;
    const total = candidates.map((c, i) => `【片段 ${i + 1}】${c.raw.title}\n${c.raw.text}`).join('\n\n').length;
    const oversize = candidates.length > 30 || generic && total > 20000 || timeline && new TimelineCapturePayload().text(candidates).length>20000;
    const complete = candidates.length > 0 && candidates.every(c => c.save_allowed);
    return {generic, timeline, count: candidates.length, valid, oversize,
      bindingVisible: valid && generic && candidates.length > 0 && complete && !oversize,
      canSave: valid && complete && !oversize && (!generic || bindingReady) && !saving && !task.submission};
  }
}
