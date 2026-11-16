import {errorText} from './errors.js';
import {SiteRegistry} from '../extraction/sites.js';

/** Coordinates browser/client/form ports. Renderers own DOM, worker owns captures. */
export class CaptureController {
  constructor({browser, client, forms, view, location, clock = Date.now}) {
    Object.assign(this, {browser, client, forms, view, location, clock});
    this.cfg = {}; this.form = null; this.task = null; this.entry = null;
    this.generation = 0; this.connectionGeneration = 0; this.saving = false;
    this.refreshing = false; this.polling = false; this.disposed = false;
    this.receiptPending = false; this.historical = false; this.closed = false;
  }
  owner(cfg = this.cfg) { return `${cfg.server || ''}|${cfg.uid || ''}`; }
  guard(action) {
    return async () => {
      try { await action(); }
      catch (e) {
        if (this.disposed) return;
        this.actionError = e.message;
        this.view.status(errorText(e.message), true);
        if (['backend_login_required', 'unauthorized'].includes(e.message)) this.openSettings();
      }
    };
  }
  async init() {
    this.view.ready(false); this.bind();
    this.cfg = await this.client.send({type: 'config'}); this.view.config(this.cfg);
    const args = new URL(this.location.href).searchParams;
    this.currentTabId = Number(args.get('tab')) || (await this.browser.tabs.query({active: true, currentWindow: true}))[0]?.id;
    if (!this.currentTabId) throw Error('page_read_failed');
    try { this.currentTab = await this.browser.tabs.get(this.currentTabId); }
    catch { this.currentTab = {id: this.currentTabId}; }
    await this.loadCurrentForm(); this.view.ready(true); this.render();
    this.timer = setInterval(() => this.guard(() => this.poll())(), 1200);
    void this.checkConnection();
    if (this.form.phase === 'prepared' && this.cfg.uid && this.form.url && await this.browser.permissions.contains({origins: [new URL(this.form.url).origin + '/*']})) await this.dispatch();
    else await this.restoreTask();
  }
  async loadCurrentForm() {
    const stored = await this.forms.load(this.cfg, this.currentTabId), tab = this.currentTab;
    this.form = stored && (!tab.url || stored.url === tab.url) ? stored : {tabId: tab.id, url: tab.url || '', query: '', match_scope: 'content', taskId: null, phase: 'editing'};
    this.historical = false; this.closed = !tab.url;this.uncertainSave = Boolean(this.form.pending_save);if (this.uncertainSave) this.entry = {state:'failed',error:'worker_timeout'};
    this.view.$('query').value = this.form.query;
    this.view.select('match-scope', this.form.match_scope || 'content');
    this.view.$('auto-monitor').checked = this.form.auto_monitor !== false;
    this.view.select('monitor-interval', String(this.form.monitor_interval || 1800));
    this.view.restoreBinding(this.form.source_binding, this.form.binding_draft);
    this.showPage({...tab, url: this.form.url});
    this.view.status(this.form.read_error ? errorText(this.form.read_error) : '', Boolean(this.form.read_error));
  }
  persist() { return this.historical ? this.forms.writeHistory({...this.cfg}, {...this.form}) : this.forms.write({...this.cfg}, {...this.form}); }
  async restoreTask() {
    try { await this.refresh(); }
    catch (e) {
      if (e.message !== 'draft_not_found') throw e;
      this.form = {...this.form, taskId: null, phase: 'editing'}; this.task = null;
      await this.persist(); this.render(); this.view.status('上次预览已过期或已删除，条件保留，请重新提取。');
    }
  }
  openSettings() {
    this.view.$('connection').open = true; this.view.$('connection-toggle').setAttribute('aria-expanded', 'true');
  }
  bind() {
    const $ = id => this.view.$(id);
    $('query').oninput = () => this.edit();
    $('query').onkeydown = e => { if (e.key === 'Enter' && !$('capture').disabled) {e.preventDefault(); this.guard(() => this.capture())();} };
    $('clear-query').onclick = () => {if (!this.busy()) {$('query').value = '';this.edit();$('query').focus();}};
    $('match-scope').onchange = () => this.edit();
    for (const b of this.view.document.querySelectorAll('[data-scope]')) b.onclick = () => {
      if (this.busy()) return;
      this.view.select('match-scope', b.dataset.scope); this.edit();
    };
    for(const id of ['auto-monitor','monitor-interval']) $(id).onchange=()=>{
      if(this.busy() || this.task?.submission)return;
      this.form.auto_monitor=$('auto-monitor').checked;
      this.form.monitor_interval=Number($('monitor-interval').value);void this.persist();this.render();
    };
    $('capture').onclick = this.guard(() => this.capture());
    $('save').onclick = this.guard(() => this.save());
    $('refresh').onclick = this.guard(() => this.refresh(true));
    $('retry').onclick = this.guard(async () => {
      if (this.busy()) return;
      if (this.uncertainSave && !this.task?.submission) {await this.save();return;}
      if (!this.task?.submission) return;
      const generation = this.generation; this.saving = true; this.render();
      try { await this.client.send({type: 'retry', request_id: this.task.submission.request_id}); if (generation === this.generation) await this.refresh(true); }
      finally {this.saving = false;if (generation === this.generation) this.render();}
    });
    $('verify-account').onclick = this.guard(async () => {
      if(this.busy() || !this.task || this.task.submission)throw Error('preview_required');
      const generation=this.generation;
      const {identity}=await this.client.send({type:'extract.verifyAccount',id:this.task.id});
      if(generation!==this.generation)return;
      if(!this.view.document.defaultView.confirm(`将当前来源绑定到 ${identity.display}？以后重读必须核对同一账号。别名只是备注。`))return;
      this.actionError = null;this.view.source.setIdentity(identity);this.bindingChanged();
      this.view.status('来源账号已核对。保存后请在工作台测试后台重读。');
    });
    $('source-kind').onchange = () => {this.view.source.choose();this.bindingChanged();};
    $('source-label').oninput = () => this.bindingChanged();
    $('source-label').onkeydown = e => {if (e.key === 'Enter') {e.preventDefault();this.guard(() => this.confirmBinding())();}};
    $('confirm-binding').onclick = this.guard(() => this.confirmBinding());
    $('change-binding').onclick = () => {this.view.source.change();this.bindingChanged();};
    $('connection-toggle').onclick = () => { $('connection').open = !$('connection').open;$('connection-toggle').setAttribute('aria-expanded', String($('connection').open)); };
    $('connection-close').onclick = () => {$('connection').open = false;$('connection-toggle').setAttribute('aria-expanded', 'false');};
    $('connection').ontoggle = () => $('connection-toggle').setAttribute('aria-expanded', String($('connection').open));
    $('receipt-settings').onclick = () => this.openSettings();
    $('check-connection').onclick = this.guard(() => this.checkConnection());
    $('login').onclick = this.guard(() => this.login());
    $('logout').onclick = this.guard(async () => {await this.client.send({type: 'logout'});await this.changeOwner(await this.client.send({type: 'config'}));});
    $('drafts').onclick = this.guard(async () => {
      const panel = $('history-panel'); panel.hidden = !panel.hidden;
      $('drafts').setAttribute('aria-expanded', String(!panel.hidden));
      if (!panel.hidden) await this.history();
    });
    $('history-close').onclick = () => {$('history-panel').hidden = true;$('drafts').setAttribute('aria-expanded', 'false');};
    $('page-more').onclick = () => { $('page-url').hidden = !$('page-url').hidden;$('page-more').setAttribute('aria-expanded', String(!$('page-url').hidden)); };
    $('return-current').onclick = this.guard(() => this.returnCurrent());
    $('continue').onclick = this.guard(async () => {
      if (this.busy()) return;
      if (this.historical) await this.returnCurrent();
      else this.edit();
      $('query').focus();
    });
    $('workbench').onclick = this.guard(() => {
      const rows = this.entry?.response?.results || [], item = rows.find(r => r.status !== 'failed' && Number.isInteger(r.item_id) && r.item_id > 0);
      const reading=this.entry?.response?.reading_source_id;
      return this.browser.tabs.create({url: (this.cfg.server || 'http://localhost:8080') + (Number.isInteger(reading)&&reading>0?'/#/sources':item ? `/#/item/${item.item_id}` : '/#/sources')});
    });
  }
  busy() { return this.saving || Boolean(this.receiptPending && !this.entry?.error); }
  edit() {
    if (!this.form || this.busy() || this.historical) return;
    this.actionError = null;
    this.generation++; this.task = null; this.entry = null; this.receiptPending = false;
    this.form = {...this.form, query: this.view.$('query').value, match_scope: this.view.$('match-scope').value || 'content', taskId: null, phase: 'editing', pending_save: false, read_error: null};this.uncertainSave = false;
    void this.persist().catch(() => {}); this.view.clear(); this.render();
    this.view.status(this.form.query ? '条件已修改，点击提取生成新预览。' : '');
  }
  confirmBinding() { this.view.source.confirm(); return this.bindingChanged(); }
  bindingChanged() {
    if (!this.form || this.busy()) return;
    Object.assign(this.form, this.view.source.state());
    void this.persist().catch(() => {}); this.render();
  }
  async login() {
    if (this.connecting) return;
    const $ = id => this.view.$(id), previous = this.owner();
    if ($('login-fields').hidden) {
      $('login-fields').hidden = false;$('login').textContent = '登录工作台';$('password').focus();return;
    }
    const url = new URL($('server').value);
    if (!['http:', 'https:'].includes(url.protocol) || url.username || url.password) throw Error('invalid_server');
    const credentials = {type: 'login', server: url.origin, email: $('email').value.trim(), password: $('password').value};
    const permission = this.browser.permissions.request({origins: [url.origin + '/*']});
    this.connecting = true;this.loginControls(true);
    try {
      if (!await permission) throw Error('permission_denied');
      await this.client.send(credentials);
      const cfg = await this.client.send({type: 'config'});
      if (this.owner(cfg) !== previous) await this.changeOwner(cfg);
      else {this.cfg = cfg;this.view.config(cfg);await this.refresh(true);}
      $('connection').open = false;$('connection-toggle').setAttribute('aria-expanded', 'false');
      await this.checkConnection();this.render();
    } catch (e) {
      $('connection-error').textContent = errorText(e.message);$('connection-error').hidden = false;throw e;
    } finally {credentials.password = ''; $('password').value = '';this.connecting = false;this.loginControls(false);}
  }
  loginControls(busy) {
    for (const id of ['server','email','password','login','logout','check-connection']) this.view.$(id).disabled = busy;
  }
  async changeOwner(cfg) {
    this.generation++; this.connectionGeneration++; this.cfg = cfg;
    this.task = null; this.entry = null; this.receiptPending = false; this.saving = false;this.uncertainSave = false;
    this.view.$('history').replaceChildren();this.view.$('history-panel').hidden = true;this.view.$('drafts').setAttribute('aria-expanded', 'false');
    this.view.config(cfg);this.view.clear();await this.loadCurrentForm();this.render();
    void this.checkConnection();
  }
  async checkConnection() {
    const cfg = {...this.cfg}, generation = ++this.connectionGeneration;
    if (!cfg.uid) {this.view.connection({state: 'anonymous'});return;}
    this.connectionCheckedAt = this.clock(); this.view.connection({state: 'checking'});
    try {
      const data = await this.client.send({type: 'connection.check'});
      if (generation !== this.connectionGeneration || this.owner(cfg) !== this.owner() || this.disposed) return;
      if (data?.state !== 'connected' || data.uid !== cfg.uid || typeof data.email !== 'string' || !data.email.trim()) throw Error('invalid_session_response');
      this.view.connection({state: 'connected'});
      this.render();
    } catch (e) {
      if (generation !== this.connectionGeneration || this.owner(cfg) !== this.owner() || this.disposed) return;
      this.view.connection({state: ['unauthorized','backend_login_required'].includes(e.message) ? 'expired' : e.message === 'backend_account_changed' ? 'mismatch' : e.message === 'invalid_session_response' ? 'invalid' : 'unavailable', error: e.message});
      this.render();
    }
  }
  capture(choice) {
    if (this.busy()) return;
    if (!this.form) throw Error('worker_unavailable');
    if (this.historical || this.closed) throw Error('page_read_failed');
    const query = this.view.$('query').value.trim();
    if (!query) throw Error('query_required');
    if (query.length > 200) throw Error('query_too_long');
    if (!this.cfg.uid || this.view.authBlocked) throw Error('backend_login_required');
    if (!/^https?:/.test(this.form.url)) throw Error('unsupported');
    this.actionError = null;
    this.generation++;this.task = null;this.entry = null;this.receiptPending = false;this.uncertainSave = false;this.view.clear();
    this.form = {...this.form, query, match_scope: this.view.$('match-scope').value || 'content', choice, taskId: crypto.randomUUID(), phase: 'prepared', pending_save: false, read_error: null};
    const generation = this.generation, form = {...this.form}, persisted = this.persist();
    const permitted = this.browser.permissions.request({origins: [new URL(form.url).origin + '/*']});
    this.view.controls({reading: true});this.view.status('正在确认权限并提取匹配内容…');
    return Promise.all([persisted, permitted]).then(async ([, allowed]) => {
      if (generation !== this.generation) return;
      if (!allowed) throw Error('permission_denied');
      await this.dispatch(form, generation);
    }).catch(async error => {await this.readFailed(error, generation);throw error;});
  }
  async readFailed(error, generation) {
    if (generation !== this.generation || this.disposed) return;
    // A definitive rejection did not create a draft. Keep its actual reason,
    // rather than polling a nonexistent ID and replacing it with "expired".
    if (!['worker_timeout','worker_unavailable'].includes(error.message) && this.form.taskId && this.form.phase === 'prepared') {
      this.form = {...this.form, taskId: null, phase: 'editing', read_error: error.message};
      await this.persist();
    }
    this.view.controls({reading: false});this.view.status(errorText(error.message), true);
  }
  async dispatch(form = {...this.form}, generation = this.generation) {
    try {
      await this.client.send({type: 'extract.start', version: 2, request_id: form.taskId, tabId: form.tabId, url: form.url, query: form.query, match_scope: form.match_scope || 'content', ...(form.choice ? {choice: form.choice} : {})});
    } catch (error) {await this.readFailed(error, generation);throw error;}
    if (generation !== this.generation) return;
    this.form.phase = 'reading';await this.persist();await this.refresh();
  }
  async checkPage() {
    let tab;try {tab = await this.browser.tabs.get(this.currentTabId);} catch {tab = {id: this.currentTabId};}
    this.currentTab = tab;
    if (this.historical) return;
    this.closed = !tab.url;
    if (tab.url && tab.url !== this.form.url) {
      this.generation++;this.task = null;this.entry = null;this.receiptPending = false;this.uncertainSave = false;
      this.form = {tabId: tab.id, url: tab.url, query: this.view.$('query').value, match_scope: 'content', taskId: null, phase: 'editing'};
      this.view.select('match-scope','content');this.view.restoreBinding(null);this.view.clear();await this.persist();
      this.view.status('原网页地址或视图已变化，请重新提取。', true);
    }
    this.showPage({...tab, url: tab.url || this.form.url});this.render();
  }
  async poll() {
    if (this.polling || this.disposed) return;
    this.polling = true;
    try {await this.checkPage();await this.refresh();if (this.cfg.uid && this.clock() - (this.connectionCheckedAt || 0) > 30000) void this.checkConnection();}
    finally {this.polling = false;}
  }
  async refresh(receipt = false) {
    if (this.refreshing || !this.form || this.disposed) return;
    this.refreshing = true;const generation = this.generation;
    try {
      const cfg = await this.client.send({type: 'config'});
      if (generation !== this.generation) return;
      if (this.owner(cfg) !== this.owner()) {await this.changeOwner(cfg);this.view.status('工作台账号已变化，已切换到该账号的本地记录。');return;}
      if (!cfg.uid || !this.form.taskId) return;
      let task;
      try {task = await this.client.send({type: 'extract.get', id: this.form.taskId});}
      catch (e) {if (e.message === 'draft_not_found' && this.form.phase === 'prepared') return;throw e;}
      if (generation !== this.generation || this.disposed) return;
      this.task = task;if (!this.uncertainSave) this.entry = null;
      if (task.submission || this.uncertainSave) {
        const data = await this.client.send({type: 'status'});
        if (generation !== this.generation || this.disposed) return;
        const requestId = task.submission?.request_id || task.id;
        this.entry = data.entries.find(e => (e.request_id || e.response?.request_id || e.body?.request_id) === requestId) || (this.uncertainSave ? this.entry : null);
        const intent = data.intents?.find(e => e.id === requestId);
        this.receiptPending = Boolean(task.submission && (!this.entry || this.entry.state === 'pending') && intent?.state !== 'failed');
        if (!this.entry && intent?.state === 'failed') this.entry = {state: 'failed', error: intent.error};
      } else this.receiptPending = false;
      this.renderTask(task);
      if (['failed','interrupted'].includes(task.state)) this.view.status(errorText(task.error || 'page_read_failed'), true);
      else if (task.state === 'needs_choice') this.view.status('请确认课程范围，再继续提取。');
      else this.view.status(this.actionError ? errorText(this.actionError) : '', Boolean(this.actionError));
    } finally {this.refreshing = false;}
  }
  async history() {
    const generation = this.generation, {tasks} = await this.client.send({type: 'extract.list'});
    if (generation !== this.generation) return;
    const root = this.view.$('history');root.replaceChildren();
    const states = {queued:'等待提取', running:'正在提取', succeeded:'已提取', failed:'提取失败', interrupted:'读取中断', needs_choice:'待确认课程'};
    for (const t of tasks) {
      const row = this.view.node('div','', 'history-row');row.append(this.view.node('span',t.query || '旧版预览'));
      let domain = '';try {domain = new URL(t.url).hostname;}catch { /* old draft */ }
      row.append(this.view.node('p', `${domain} · ${t.submission ? '已提交 · 可查询结果' : states[t.state] || '旧版只读记录'}`));
      if (t.schema_version === 2) row.append(this.view.button('查看预览', this.guard(() => this.openHistory(t)), 'text-button'));
      row.append(this.view.button('删除本地预览', this.guard(async () => {
        if (!this.view.document.defaultView.confirm('删除这条本地预览？已保存资料和已提交请求会保留。')) return;
        await this.client.send({type: 'extract.delete', id: t.id});
        if (this.form.taskId === t.id) {this.task = null;this.entry = null;this.receiptPending = false;this.form.taskId = null;await this.persist();this.view.clear();this.render();}
        await this.history();
      }), 'text-button'));
      root.append(row);
    }
    if (!tasks.length) root.append(this.view.node('p','没有本地预览记录。','muted'));
  }
  async openHistory(summary) {
    if (this.busy()) return;
    const generation = ++this.generation;
    const stored = await this.forms.loadHistory(this.cfg, summary.id) || await this.forms.load(this.cfg, summary.tabId);
    if (generation !== this.generation) return;
    this.task = null;this.entry = null;this.receiptPending = false;this.historical = true;
    const previous = stored?.taskId === summary.id && stored.url === summary.url ? stored : {};
    this.form = {...previous, tabId: summary.tabId, url: summary.url, query: summary.query, match_scope: summary.match_scope || 'content', taskId: summary.id, phase: 'reading'};
    this.uncertainSave = Boolean(this.form.pending_save);
    if (this.uncertainSave) this.entry = {state:'failed',error:'worker_timeout'};
    this.view.$('query').value = summary.query;this.view.select('match-scope', this.form.match_scope);
    this.view.$('auto-monitor').checked=this.form.auto_monitor !== false;this.view.select('monitor-interval',String(this.form.monitor_interval || 1800));this.view.restoreBinding(this.form.source_binding, this.form.binding_draft);this.view.clear();this.showPage({url: summary.url, title: '历史预览 · ' + summary.query});
    await this.refresh(true);
    this.view.$('history-panel').hidden = true;this.view.$('drafts').setAttribute('aria-expanded','false');
  }
  async returnCurrent() {
    if (this.busy()) return;
    this.generation++;this.task = null;this.entry = null;this.receiptPending = false;
    await this.loadCurrentForm();this.view.clear();this.render();await this.restoreTask();
  }
  async save() {
    if (this.busy() || !this.task || this.task.submission) return;
    const task = this.task, query = this.view.$('query').value.trim(), generation = this.generation;
    if (query !== task.query || (task.intent?.match_scope || task.result?.intent?.match_scope || 'content') !== (this.view.$('match-scope').value || 'content')) throw Error('query_changed');
    if (this.view.authBlocked) throw Error('backend_login_required');
    const monitoring = this.view.$('auto-monitor').checked ? {mode:'resident',interval_s:Number(this.view.$('monitor-interval').value)} : null;
    const binding = task.result?.source === 'generic' && !monitoring ? this.view.binding() : null;
    // Reserve the operation before the first await: rapid clicks must not enqueue twice.
    this.actionError = null;this.saving = true;this.render();
    try {
      try {const tab = await this.browser.tabs.get(this.form.tabId);if (tab.url && tab.url !== this.form.url) throw Error('route_mismatch');}
      catch (e) {if (e.message === 'route_mismatch') throw e;}
      if (generation !== this.generation) return;
      let result;
      try {result = await this.client.send({type: 'extract.save', id: task.id, query, ...(binding ? {source_binding: binding} : {}), ...(monitoring?{monitoring}:{})});}
      catch (e) {
        if (generation === this.generation && ['worker_timeout','worker_unavailable','backend_timeout','backend_unavailable'].includes(e.message)) {
          this.uncertainSave = true;this.form.pending_save = true;this.entry = {state: 'failed', error: e.message};
          await this.persist();
        }
        throw e;
      }
      if (generation !== this.generation) return;
      this.task = {...task, submission: result};this.receiptPending = true;
      await this.refresh(true);
    } finally {this.saving = false;if (generation === this.generation) this.render();}
  }
  render() {if (this.task) this.renderTask(this.task);else this.view.controls({saving: this.saving, reading: false, historical: this.historical, closed: this.closed});}
  renderTask(task) {
    const stale = task.query !== this.view.$('query').value.trim() || (task.intent?.match_scope || task.result?.intent?.match_scope || 'content') !== (this.view.$('match-scope').value || 'content');
    const displayTask = !task.submission && this.uncertainSave ? {...task, submission: {request_id: task.id}} : task;
    this.view.task(displayTask, {stale, monitoring:this.view.$('auto-monitor').checked, saving: this.busy(), onChoice: id => this.guard(() => this.capture(id))()});
    const receipt = this.view.receipt(this.entry, this.cfg, Boolean(task.submission || this.uncertainSave));
    this.view.$('refresh').hidden = !task.submission && !this.uncertainSave;
    if (receipt.state === 'unconfirmed') {
      if (receipt.auth) this.view.connection({state: 'expired', error: this.entry?.error});
      else if (['backend_unavailable','backend_timeout'].includes(receipt.error)) this.view.connection({state: 'unavailable', error: receipt.error});
    }
  }
  showPage(tab) {
    let source;try {source = new SiteRegistry().resolve(tab.url).source;}catch {source = 'restricted';}
    this.view.page({...tab, title: this.closed && !this.historical ? '原网页已关闭（查看已完成预览）' : tab.title || (this.task?.result?.url === tab.url ? this.task?.result?.title : '')}, {source, historical: this.historical, closed: this.closed});
  }
  dispose() {this.disposed = true;this.connectionGeneration++;clearInterval(this.timer);}
}
