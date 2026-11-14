import { safeUrl } from './sites.js';

export const clean = value => String(value || '').split('\n').map(s => s.replace(/\s+/g, ' ').trim()).filter(Boolean).join('\n');

/** Technical normalization only. No semantic deadline inference or personal ranking. */
export class CandidateFactory {
  constructor(snapshot, adapter) { this.snapshot = snapshot; this.adapter = adapter; }
  create({ entity = null, title, text, url = this.snapshot.url, fields = {}, evidence, complete = false, view: context = {}, missing = [], previewReason = '', recordType = 'detail', presentation }) {
    title = clean(title); text = clean(text); url = safeUrl(url, this.snapshot.url);
    if (!title || title.length > 300 || !text || text.length > 20000 || !url || !evidence) return null;
    const privatePage = this.adapter !== 'fie';
    const reason = ['navigation_only','section_preview_only','attachments_only','timeline_preview_only','contact_preview_only'].includes(previewReason)?previewReason:!entity ? 'identity_unknown' : missing.length ? 'fields_missing' : !complete ? 'detail_required'
      : privatePage && this.snapshot.account.state !== 'known' ? 'account_unknown' : '';
    const view = { route: new URL(url).hash, query: new URL(url).search, ...context };
    return { entity_id: entity, record_type:recordType, ...(presentation?{presentation}:{}), raw: { title, text, fields }, url, evidence: [evidence],
      completeness: complete ? 'detail' : 'summary', save_allowed: !reason, save_reason: reason, missing_fields: missing,
      // v2 is explicitly a snapshot-only recipe. It cannot enable a monitor.
      target: entity && !previewReason ? { entity_id: entity, locator: { url, frame_url: url, view }, raw: { title, text, fields },
        recipe: { adapter: this.adapter, version: 2, strategy: 'snapshot', entity_id: entity, url, view }, supported: false, enabled: false } : null };
  }
}


export function uniqueCandidates(values) {
  const found = new Map();
  for (const c of values.filter(Boolean)) {
    // Identity-backed duplicate anchors may be merged; uncertain blocks stay separate.
    const key = c.entity_id ? `${c.entity_id}|${new URL(c.url).origin}` : `unresolved:${found.size}`;
    if (!found.has(key)) found.set(key, c);
    else {
      const previous = found.get(key);
      if (c.raw.title.length > previous.raw.title.length) found.set(key, c);
    }
  }
  return [...found.values()].map((c, i) => ({ ...c, candidate_id: `candidate-${i + 1}` }));
}

export function fieldsFromLabels(labels, mappings) {
  const fields = {};
  for (const [name, pattern] of Object.entries(mappings)) {
    const pair = Object.entries(labels || {}).find(([label]) => label === name || pattern.test(label));
    if (pair) fields[name] = clean(pair[1]);
  }
  return fields;
}
