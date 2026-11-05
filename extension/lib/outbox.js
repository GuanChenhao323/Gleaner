import { request } from './api.js';
export const scope = cfg => `${cfg.server}|${cfg.uid}`;
export class Outbox {
  constructor(storage, api = request) { this.storage = storage; this.api = api; }
  async all() { return (await this.storage.get('outbox')).outbox || []; }
  async add(cfg, path, body) {
    const all = await this.all();
    const rows = [...all.filter(r => r.state !== 'confirmed'), ...all.filter(r => r.state === 'confirmed').slice(-15)];
    if (rows.length >= 60 || JSON.stringify(rows).length + JSON.stringify(body).length > 2000000) throw Error('outbox_full');
    const entry = { id: crypto.randomUUID(), scope: scope(cfg), path, body, attempts: 0, state: 'pending', next: 0 };
    await this.storage.set({ outbox: [...rows, entry] });
    return entry.id;
  }
  async flush(cfg) {
    const rows = await this.all();
    for (const row of rows) {
      if (row.scope !== scope(cfg) || row.state !== 'pending' || row.next > Date.now()) continue;
      try {
        row.response = await this.api(cfg, row.path, row.body);
        row.state = 'confirmed';
        // Raw content can leave the queue after confirmation; retain only compact result metadata.
        delete row.body;
      } catch (e) {
        row.error = e.code || e.message;
        row.attempts++;
        if (e.status === 401) row.state = 'auth_required';
        else if (e.status === 409) row.state = 'rejected';
        else if (row.attempts >= 3 || (e.status >= 400 && e.status < 500)) row.state = 'failed';
        row.next = Date.now() + 1000 * 2 ** row.attempts;
      }
      await this.storage.set({ outbox: rows });
    }
  }
  async retry(cfg) {
    const rows = await this.all();
    for (const row of rows) if (row.scope === scope(cfg) && ['failed', 'auth_required'].includes(row.state)) Object.assign(row, { state: 'pending', attempts: 0, next: 0 });
    await this.storage.set({ outbox: rows });
  }
}
