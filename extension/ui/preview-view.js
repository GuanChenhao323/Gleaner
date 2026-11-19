import {DomView} from './dom.js';
import {ResultGroups} from './result-groups.js';
import {FIELD_NAMES, errorText} from './errors.js';

/** Compact excerpts and expandable original evidence. Never constructs uploads. */
export class PreviewView extends DomView {
  constructor(document, groups = new ResultGroups()) { super(document); this.groups = groups; this.key = null; }
  clear(message = '输入条件后，结果会出现在这里。') {
    this.key = null; this.$('preview').replaceChildren(this.node('p', message, 'empty-state'));
    this.$('preview-count').textContent = '';
  }
  highlight(text, query) {
    const span = this.node('span'), index = query ? text.toLowerCase().indexOf(query.toLowerCase()) : -1;
    if (index < 0) { span.textContent = text; return span; }
    span.append(this.document.createTextNode(text.slice(0, index)), this.node('mark', text.slice(index, index + query.length)), this.document.createTextNode(text.slice(index + query.length)));
    return span;
  }
  render(task, {stale = false, onChoice, onDetail} = {}) {
    if (!task) { this.clear(); return; }
    const key = task.id ? JSON.stringify([task.id, task.state, task.error, stale, task.result?.observed_at]) : null;
    if (key && key === this.key) return;
    this.key = key;
    const root = this.$('preview'); root.replaceChildren(); this.$('preview-count').textContent = '';
    if (stale) { root.append(this.node('p', '条件或网页已修改，旧结果不可保存。', 'warning')); return; }
    if (task.error) { root.append(this.node('p', errorText(task.error), 'warning')); return; }
    if (['queued', 'running'].includes(task.state)) {
      root.append(this.node('p', task.state === 'queued' ? '等待提取…' : '正在读取匹配片段…', 'empty-state')); return;
    }
    if (!task.result) return;
    const r = task.result, candidates = r.candidates || [], generic = r.source === 'generic';
    this.$('preview-count').textContent = `${candidates.length} ${generic ? '个片段' : '条结果'}`;
    if (task.state === 'needs_choice') {
      root.append(this.node('p', '有多个同名课程，请确认课程范围。'));
      for (const c of r.choices || []) root.append(this.button(`${c.title}${c.context ? ' · ' + c.context : ''}`, () => onChoice(c.id)));
    }
    const outcome = r.outcome?.status || (candidates.length ? 'matched' : r.navigation?.length ? 'navigation_required' : 'no_match');
    if (task.state === 'succeeded' && outcome === 'no_match') root.append(this.node('p', '当前已加载内容匹配 0 条。试试更短的关键词或调整匹配位置；没有回退为整页采集。', 'empty-state'));
    if (outcome === 'navigation_required') root.append(this.node('p', '已定位目标课程，当前页只有入口或缺少匹配正文；请打开课程详情后重新提取。', 'warning'));
    for (const n of r.navigation || []) root.append(this.link(`打开课程：${n.title}`, n.url));
    const count = candidates.filter(c => c.save_allowed).length;
    if(r.save_mode==='timeline_summary') root.append(this.node('p','当前活动摘要将合为一份资料，保留课程、时间原文和详情链接；未读取活动详情或其他分页。','muted'));
    if (candidates.length && !generic && count !== candidates.length) {
      root.append(this.node('p', `可保存 ${count} 条，仅预览 ${candidates.length - count} 条。`, 'muted'));
      if (count !== candidates.length) root.append(this.node('p', r.save_mode==='timeline_summary'?'尚未核对学校账号，请在原站登录后重新提取。':this.groups.previewGuidance(candidates).message, 'muted'));
    }
    const groups = this.groups.arrange(candidates);
    if (!generic && groups.length === 1) this.$('preview-count').textContent = `${candidates.length} 条 · ${groups[0].title}`;
    for (const group of groups) {
      const section = this.node('section'); section.dataset.resultGroup = group.id;
      section.setAttribute('aria-label', group.title);
      if (!generic && groups.length > 1) section.append(this.node('h3', `${group.title}（${group.candidates.length}）`, 'group-title'));
      for (const c of group.candidates) section.append(this.candidate(c, r.intent?.query || task.query || '', r.url, onDetail));
      root.append(section);
    }
    if ((r.warnings || []).length || r.coverage?.regions?.length) {
      const details = this.node('details'); details.append(this.node('summary', '读取范围与限制'));
      for (const warning of r.warnings || []) details.append(this.node('p', warning, 'muted'));
      for (const region of r.coverage?.regions || []) details.append(this.node('p', `${region.title}：${({matched:'已匹配', no_match:'已识别，无匹配', not_ready:'尚未就绪', unsupported:'结构未识别', fields_missing:'部分字段缺失'})[region.status] || region.status}`, 'muted'));
      root.append(details);
    }
  }
  candidate(c, query, pageUrl, onDetail) {
    const card = this.node('article', '', 'result-card'), title = this.node('h3'); title.append(this.highlight(c.raw.title, query));
    card.append(title);
    const type = {web_fragment:'网页片段 · 非完整正文', course_entry:'课程概览 · 仅预览', page_section:'页面区块 · 仅预览', assignment:'作业', timeline_event:c.save_allowed?'活动摘要 · 可保存为资料':'活动摘要 · 仅预览', contact_info:'联系信息 · 仅预览'}[c.record_type];
    if (type && (c.record_type !== 'assignment' || !c.save_allowed)) card.append(this.node('p', type, 'candidate-type'));
    const excerpt = this.node('p', '', 'excerpt'); excerpt.append(this.highlight(Array.from(c.raw.text).slice(0, 240).join(''), query)); card.append(excerpt);
    if(c.record_type==='assignment' && c.raw.fields?.subtype==='assignment_link') {
      card.append(this.node('p','仅作业链接 · 截止时间待补充','muted'));
      if(onDetail && pageUrl && new URL(pageUrl).pathname!=='/mod/assign/view.php')
        card.append(this.button('读取这项作业的详情',()=>onDetail(c)));
      else card.append(this.node('p','当前详情页未识别到说明、日期或提交状态。','muted'));
    }
    const full = this.node('details', '', 'full-fragment'), summary = this.node('summary', '原文');
    const label = () => { summary.textContent = full.open ? '收起' : '原文'; summary.setAttribute('aria-label', `${full.open ? '收起' : '查看'}原文：${c.raw.title}`); };
    label();full.addEventListener('toggle', label);full.append(summary, this.node('pre', c.raw.text));
    const fields = Object.entries(c.raw.fields || {}).filter(([k,v]) => v && k !== 'subtype').map(([k,v]) => `${FIELD_NAMES[k] || k}：${v}`).join('\n');
    if (fields && fields !== c.raw.text) full.append(this.node('pre', fields));
    if (c.presentation) {
      const match = {course_identity:'原生课程范围', activity_title:'活动标题', section_heading:'区块标题', requested_fields:'指定联系字段'}[c.presentation.matched_by];
      full.append(this.node('p', `来源区块：${c.presentation.region} · 匹配依据：${match}`, 'muted'));
      if (c.presentation.course_relation === 'unconfirmed') full.append(this.node('p', '尚无原生归属证明，不会据此绑定课程。', 'muted'));
    }
    const evidence = this.node('details'); evidence.append(this.node('summary', '原文依据'), this.node('pre', (c.evidence || []).map(e => `${e.locator}\n${e.text}`).join('\n')));
    full.append(evidence, this.link('打开原文', c.url)); card.append(full);
    if (c.missing_fields?.length) card.append(this.node('p', `尚未确认：${c.missing_fields.map(k => FIELD_NAMES[k] || k).join('、')}。`, 'warning'));
    if (!c.save_allowed) card.append(this.node('p', errorText(c.save_reason), 'warning'));
    return card;
  }
}
