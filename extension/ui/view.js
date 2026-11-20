import {t} from './i18n.js';
import {LoginRequirementPolicy} from '../identity/login-requirement.js';
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
    this.$('auto-monitor').disabled = saving || Boolean(this.submitted);
    this.$('monitor-interval').disabled = saving || Boolean(this.submitted) || !this.$('auto-monitor').checked;
    this.$('monitor-explanation').hidden = !this.$('auto-monitor').checked;
    this.$('query').disabled = !this.initialized || saving || historical;
    this.$('clear-query').disabled = !this.initialized || saving || historical;
    this.$('capture').disabled = !this.initialized || saving || reading || historical || closed || this.restricted || this.authBlocked || !this.cfg?.uid || !this.$('query').value.trim();
    this.$('capture').textContent = reading ? t('提取中…') : t('提取');
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
    this.cfg = cfg; this.$('account').textContent = cfg.email || t('请先登录工作台');
    this.$('connection').open = !cfg.uid;
    this.$('login-fields').hidden = Boolean(cfg.uid);
    this.$('email').value = cfg.email || '';
    this.$('password').value = '';
    this.$('login').textContent = cfg.uid ? t('切换连接或账号') : t('登录工作台');
    this.$('logout').hidden = !cfg.uid;
    if (cfg.server) this.$('server').value = cfg.server;
    this.connection({state: cfg.uid ? 'checking' : 'anonymous'});
  }
  connection({state, error} = {}) {
    this.authBlocked = ['anonymous', 'expired', 'mismatch'].includes(state);
    const labels = {checking:t('正在检查连接'), connected:t('工作台已连接'), anonymous:t('工作台未登录'), expired:t('工作台登录已失效'), mismatch:t('工作台账号已变化'), unavailable:t('工作台暂不可用'), invalid:t('工作台响应异常')};
    this.$('connection-status').textContent = labels[state] || t('连接待检查');
    this.$('connection-dot').dataset.state = state;
    if (['expired','anonymous','mismatch'].includes(state)) {
      this.$('connection').open = true;this.$('login-fields').hidden = false;
      this.$('login').textContent = t('登录工作台');
    }
    this.$('connection-error').textContent = error ? errorText(error) : '';
    this.$('connection-error').hidden = !error;
    this.controls();
  }
  page(tab, {source = 'generic', historical = false, closed = false} = {}) {
    this.historical = historical; this.closed = closed; this.restricted = source === 'restricted'; this.specialized = !['generic','restricted'].includes(source);
    let domain = ''; try { domain = new URL(tab.url).hostname; } catch { /* restricted */ }
    this.$('page').textContent = tab.title || (closed ? t('原网页已关闭（查看已完成预览）') : t('当前网页'));
    this.$('page-domain').textContent = domain || t('页面地址不可读取');
    this.$('page-url').textContent = tab.url || t('原网页已关闭');
    this.$('source-mode').textContent = historical ? t('历史预览') : closed ? t('原页已关闭') : this.restricted ? t('页面受限') : t('当前网页');
    this.$('return-current').hidden = !historical;
    this.$('continue').textContent = historical ? t('返回当前网页') : t('继续提取');
    this.controls();
  }
  binding() { return this.source.get(); }
  restoreBinding(value, draft) { this.source.restore(value, draft); }
  clear() {
    this.submitted=false;this.$('monitor-options').hidden=false;
    this.preview.clear(); this.$('save').disabled = true; this.$('save').hidden = true;
    this.$('refresh').hidden = true;
    this.source.render(); this.$('save-hint').textContent = t('预览确认后再保存，不会自动采集整页。');
    this.receipt(null, this.cfg || {});
  }
  task(task, options = {}) {
    this.submitted=Boolean(task?.submission);
    this.preview.render(task, options);
    if (task?.save_binding) this.source.restore(task.save_binding);
    this.source.requiresLogin = Boolean(task?.url && new LoginRequirementPolicy().requiresLogin(task.url, task.result?.account));
    const p = this.policy.evaluate(task, {...options, bindingReady: this.source.ready()});
    const reading = ['queued','running'].includes(task?.state), submitted = Boolean(task?.submission);
    this.source.render({visible: p.bindingVisible && !submitted, locked: Boolean(task?.save_binding) || options.saving});
    this.$('save').hidden = !p.count || !p.valid || submitted;
    this.$('save').disabled = !p.canSave || this.authBlocked;
    this.$('monitor-options').hidden = submitted;
    this.$('save').textContent = options.monitoring ? t`保存并开启定期监测` : p.timeline ? t`保存为一份活动摘要（${p.count} 条）` : p.generic ? t('保存为一份网页资料') : t`保存匹配结果（${p.count}）`;
    if(p.canSave && task.result?.candidates.every(c=>c.raw.fields?.subtype==='assignment_link'))
      this.$('save').textContent=options.monitoring?t('保存作业链接并监测'):t('保存作业链接');
    if (p.count && !task.result.candidates.every(c => c.save_allowed)) this.$('save').textContent = this.preview.groups.previewGuidance(task.result.candidates).button;
    if(p.timeline && task.result.candidates.some(c=>c.save_reason==='account_unknown'))this.$('save').textContent=t('请登录原学校账号后重新提取');
    this.$('save-hint').textContent = p.oversize ? t('匹配内容超过保存范围，请缩小条件；不会截断保存。')
      : submitted ? t('已提交原预览，正在核对保存结果。')
      : options.monitoring && p.count ? t('先保存资料，自动刷新验证后启动；首次检查失败会显示原因，已有资料保留。')
      : p.count ? p.timeline ? t('仅保存当前已加载的活动摘要及详情链接，不含作业完整正文；来源检查在工作台设置。') : p.generic ? t`${p.count} 个网页片段合为一份资料，非完整文章或邮件；来源检查在工作台设置。` : t('仅保存完整且身份明确的匹配事项；不启用监测。')
      : t('预览确认后再保存，不会自动采集整页。');
    this.controls({saving: Boolean(options.saving), reading});
    return p;
  }
  receipt(entry, cfg, submitted = false) {
    const model = this.receipts.render(entry, cfg, submitted);
    if (model.state !== 'none') this.$('save').hidden = true;
    if (model.state === 'pending') this.$('save-hint').textContent = t('提交已持久保留，可关闭弹窗，稍后查看结果。');
    if (model.state === 'success') this.$('save-hint').textContent = '';
    return model;
  }
}
