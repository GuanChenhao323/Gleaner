const TTL = 24 * 60 * 60 * 1000;
/** Owner isolation and all mutations live here; replacement workers share no in-memory state. */
export class DraftRepository {
  constructor(storage, clock = Date.now) { this.storage = storage; this.clock = clock; this.chain = Promise.resolve(); }
  async rows() {
    const data = (await this.storage.get('extractionDrafts')).extractionDrafts || [];
    return data.filter(r => r.expires_at > this.clock());
  }
  mutate(fn) {
    const next = this.chain.then(async () => {
      const rows = await this.rows();
      const result = await fn(rows);
      if (JSON.stringify(rows).length > 2500000) throw Error('draft_limit');
      await this.storage.set({ extractionDrafts: rows });
      return structuredClone(result);
    });
    this.chain = next.catch(() => {}); return next;
  }
  async create(owner, values, id = crypto.randomUUID()) {
    return this.mutate(rows => {
      const previous = rows.find(r => r.owner === owner && r.id === id);
      if (previous) {
        if (previous.signature !== values.signature) throw Error('idempotency_conflict');
        return { ...previous, fresh: false };
      }
      if (rows.filter(r => r.owner === owner).length >= 10 || rows.length >= 20) throw Error('draft_limit');
      const task = { ...values, id, owner, state: 'queued', created_at: this.clock(), expires_at: this.clock() + TTL };
      rows.push(task); return { ...task, fresh: true };
    });
  }
  async get(owner, id) {
    await this.chain;
    const row = (await this.rows()).find(r => r.owner === owner && r.id === id);
    if (!row) throw Error('draft_not_found');
    return structuredClone(row);
  }
  async list(owner) {
    return this.mutate(rows => rows.filter(r => r.owner === owner).map(({ result, owner: _, signature, intent, ...r }) => r).reverse());
  }
  update(owner, id, values) { return this.mutate(rows => { const r = rows.find(x => x.owner === owner && x.id === id); if (!r) throw Error('draft_not_found'); Object.assign(r, values); return r; }); }
  remove(owner, id) { return this.mutate(rows => { const i = rows.findIndex(r => r.owner === owner && r.id === id); if (i < 0) throw Error('draft_not_found'); rows.splice(i, 1); return {}; }); }
  recover() { return this.mutate(rows => { for (const row of rows) if (['running', 'queued'].includes(row.state)) { row.state = 'interrupted'; row.error = 'worker_interrupted'; delete row.result; } }); }
}
