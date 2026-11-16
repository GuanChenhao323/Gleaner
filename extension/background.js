import {ResidentTabRegistry} from './monitoring/resident-registry.js';
import {ResidentCycleReader} from './monitoring/resident-reader.js';
import { request } from './lib/api.js';
import { Outbox, scope } from './lib/outbox.js';
import { DomPageReader } from './extraction/readers.js';
import { DraftRepository } from './extraction/drafts.js';
import { PageExtractionService } from './extraction/service.js';
import {PageReentry,SourceSessionVerifier,ConditionalPageReader} from './monitoring/page-session.js';
import {ReadingJobExecutor} from './monitoring/jobs.js';
const storage = chrome.storage.local;
const box = new Outbox(storage);
const files = ['content/runtime.js', 'adapters/must_moodle.js', 'adapters/must_student_portal.js', 'adapters/must_fie_people.js', 'content/capture.js'];
let chain = Promise.resolve();
const serial = fn => { const next = chain.then(fn, fn); chain = next.catch(() => {}); return next; };
const config = async () => (await storage.get('config')).config || {};
let devicePromise;
async function device() {
  if (!devicePromise) devicePromise = (async () => {
    const data = await storage.get(['device', 'salt']);
    if (data.device && data.salt) return data;
    const value = { device: crypto.randomUUID(), salt: crypto.randomUUID() };
    await storage.set(value); return value;
  })();
  try { return await devicePromise; } catch (e) { devicePromise = null; throw e; }
}
async function accountKey(adapter, account) {
  if (account === 'public') return 'public';
  if (!account) throw Error('account_unknown');
  const { salt } = await device();
  return [...new Uint8Array(await crypto.subtle.digest('SHA-256', new TextEncoder().encode(`${salt}|${adapter}|${account}`)))].map(b => b.toString(16).padStart(2, '0')).join('');
}
const domReader = new DomPageReader(chrome);
const reentry=new PageReentry(chrome,storage,domReader);
const residents=new ResidentTabRegistry(chrome,storage,domReader,accountKey);
const readingJobs=new ReadingJobExecutor({storage,api:request,outbox:box,
  reader:new ResidentCycleReader({browser:chrome,registry:residents,reader:domReader,verifier:new SourceSessionVerifier(accountKey),config,legacy:new ConditionalPageReader(reentry,new SourceSessionVerifier(accountKey))}),reentry,config,device});
const extraction = new PageExtractionService({ browser: chrome, repository: new DraftRepository(storage),
  reader: domReader, config, accountKey, residents, findSubmission:recoverSubmission, enqueue: enqueueCapture, enqueueWeb: enqueueWebCapture,
  enqueueTimeline:(cfg,payload)=>enqueueCollection(cfg,payload,'/api/v1/timeline-captures') });
