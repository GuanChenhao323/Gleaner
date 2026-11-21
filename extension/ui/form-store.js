/** One storage key per owner and original tab. No credentials or page content. */
export class CaptureFormStore {
  constructor(storage) { this.storage=storage; }
  key(cfg,tabId) { return `captureForm.v2:${cfg.server || 'local'}|${cfg.uid || 'anonymous'}|${tabId}`; }
  async load(cfg,tabId) { const key=this.key(cfg,tabId); return (await this.storage.get(key))[key] || null; }
  write(cfg,form) { return this.storage.set({[this.key(cfg,form.tabId)]:{...form,updated_at:Date.now()}}); }
  historyKey(cfg,id) { return `captureHistoryForm.v1:${cfg.server || 'local'}|${cfg.uid || 'anonymous'}|${id}`; }
  async loadHistory(cfg,id) { const key=this.historyKey(cfg,id);return (await this.storage.get(key))[key] || null; }
  writeHistory(cfg,form) { return this.storage.set({[this.historyKey(cfg,form.taskId)]:{...form,updated_at:Date.now()}}); }
}
