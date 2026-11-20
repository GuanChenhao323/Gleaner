import {t} from './i18n.js';
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
    const failed = count('failed'), generic = Boolean(rows[0].capture_id), timeline=entry.response.capture_type==='timeline_summary';
    let title = generic ? count('new') ? t('已保存为 1 份网页资料') : count('changed') ? t`已更新这份网页资料 · v${rows[0].version}` : t('资料已存在 · 内容无变化')
      : t`后端已确认：新增 ${count('new')}，更新 ${count('changed')}，已有 ${count('unchanged')}，失败 ${failed}。`;
    if (failed) title = t`后端已返回结果：成功 ${rows.length - failed}，失败 ${failed}。`;
    if(timeline && !failed) title = count('new') ? t('已保存为 1 份活动摘要资料') : count('changed') ? t`已更新活动摘要资料 · v${rows[0].version}` : t('资料已存在 · 内容无变化');
    const reading=Number.isInteger(entry.response.reading_source_id)&&entry.response.reading_source_id>0;
    if(entry.response.monitoring?.state==='starting')return {state:failed?'partial':'success',title,rows,generic,detail:t('资料已保存 · 自动监测启动中。此标签页将自动刷新，实际检查结果及下次时间请在工作台查看。')};
    return {state: failed ? 'partial' : 'success', title, rows, generic,
      detail: reading ? t`${generic?`${rows[0].fragment_count} ${timeline?t('条活动摘要'):t('个片段')} · v${rows[0].version} · `:''}原条件与来源已关联，可在工作台查看检查状态。` : generic ? t`${rows[0].fragment_count} 个片段 · 资料版本 ${rows[0].version} · 未启用监测` : t('保存不会自动启用监测。')};
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
    this.$('receipt-settings').hidden = model.state !== 'unconfirmed' || model.rejected;
    this.$('receipt-settings').textContent = model.auth ? t('重新登录工作台') : t('检查连接');
    this.$('continue').hidden = !['success', 'partial'].includes(model.state) && !model.rejected;
    this.$('continue').textContent = model.rejected?t('重新提取'):t('继续提取');
    this.$('workbench').hidden = !['success', 'partial'].includes(model.state) && model.error!=='source_deleted';
    this.$('workbench').textContent = model.error==='source_deleted'?t('管理已删除来源'):t('在工作台查看');
    if (model.state === 'none') return model;
    if (model.state === 'pending') { root.append(this.node('p', t('正在保存，等待后端确认…'), 'muted')); return model; }
    if (model.state === 'unconfirmed') {
      root.append(this.node('p', model.auth ? t('登录已失效，保存尚未确认。') : model.rejected ? t('提交被拒绝，资料没有确认保存。') : t('保存尚未确认，预览和原请求已保留。'), 'warning'));
      if (model.error) root.append(this.node('p', this.errorText(model.error), 'muted'));
      return model;
    }
    root.append(this.node('p', model.title, model.state === 'success' ? 'success' : 'warning'), this.node('p', model.detail, 'muted'));
    const details = this.node('details'); details.append(this.node('summary', t('查看逐项结果')));
    for (const row of model.rows) {
      if (row.status === 'failed') details.append(this.node('p', `${row.candidate_id}：${this.errorText(row.error)}`, 'warning'));
      else details.append(this.link(t`在工作台查看记录 ${row.item_id}`, `${cfg.server}/#/item/${row.item_id}`));
    }
    root.append(details); return model;
  }
}