// Content scripts have no reason to access Campus Radar tokens or private drafts.
storage.setAccessLevel?.({ accessLevel: 'TRUSTED_CONTEXTS' });
async function invoke(tabId, method, arg) {
  await chrome.scripting.executeScript({ target: { tabId, frameIds: [0] }, files });
  const [result] = await chrome.scripting.executeScript({ target: { tabId, frameIds: [0] }, func: async (name, value) => {
    try { return { ok: true, value: await globalThis.CampusRadar[name](value) }; }
    catch (e) { return { ok: false, error: e.code || e.message }; }
  }, args: [method, arg ?? null] });
  if (!result?.result || result.result.ok !== true) throw Error(result?.result?.error || 'page_read_failed');
  return result.result.value;
}
async function readTab(tabId, recipe) {
  const until = Date.now() + 18000;
  while (Date.now() < until) {
    const tab = await chrome.tabs.get(tabId);
    if (tab.status === 'complete') return invoke(tabId, 'wait', recipe);
    await new Promise(r => setTimeout(r, 250));
  }
  throw Error('render_timeout');
}
function canClose(tab, expected) {
  if (tab.active) return false; // A user who opened the runner owns its current interaction.
  if (tab.url === expected || tab.url?.startsWith(chrome.runtime.getURL('runner.html'))) return true;
  try {
    const url = new URL(tab.url);
    return url.origin === new URL(expected).origin && /\/(login|auth|sso)(\/|\.|$)/i.test(url.pathname);
  } catch { return false; }
}
async function backgroundRead(recipe, jobKey) {
  const origin = new URL(recipe.url).origin;
  const times = (await storage.get('originTimes')).originTimes || {};
  const delay = 2100 - (Date.now() - (times[origin] || 0));
  if (delay > 0) await new Promise(r => setTimeout(r, delay));
  times[origin] = Date.now(); await storage.set({ originTimes: times });
  if (!(await chrome.permissions.contains({ origins: [new URL(recipe.url).origin + '/*'] }))) throw Error('permission_denied');
  const data = (await storage.get('ownedTabs')).ownedTabs || {};
  const tab = await chrome.tabs.create({ url: chrome.runtime.getURL('runner.html') + '#' + jobKey, active: false });
  data[tab.id] = recipe.url;
  await storage.set({ ownedTabs: data });
  try { await chrome.tabs.update(tab.id, { url: recipe.url }); return await readTab(tab.id, recipe); }
  finally {
    try { const current = await chrome.tabs.get(tab.id); if (canClose(current, recipe.url)) await chrome.tabs.remove(tab.id); } catch { /* already closed */ }
    delete data[tab.id]; await storage.set({ ownedTabs: data });
  }
}
async function cleanup() {
  const owned = (await storage.get('ownedTabs')).ownedTabs || {};
  for (const [id, url] of Object.entries(owned)) {
    try { const tab = await chrome.tabs.get(Number(id)); if (canClose(tab, url)) await chrome.tabs.remove(Number(id)); } catch { /* gone */ }
  }
  // Covers interruption between runner tab creation and recording its ID.
  for (const tab of await chrome.tabs.query({})) if (!tab.active && tab.url?.startsWith(chrome.runtime.getURL('runner.html'))) await chrome.tabs.remove(tab.id);
  await storage.set({ ownedTabs: {} });
}
async function legacyWake() {
  const cfg = await config();
  if (!cfg.token) return;
  await cleanup();
  await processIntents(cfg);
  await box.flush(cfg);
  const active = (await storage.get('activeJob')).activeJob;
  if (active) {
    // A terminated worker cannot assert a successful read. Persist an explicit failure for its lease.
    if (active.scope === scope(cfg) && !active.queued && !(await box.all()).some(r => r.path === `/api/v1/monitor-jobs/${active.job.id}/result` && (r.body?.lease === active.job.lease || r.state === 'confirmed'))) {
      await box.add(cfg, `/api/v1/monitor-jobs/${active.job.id}/result`, { schema_version: 1, device_id: active.job.device_id, lease: active.job.lease, revision: active.job.revision, status: 'failed' });
    }
    await storage.remove('activeJob'); await box.flush(cfg);
  }
  const { device: id } = await device();
  const { job } = await request(cfg, '/api/v1/monitor-jobs/claim', { device_id: id });
  if (!job) return;
  await storage.set({ activeJob: { scope: scope(cfg), job, queued: false } });
  let payload = { schema_version: 1, device_id: id, lease: job.lease, revision: job.revision };
  try {
    const found = await backgroundRead(job.recipe, `job-${job.id}`);
    payload = { ...payload, status: 'success', raw: found.raw, account_key: await accountKey(found.adapter, found.account) };
  } catch (e) {
    const allowed = ['need_login', 'selection_missing', 'render_timeout', 'permission_denied', 'account_mismatch', 'unsupported', 'view_mismatch', 'route_mismatch'];
    payload.status = allowed.includes(e.message) ? e.message : 'failed';
  }
  await box.add(cfg, `/api/v1/monitor-jobs/${job.id}/result`, payload);
  await storage.set({ activeJob: { scope: scope(cfg), job, queued: true } });
  await box.flush(cfg); await storage.remove('activeJob');
}
async function wake() {
  const cfg=await config();
  if(!cfg.token)return;
  try {await readingJobs.wake(cfg);}catch {/* Connection remains visible in popup/workbench; next alarm retries. */}
  try {await legacyWake();}catch {/* Legacy failures must not block saved-page monitoring. */}
}
async function alarm() {
  if (!(await chrome.alarms.get('campus-radar'))) chrome.alarms.create('campus-radar', { periodInMinutes: 1 });
}
chrome.runtime.onInstalled.addListener(() => { alarm(); serial(wake).catch(() => {}); });
chrome.runtime.onStartup.addListener(() => { alarm(); serial(wake).catch(() => {}); });
chrome.alarms.onAlarm.addListener(a => { if (a.name === 'campus-radar') serial(wake).catch(() => {}); });
chrome.runtime.onMessage.addListener((m, sender, reply) => {
  if (sender.id !== chrome.runtime.id || (sender.url && !sender.url.startsWith(chrome.runtime.getURL('')))) return false;
  const action = async () => {
    const cfg = await config();
    if (m.type === 'config') return { ...cfg, token: undefined };
    if (m.type === 'login') {
      const url = new URL(m.server); if (!['http:', 'https:'].includes(url.protocol) || url.username || url.password) throw Error('invalid_server');
      const next = { server: url.origin };
      const data = await request(next, '/api/auth/login', { email: m.email, password: m.password }, { login: true });
      Object.assign(next, { token: data.token, uid: data.user.id, email: data.user.email });
      await storage.set({ config: next }); await box.retry(next); return { uid: next.uid, email: next.email, server: next.server };
    }
    if (m.type === 'logout') { await storage.set({ config: { server: cfg.server } }); return {}; }
    if (!cfg.uid || !cfg.token) throw Error('backend_login_required');
    if (m.type === 'connection.check') {
      const user = await request(cfg, '/api/me', undefined, { session: true });
      const current = await config();
      if (user.id !== cfg.uid || current.uid !== cfg.uid || current.server !== cfg.server) throw Error('backend_account_changed');
      return { state: 'connected', uid: user.id, email: user.email };
    }
    if (m.type?.startsWith('extract.')) return extraction.handle(cfg, m);
    if (m.type === 'scan') {
      const page = await invoke(m.tabId, 'wait');
      if (!page.account) throw Error('account_unknown');
      page.binding = { adapter: page.adapter, origin: new URL(page.url).origin, account_key: await accountKey(page.adapter, page.account) };
      delete page.account;
      return page;
    }
    if (m.type === 'preview') {
      const found = await backgroundRead(m.recipe, 'preview');
      const key = await accountKey(found.adapter, found.account);
      if (key !== m.binding?.account_key || found.adapter !== m.binding?.adapter) throw Error('account_mismatch');
      delete found.account; return found;
    }
    if (m.type === 'highlight') { await invoke(m.tabId, 'highlight', m.recipe); return {}; }
    if (m.type === 'manual') {
      const page = await invoke(m.tabId, 'scan');
      if (page.adapter !== 'fie') throw Error('manual_private_unsupported');
      const target = await invoke(m.tabId, 'manual'); target.supported = false;
      return { target, binding: { adapter: 'manual', origin: new URL(target.locator.url).origin, account_key: 'public' } };
    }
    if (m.type === 'submit') {
      return enqueueCapture(cfg, m);
    }
    if (m.type === 'status') {
      await processIntents(cfg); await box.flush(cfg);
      const rows = await box.all();
      return { entries: rows.filter(r => r.scope === scope(cfg)).map(({ body, ...r }) => r), intents: ((await storage.get('intents')).intents || []).filter(r => r.scope === scope(cfg)).map(({ selected, captured, binding, ...r }) => r) };
    }
    if (m.type === 'wake') { await processIntents(cfg); await wake(); return {}; }
    if (m.type === 'retry') {
      if (m.request_id !== undefined && (typeof m.request_id !== 'string' || !m.request_id || m.request_id.length > 100)) throw Error('invalid_request');
      await box.retry(cfg, m.request_id); await box.flush(cfg); return {};
    }
    throw Error('unknown_message');
  };
  // Reads have their own repository/reader queue; monitor navigation must not block popup queries.
  const independent = ['config', 'connection.check', 'extract.start', 'extract.get', 'extract.list', 'extract.delete'].includes(m.type);
  (independent ? action() : serial(action)).then(value => reply({ ok: true, value }), e => reply({ ok: false, error: e.code || e.message }));
  return true;
});
async function enqueueCapture(cfg, m) {
  if (!Array.isArray(m.selected) || !m.selected.length || m.selected.length > 30) throw Error('invalid_selection');
  if (m.selected.some(c => c.needs_detail)) throw Error('preview_required');
  const { device: id } = await device();
  const signature = [...new Uint8Array(await crypto.subtle.digest('SHA-256', new TextEncoder().encode(JSON.stringify({binding:m.binding,selected:m.selected,enabled:m.enabled,reading:m.reading}))))].map(b=>b.toString(16).padStart(2,'0')).join('');
  const intent = { id: m.request_id || crypto.randomUUID(), signature, scope: scope(cfg), tabId: m.tabId, binding: m.binding, selected: m.selected, enabled: m.enabled, reading:m.reading, state: 'pending' };
  const existing = (await storage.get('intents')).intents || [];
  const previous = existing.find(r => r.scope === scope(cfg) && r.id === intent.id);
  if (previous) {
    if (previous.signature !== signature) throw Error('idempotency_conflict');
    return { request_id: previous.id, device_id: id };
  }
  const pending = existing.filter(r => r.state === 'pending');
  if (pending.length >= 20) throw Error('outbox_full');
  const intents = [...existing.filter(r => r.state !== 'pending').slice(-20), ...pending];
  if (JSON.stringify([...intents, intent]).length > 2000000) throw Error('outbox_full');
  await storage.set({ intents: [...intents, intent] });
  queueMicrotask(() => serial(async () => { await processIntents(cfg); await box.flush(cfg); if(intent.reading?.resident)await wake(); }).catch(() => {}));
  return { request_id: intent.id, device_id: id };
}
async function enqueueWebCapture(cfg,payload) {
  return enqueueCollection(cfg,payload,'/api/v1/web-captures');
}
async function enqueueCollection(cfg,payload,path) {
  const {device:id}=await device();
  // The atomic outbox write is the durable submission, before acknowledgement.
  await box.add(cfg,path,{...payload,device_id:id});
  queueMicrotask(()=>serial(async()=>{await box.flush(cfg);if(payload.reading?.resident)await wake();}).catch(()=>{}));
  return {request_id:payload.request_id,device_id:id};
}
async function recoverSubmission(cfg,id) {
  const row=(await box.all()).find(r=>r.scope===scope(cfg)&&r.request_id===id&&['/api/v1/captures','/api/v1/web-captures','/api/v1/timeline-captures'].includes(r.path));
  const intent=((await storage.get('intents')).intents || []).find(r=>r.scope===scope(cfg)&&r.id===id);
  return row || intent ? {request_id:id,device_id:(await device()).device} : null;
}
async function processIntents(cfg) {
  const intents = (await storage.get('intents')).intents || [];
  for (const intent of intents) {
    if (intent.scope !== scope(cfg) || intent.state !== 'pending') continue;
    try {
      const targets = intent.captured || [];
      for (const candidate of intent.selected) {
        if (targets.some(t => t.candidate_id === candidate.candidate_id)) continue;
        // Save exactly the raw snapshot the user previewed. Later reads belong to monitor jobs.
        const found = candidate;
        if (candidate.needs_detail) throw Error('preview_required');
        targets.push({ candidate_id: candidate.candidate_id, entity_id: candidate.entity_id,
          locator: found.locator, raw: found.raw, recipe: found.recipe, supported: candidate.supported, enabled: Boolean(intent.enabled && candidate.supported) });
        intent.captured = targets; await storage.set({ intents });
      }
      await box.add(cfg, '/api/v1/captures', { schema_version: 1, request_id: intent.id, device_id: (await device()).device, binding: intent.binding, targets, ...(intent.reading?{reading:intent.reading}:{}) });
      intent.state = 'queued';
      delete intent.selected; delete intent.captured;
    } catch (e) { intent.state = 'failed'; intent.error = e.message; delete intent.selected; delete intent.captured; }
    await storage.set({ intents });
  }
}
// Restore a missing alarm without postponing an existing scheduled wake-up.
alarm();
serial(async () => { await processIntents(await config()); await wake(); }).catch(() => {});
