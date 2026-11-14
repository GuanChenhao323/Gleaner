import {ResultGroups} from './result-groups.js';
import {sourceBinding} from '../extraction/web-payload.js';

const ERRORS={query_required:'请输入想抓取的内容。',query_too_long:'条件请控制在 200 字以内。',unsupported_query:'暂支持课程名、标题关键词及人员联系方式。可写“课程：网络编程；关键词：实验”，复杂时间和语义条件暂不支持。',
  wrong_section:'这个条件与当前页面类型不符，请打开对应网页后重试。',need_login:'请先在学校原站自行登录，再点击抓取。',unsupported:'当前网页尚未适配。',unsupported_dom:'尚未可靠识别此页面结构，未抓取内容。',
  frame_unsupported:'当前内容位于嵌入页面中，请打开独立内容页后重试。',backend_login_required:'请展开连接设置，登录 Campus Radar。',backend_account_changed:'Campus Radar 账号已变化，请重新抓取。',backend_unavailable:'本地后端不可用，提交尚未确认。',backend_timeout:'后端响应超时，可稍后查询同一提交。',
  permission_denied:'缺少当前站点权限，请点击抓取并允许访问。',render_timeout:'页面加载超时，请等待原页内容加载后重试。',page_read_failed:'无法读取原页，页面可能已经关闭。',page_not_ready:'页面内容尚未就绪。',selection_missing:'所需内容已失效，请回原页确认后重试。',
  route_mismatch:'原页地址或视图已改变，请重新打开插件并抓取。',account_mismatch:'学校账号在读取期间变化，请确认后重试。',account_unknown:'无法可靠识别学校账号，当前只能预览。',preview_only:'结果存在不完整内容或身份不足，请打开详情或缩小条件后重试。',
  attachments_only:'当前页只有作业附件名称与链接，未读取附件正文；仅供预览，不作为完整作业保存。',navigation_only:'这是当前页的课程入口／概览，仅供预览。请打开课程或输入“课程名的作业”读取完整事项。',section_preview_only:'这是当前已加载的区块预览，未确认为完整独立事项，暂不保存。',identity_unknown:'原站身份尚未确认，仅供预览。',fields_missing:'部分指定字段未找到，不推测缺失内容。',detail_required:'当前只有摘要／入口，请进入详情后重新抓取。',query_changed:'条件已修改，请重新抓取。',preview_required:'请先完成当前条件的抓取预览。',
  worker_interrupted:'读取被中断，未确认完成，请重新抓取。',worker_timeout:'后台暂未响应，可重新打开插件查询任务，避免重复提交。',worker_unavailable:'扩展后台不可用，请重新加载扩展。',draft_not_found:'预览已经过期或不存在，请重新抓取。',draft_limit:'本地预览已达容量上限，请在任务记录中管理旧草稿。',
  content_too_large:'匹配内容超过安全上限，请缩小范围。',candidate_limit:'匹配数量过多，请缩小条件。',invalid_response:'后端响应异常，未确认保存。',invalid_capture_response:'后端逐项回执异常，未确认保存。',idempotency_conflict:'同一请求的内容发生冲突，请重新抓取。',invalid_selection:'一次仅能保存 1–30 条完整匹配结果，请缩小范围。'};
const FIELD_NAMES={course:'课程',semester:'学期',week:'周次',weekday:'星期',period:'节次',datetime_text:'时间原文',date_text:'日期原文',email:'邮箱',office:'办公室',phone:'电话',role:'职务',department:'部门',published_text:'发布时间原文',valid_until_text:'有效期原文',native_occurrence_id:'课次身份'};
Object.assign(ERRORS,{unsupported_region:'指定区块不存在、未显示或结构尚未识别；未将它当作零匹配，请确认原页已加载。',timeline_preview_only:'这是时间线活动摘要，时间保留原文。请打开原文详情后重新抓取并保存。',contact_preview_only:'这是联系信息预览，不创建作业或待办。'});
Object.assign(ERRORS,{unsupported:'此页面不能注入网页读取脚本，请打开普通 HTTP(S) 网页。',page_too_large:'页面结构过大，未完成读取。请在内容更集中的页面重试。',source_label_required:'请选择公开网页或填写私人来源标签，再保存资料。',specialized_source_required:'这个站点须使用校园专用读取规则。'});
ERRORS.restricted_page='浏览器限制在此页面运行扩展读取脚本，请打开普通网站页面。';
export const errorText=code=>ERRORS[code] || `操作未完成：${code}`;

