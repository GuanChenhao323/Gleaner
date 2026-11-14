import {DomView} from './dom.js';

/** Normalize confirmed receipts separately from task/read state. */
export class ReceiptPresenter {
  present(entry, submitted = false) {
    if (!entry) return {state: submitted ? 'pending' : 'none'};
    if (entry.state !== 'confirmed') return {state: entry.state === 'pending' && !entry.error ? 'pending' : 'unconfirmed',
      error: entry.error, auth: entry.state === 'auth_required', rejected: entry.state === 'rejected'};
    const rows = entry.response?.results;
    if (!Array.isArray(rows) || !rows.length || rows.some(row => !['new', 'changed', 'unchanged', 'failed'].includes(row.status) ||
      (row.status === 'failed' ? typeof row.error !== 'string' : !Number.isInteger(row.item_id) || row.item_id <= 0)))
      return {state: 'unconfirmed', error: 'invalid_capture_response'};
    const count = status => rows.filter(row => row.status === status).length;
    const failed = count('failed'), generic = Boolean(rows[0].capture_id);
    let title = generic ? count('new') ? '已保存为 1 份网页资料' : count('changed') ? `已更新这份网页资料 · v${rows[0].version}` : '资料已存在 · 内容无变化'
      : `后端已确认：新增 ${count('new')}，更新 ${count('changed')}，已有 ${count('unchanged')}，失败 ${failed}。`;
    if (failed) title = `后端已返回结果：成功 ${rows.length - failed}，失败 ${failed}。`;
    return {state: failed ? 'partial' : 'success', title, rows, generic,
      detail: generic ? `${rows[0].fragment_count} 个片段 · 资料版本 ${rows[0].version} · 未启用监测` : '保存不会自动启用监测。'};
  }
}

export class ReceiptView extends DomView {
  constructor(document, errorText, presenter = new ReceiptPresenter()) { super(document); this.errorText = errorText; this.presenter = presenter; }
  render(entry, cfg, submitted = false) {
    const key = JSON.stringify([entry?.state, entry?.error, entry?.response, cfg.server, submitted]);
    if (key === this.key) return this.model;
    this.key = key;
    const model = this.presenter.present(entry, submitted), root = this.$('results');
    this.model = model;
    root.replaceChildren(); root.hidden = model.state === 'none';
    this.$('retry').hidden = model.state !== 'unconfirmed' || Boolean(model.rejected);
    this.$('receipt-settings').hidden = model.state !== 'unconfirmed';
    this.$('receipt-settings').textContent = model.auth ? '重新登录工作台' : '检查连接';
    this.$('continue').hidden = !['success', 'partial'].includes(model.state);
    this.$('workbench').hidden = !['success', 'partial'].includes(model.state);
    if (model.state === 'none') return model;
    if (model.state === 'pending') { root.append(this.node('p', '正在保存，等待后端确认…', 'muted')); return model; }
    if (model.state === 'unconfirmed') {
      root.append(this.node('p', model.auth ? '登录已失效，保存尚未确认。' : model.rejected ? '提交被拒绝，资料没有确认保存。' : '保存尚未确认，预览和原请求已保留。', 'warning'));
      if (model.error) root.append(this.node('p', this.errorText(model.error), 'muted'));
      return model;
    }
    root.append(this.node('p', model.title, model.state === 'success' ? 'success' : 'warning'), this.node('p', model.detail, 'muted'));
    const details = this.node('details'); details.append(this.node('summary', '查看逐项结果'));
    for (const row of model.rows) {
      if (row.status === 'failed') details.append(this.node('p', `${row.candidate_id}：${this.errorText(row.error)}`, 'warning'));
      else details.append(this.link(`在工作台查看记录 ${row.item_id}`, `${cfg.server}/#/item/${row.item_id}`));
    }
    root.append(details); return model;
  }
}
