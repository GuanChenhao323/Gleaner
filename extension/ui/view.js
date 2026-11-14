import {DomView} from './dom.js';
import {PanelPolicy} from './panel-policy.js';
import {PreviewView} from './preview-view.js';
import {SourceBindingView} from './source-binding-view.js';
import {ReceiptView} from './receipt-view.js';
import {errorText} from './errors.js';
export {errorText} from './errors.js';

/** Composition root for renderers; browser and network operations live elsewhere. */
export class CaptureView extends DomView {
  constructor(document, {preview, binding, receipts, policy} = {}) {
    super(document);
    this.preview = preview || new PreviewView(document);
    this.source = binding || new SourceBindingView(document);
    this.receipts = receipts || new ReceiptView(document, errorText);
    this.policy = policy || new PanelPolicy();
    this.initialized = false; this.busy = false; this.reading = false; this.authBlocked = false;
  }
  ready(value) { this.initialized = value; this.controls(); }
  controls({saving = this.busy, reading = this.reading, historical = this.historical, closed = this.closed} = {}) {
    Object.assign(this, {busy: saving, reading, historical, closed});
    this.$('query').disabled = !this.initialized || saving || historical;
    this.$('clear-query').disabled = !this.initialized || saving || historical;
    this.$('capture').disabled = !this.initialized || saving || reading || historical || closed || this.restricted || this.authBlocked || !this.cfg?.uid || !this.$('query').value.trim();
    this.$('capture').textContent = reading ? '提取中…' : '提取';
    this.$('capture').classList.toggle('loading', reading);
    this.$('match-scope').disabled = saving || this.specialized;
    for (const b of this.document.querySelectorAll('[data-scope]')) {
      b.disabled = saving || historical; b.setAttribute('aria-pressed', String(b.dataset.scope === (this.$('match-scope').value || 'content')));
    }
    this.$('scope-options').hidden = Boolean(this.specialized);
    this.$('special-scope').hidden = !this.specialized;
    for (const id of ['login','logout','drafts','return-current']) this.$(id).disabled = !this.initialized || saving;
    if (this.authBlocked || saving) this.$('save').disabled = true;
  }
  status(text, error = false) {
    this.$('status').textContent = text; this.$('status').hidden = !text;
    this.$('status').className = error ? 'warning' : 'muted';
  }
  config(cfg) {
    this.cfg = cfg; this.$('account').textContent = cfg.email || '请先登录工作台';
    this.$('connection').open = !cfg.uid;
    this.$('login-fields').hidden = Boolean(cfg.uid);
    this.$('email').value = cfg.email || '';
    this.$('password').value = '';
    this.$('login').textContent = cfg.uid ? '切换连接或账号' : '登录工作台';
    this.$('logout').hidden = !cfg.uid;
    if (cfg.server) this.$('server').value = cfg.server;
    this.connection({state: cfg.uid ? 'checking' : 'anonymous'});
  }
  connection({state, error} = {}) {
    this.authBlocked = ['anonymous', 'expired', 'mismatch'].includes(state);
    const labels = {checking:'正在检查连接', connected:'工作台已连接', anonymous:'工作台未登录', expired:'工作台登录已失效', mismatch:'工作台账号已变化', unavailable:'工作台暂不可用', invalid:'工作台响应异常'};
    this.$('connection-status').textContent = labels[state] || '连接待检查';
    this.$('connection-dot').dataset.state = state;
    if (['expired','anonymous','mismatch'].includes(state)) {
      this.$('connection').open = true;this.$('login-fields').hidden = false;
      this.$('login').textContent = '登录工作台';
    }
    this.$('connection-error').textContent = error ? errorText(error) : '';
    this.$('connection-error').hidden = !error;
    this.controls();
  }
  page(tab, {source = 'generic', historical = false, closed = false} = {}) {
    this.historical = historical; this.closed = closed; this.restricted = source === 'restricted'; this.specialized = !['generic','restricted'].includes(source);
    let domain = ''; try { domain = new URL(tab.url).hostname; } catch { /* restricted */ }
    this.$('page').textContent = tab.title || (closed ? '原网页已关闭（查看已完成预览）' : '当前网页');
    this.$('page-domain').textContent = domain || '页面地址不可读取';
    this.$('page-url').textContent = tab.url || '原网页已关闭';
    this.$('source-mode').textContent = historical ? '历史预览' : closed ? '原页已关闭' : this.restricted ? '页面受限' : '当前网页';
    this.$('return-current').hidden = !historical;
    this.$('continue').textContent = historical ? '返回当前网页' : '继续提取';
    this.controls();
  }
  binding() { return this.source.get(); }
  restoreBinding(value, draft) { this.source.restore(value, draft); }
  clear() {
    this.preview.clear(); this.$('save').disabled = true; this.$('save').hidden = true;
    this.$('refresh').hidden = true;
    this.source.render(); this.$('save-hint').textContent = '预览确认后再保存，不会自动采集整页。';
    this.receipt(null, this.cfg || {});
  }
  task(task, options = {}) {
    this.preview.render(task, options);
    if (task?.save_binding) this.source.restore(task.save_binding);
    const p = this.policy.evaluate(task, {...options, bindingReady: this.source.ready()});
    const reading = ['queued','running'].includes(task?.state), submitted = Boolean(task?.submission);
    this.source.render({visible: p.bindingVisible && !submitted, locked: Boolean(task?.save_binding) || options.saving});
    this.$('save').hidden = !p.count || !p.valid || submitted;
    this.$('save').disabled = !p.canSave || this.authBlocked;
    this.$('save').textContent = p.generic ? '保存为一份网页资料' : `保存匹配结果（${p.count}）`;
    if (p.count && !task.result.candidates.every(c => c.save_allowed)) this.$('save').textContent = this.preview.groups.previewGuidance(task.result.candidates).button;
    this.$('save-hint').textContent = p.oversize ? '匹配内容超过保存范围，请缩小条件；不会截断保存。'
      : submitted ? '已提交原预览，正在核对保存结果。'
      : p.count ? p.generic ? `${p.count} 个网页片段合为一份资料，非完整文章或邮件；不启用监测。` : '仅保存完整且身份明确的匹配事项；不启用监测。'
      : '预览确认后再保存，不会自动采集整页。';
    this.controls({saving: Boolean(options.saving), reading});
    return p;
  }
  receipt(entry, cfg, submitted = false) {
    const model = this.receipts.render(entry, cfg, submitted);
    if (model.state !== 'none') this.$('save').hidden = true;
    if (model.state === 'pending') this.$('save-hint').textContent = '提交已持久保留，可关闭弹窗，稍后查看结果。';
    if (model.state === 'success') this.$('save-hint').textContent = '';
    return model;
  }
}