/** Render only: all workflow decisions are supplied by the controller/service. */
export class CaptureView {
  constructor(document,groups=new ResultGroups()) { this.document=document;this.groups=groups; }
  $(id) { return this.document.getElementById(id); }
  select(id,value) {const options=[...this.$(id).querySelectorAll('option')];for(const option of options)option.selected=false;const chosen=options.find(o=>o.value===value);if(chosen)chosen.selected=true;}
  binding() {const kind=this.$('source-kind').value;return sourceBinding({kind,label:kind==='public'?'公开网页':this.$('source-label').value});}
  restoreBinding(binding) {this.select('source-kind',binding?.kind || '');this.$('source-label').value=binding?.kind==='labeled'?binding.label:'';this.$('source-label-field').hidden=binding?.kind==='public';}
  ready(value) { for(const id of ['query','capture','large','drafts','login','logout'])this.$(id).disabled=!value; }
  node(tag,text,className='') { const n=this.document.createElement(tag);n.textContent=text;n.className=className;return n; }
  link(title,url) { const a=this.node('a',title);a.href=url;a.target='_blank';a.rel='noopener noreferrer';return a; }
  button(title,action) { const b=this.node('button',title);b.type='button';b.onclick=action;return b; }
  status(text,error=false) {this.$('status').textContent=text;this.$('status').className=error?'error':'';}
  config(cfg) {
    this.$('account').textContent=cfg.email?`Campus Radar：${cfg.email}（工作台需同一账号）`:'尚未连接 Campus Radar';
    this.$('connection').open=!cfg.uid;
    this.$('logout').hidden=!cfg.uid;
    this.$('login-fields').hidden=Boolean(cfg.uid);
    if(cfg.server) this.$('server').value=cfg.server;
  }
  page(tab) {this.$('page').textContent=tab?.url?`${tab.title || '当前网页'}\n${tab.url}`:'原网页已关闭；已完成的预览仍可查看。';}
  clear() {this.$('preview').replaceChildren();this.$('save').disabled=true;this.$('save').textContent='保存匹配结果';this.$('source-binding').hidden=true;}
  task(task,{stale=false,saving=false,onChoice}={}) {
    this.clear();if(!task) return;
    const root=this.$('preview');
    if(stale) {root.append(this.node('p','条件已修改，旧结果不可保存。','warning'));return;}
    const labels={queued:'等待抓取',running:'正在按条件定位并提取',failed:'抓取失败',interrupted:'抓取中断',needs_choice:'请确认目标课程',succeeded:'匹配结果'};
    root.append(this.node('h2',labels[task.state] || '旧版只读记录'));
    if(task.error) {root.append(this.node('p',errorText(task.error),'warning'));return;}
    if(!task.result) return;
    const r=task.result, i=r.intent;
    const generic=r.source==='generic';
    this.$('source-binding').hidden=!generic || !r.candidates.length;
    if(task.save_binding)this.restoreBinding(task.save_binding);
    for(const id of ['source-kind','source-label'])this.$(id).disabled=saving || Boolean(task.save_binding);
    let sourceReady=true;
    if(generic) {try {this.binding();}catch {sourceReady=false;}}
    if(i) root.append(this.node('p',`条件：${i.query} · 当前页已加载内容`));
    if(task.state==='needs_choice') for(const c of r.choices || []) root.append(this.button(`${c.title}${c.context?' · '+c.context:''}（课程 ID ${c.id}）`,()=>onChoice(c.id)));
    for(const warning of r.warnings || []) root.append(this.node('p',warning,'muted'));
    if(r.coverage?.regions?.length) {
      const details=this.node('details','');details.append(this.node('summary','识别范围'));
      const states={matched:'已匹配',no_match:'已识别，无匹配',not_ready:'尚未就绪',unsupported:'结构未识别',fields_missing:'部分字段缺失'};
      details.append(this.node('pre',r.coverage.regions.map(region=>`${region.title}：${states[region.status] || region.status}`).join('\n')));
      const c=r.coverage.course_index;
      if(c)details.append(this.node('p',`课程索引 ${c.indexed_courses}；原生链接 ${c.native_links}；边界排除 ${c.excluded_boundary}；隐藏排除 ${c.excluded_visibility}；无标题 ${c.empty_titles}`,'muted'));
      root.append(details);
    }
    for(const n of r.navigation || []) root.append(this.link(`打开课程：${n.title}`,n.url));
    const outcome=r.outcome?.status || (r.candidates.length?'matched':r.navigation?.length?'navigation_required':'no_match');
    if(task.state==='succeeded' && outcome==='no_match') root.append(this.node('p','页面结构已识别，当前条件匹配 0 条；没有保存，也没有回退为整页采集。','warning'));
    if(outcome==='navigation_required') root.append(this.node('p','已定位目标课程，当前页只有入口或缺少匹配正文；请打开上方课程链接后重新抓取。','warning'));
    const guidance=this.groups.previewGuidance(r.candidates);
    if(r.candidates.length) {const count=r.candidates.filter(c=>c.save_allowed).length;root.append(this.node('p',generic?`匹配 ${r.candidates.length} 个片段；整组保存为 1 份网页资料。${!sourceReady?'请在下方选择来源身份。':''}`:`读取 ${r.candidates.length} 条：可保存 ${count} 条，仅预览 ${r.candidates.length-count} 条。`));if(count!==r.candidates.length)root.append(this.node('p',guidance.message,'muted'));}
    for(const group of this.groups.arrange(r.candidates)) {
      const section=this.node('section','');section.dataset.resultGroup=group.id;
      section.append(this.node('h3',`${group.title}（${group.candidates.length}）`));
      for(const c of group.candidates) {
        const card=this.node('article','');card.append(this.node('h3',c.raw.title));
        const type={course_entry:'课程概览 · 仅预览',page_section:'页面区块 · 仅预览',assignment:'作业',timeline_event:'活动摘要 · 仅预览',contact_info:'联系信息 · 仅预览'}[c.record_type];if(type)card.append(this.node('p',type,'muted'));
        if(c.record_type==='web_fragment')card.append(this.node('p','网页片段 · 非完整正文 · 字面条件命中','badge'));
        if(c.presentation) {
          const match={course_identity:'原生课程范围',activity_title:'活动标题',section_heading:'区块标题',requested_fields:'指定联系字段'}[c.presentation.matched_by];
          card.append(this.node('p',`来源区块：${c.presentation.region} · 匹配依据：${match}`,'muted'));
          if(c.presentation.course_relation==='unconfirmed')card.append(this.node('p','课程名称仅为原文上下文，尚无原生归属证明；不会据此绑定课程。','muted'));
        }
        card.append(this.node('pre',c.raw.text));
        const fields=Object.entries(c.raw.fields).filter(([k,v])=>v && k!=='subtype').map(([k,v])=>`${FIELD_NAMES[k] || k}：${v}`).join('\n');
        if(fields && fields!==c.raw.text) card.append(this.node('pre',fields));
        if(c.missing_fields?.length) card.append(this.node('p',`尚未确认：${c.missing_fields.map(k=>FIELD_NAMES[k] || k).join('、')}。`,'warning'));
        if(!c.save_allowed) card.append(this.node('p',errorText(c.save_reason),'warning'));
        card.append(this.link('打开原文',c.url));
        const details=this.node('details','');details.append(this.node('summary','原文依据'),this.node('pre',c.evidence.map(e=>`${e.locator}\n${e.text}`).join('\n')));card.append(details);section.append(card);
      }
      root.append(section);
    }
    const total=r.candidates.map((c,i)=>`【片段 ${i+1}】${c.raw.title}\n${c.raw.text}`).join('\n\n').length;
    const ready=task.schema_version===2 && task.state==='succeeded' && r.candidates.length>0 && r.candidates.length<=30 && r.candidates.every(c=>c.save_allowed) && !task.submission && sourceReady && (!generic || total<=20000);
    this.$('save').textContent=task.submission?'已提交，请查看结果':r.candidates.some(c=>!c.save_allowed)?guidance.button:`保存匹配结果${r.candidates.length?`（${r.candidates.length}）`:''}`;
    if(generic && !task.submission)this.$('save').textContent=`保存为一份网页资料（${r.candidates.length} 个片段）`;
    this.$('save').disabled=!ready || saving;
    if(r.candidates.length>30) root.append(this.node('p',errorText('invalid_selection'),'warning'));
    if(generic && total>20000)root.append(this.node('p','整组资料超过 20000 字，请缩小条件后重新提取；不会截断保存。','warning'));
  }
  receipt(entry,cfg) {
    const root=this.$('results');root.replaceChildren();if(!entry) return;
    if(entry.state!=='confirmed') {root.append(this.node('p',`提交${entry.state==='auth_required'?'需要重新登录':entry.state==='rejected'?'被拒绝':'尚未确认'}。${entry.error?errorText(entry.error):'可稍后查询同一请求。'}`,'warning'));return;}
    const rows=entry.response.results, count=status=>rows.filter(r=>status.includes(r.status)).length;
    root.append(this.node('p',`后端已确认：新增 ${count(['new'])}，更新 ${count(['changed'])}，已有 ${count(['unchanged'])}，失败 ${count(['failed'])}。`));
    if(rows[0]?.capture_id)root.append(this.node('p',`已确认 ${rows[0].fragment_count} 个片段，资料版本 ${rows[0].version}。仅保存快照，未启用监测。`,'muted'));
    for(const r of rows) if(r.status==='failed') root.append(this.node('p',`${r.candidate_id}：${errorText(r.error)}`,'warning'));
    else root.append(this.link(`在工作台查看记录 ${r.item_id}`,`${cfg.server}/#/item/${r.item_id}`));
  }
}
