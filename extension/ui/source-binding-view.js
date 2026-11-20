import {t} from './i18n.js';
import {DomView} from './dom.js';
import {sourceBinding} from '../extraction/web-payload.js';

/** Owns the source declaration editor; no website account is inferred here. */
export class SourceBindingView extends DomView {
  constructor(document) {
    super(document); this.value = null; this.editing = false; this.locked = false;
  }
  restore(value, draft) {
    try { this.value = sourceBinding(value); } catch { this.value = null; }
    const next = this.value || draft || {kind: '', label: ''};
    this.select('source-kind', next.kind || '');
    this.$('source-label').value = next.kind === 'labeled' ? next.label || '' : '';
    this.editing = !this.value && next.kind === 'labeled';
  }
  choose() {
    if (this.locked) return;
    const kind = this.$('source-kind').value;
    this.value = kind === 'public' ? {kind, label: '公开网页'} : null;
    this.$('source-label').value = '';
    this.editing = kind === 'labeled';
  }
  confirm() {
    if (this.locked) return;
    this.value = sourceBinding({kind: this.$('source-kind').value, label: this.$('source-label').value});
    this.editing = false;
  }
  setIdentity(identity) {this.value = sourceBinding({...this.value, identity});}
  change() { if (!this.locked) this.restore(null); }
  get() { return sourceBinding(this.value); }
  ready() { try { const value=this.get(); return !(this.requiresLogin && value.kind==='public'); } catch { return false; } }
  state() {
    return {source_binding: this.value,
      binding_draft: this.value ? null : {kind: this.$('source-kind').value || '', label: this.$('source-label').value}};
  }
  render({visible = false, locked = false} = {}) {
    this.locked = locked;
    this.$('source-binding').hidden = !visible;
    const committed = Boolean(this.value);
    this.$('source-kind').querySelector('[value="public"]').disabled = Boolean(this.requiresLogin);
    this.$('source-kind').hidden = committed;
    this.$('binding-value').hidden = !committed;
    this.$('binding-value').textContent = !this.value ? '' : this.value.kind === 'public' ? t('无需登录（用户声明）') : t`需要登录 · ${this.value.label}`;
    this.$('change-binding').hidden = !committed;
    this.$('source-label-field').hidden = !this.editing;
    for (const id of ['source-kind', 'source-label', 'change-binding']) this.$(id).disabled = locked;
    this.$('account-verification').hidden = !visible || this.value?.kind !== 'labeled';
    this.$('account-status').textContent = this.value?.identity ? t`来源账号：${this.value.identity.display} · 已核对。后台能力需在工作台测试。` : t('来源账号未核对；可保存资料，暂不能后台检查。请先让原网页显示当前账号控件；不要输入邮件正文中的邮箱。');
    this.$('verify-account').disabled = locked || !committed;
    this.$('confirm-binding').disabled = locked || !this.$('source-label').value.trim();
  }
}
