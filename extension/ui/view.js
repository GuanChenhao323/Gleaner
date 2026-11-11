const ERRORS={query_required:'请输入想抓取的内容。',query_too_long:'条件请控制在 200 字以内。',unsupported_query:'暂支持课程名、标题关键词及人员联系方式。可写“课程：网络编程；关键词：实验”，复杂时间和语义条件暂不支持。',
  wrong_section:'这个条件与当前页面类型不符，请打开对应网页后重试。',need_login:'请先在学校原站自行登录，再点击抓取。',unsupported:'当前网页尚未适配。',unsupported_dom:'尚未可靠识别此页面结构，未抓取内容。',
  frame_unsupported:'当前内容位于嵌入页面中，请打开独立内容页后重试。',backend_login_required:'请展开连接设置，登录 Campus Radar。',backend_account_changed:'Campus Radar 账号已变化，请重新抓取。',backend_unavailable:'本地后端不可用，提交尚未确认。',backend_timeout:'后端响应超时，可稍后查询同一提交。',
  permission_denied:'缺少当前站点权限，请点击抓取并允许访问。',render_timeout:'页面加载超时，请等待原页内容加载后重试。',page_read_failed:'无法读取原页，页面可能已经关闭。',page_not_ready:'页面内容尚未就绪。',selection_missing:'所需内容已失效，请回原页确认后重试。',
  route_mismatch:'原页地址或视图已改变，请重新打开插件并抓取。',account_mismatch:'学校账号在读取期间变化，请确认后重试。',account_unknown:'无法可靠识别学校账号，当前只能预览。',preview_only:'结果存在不完整内容或身份不足，请打开详情或缩小条件后重试。',
  identity_unknown:'原站身份尚未确认，仅供预览。',fields_missing:'部分指定字段未找到，不推测缺失内容。',detail_required:'当前只有摘要／入口，请进入详情后重新抓取。',query_changed:'条件已修改，请重新抓取。',preview_required:'请先完成当前条件的抓取预览。',
  worker_interrupted:'读取被中断，未确认完成，请重新抓取。',worker_timeout:'后台暂未响应，可重新打开插件查询任务，避免重复提交。',worker_unavailable:'扩展后台不可用，请重新加载扩展。',draft_not_found:'预览已经过期或不存在，请重新抓取。',draft_limit:'本地预览已达容量上限，请在任务记录中管理旧草稿。',
  content_too_large:'匹配内容超过安全上限，请缩小范围。',candidate_limit:'匹配数量过多，请缩小条件。',invalid_response:'后端响应异常，未确认保存。',invalid_capture_response:'后端逐项回执异常，未确认保存。',idempotency_conflict:'同一请求的内容发生冲突，请重新抓取。',invalid_selection:'一次仅能保存 1–30 条完整匹配结果，请缩小范围。'};
const FIELD_NAMES={course:'课程',semester:'学期',week:'周次',weekday:'星期',period:'节次',datetime_text:'时间原文',date_text:'日期原文',email:'邮箱',office:'办公室',phone:'电话',role:'职务',department:'部门',published_text:'发布时间原文',valid_until_text:'有效期原文',native_occurrence_id:'课次身份'};
export const errorText=code=>ERRORS[code] || `操作未完成：${code}`;

/** Render only: all workflow decisions are supplied by the controller/service. */
export class CaptureView {
  constructor(document) { this.document=document; }
  $(id) { return this.document.getElementById(id); }
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
  clear() {this.$('preview').replaceChildren();this.$('save').disabled=true;this.$('save').textContent='保存匹配结果';}
  task(task,{stale=false,saving=false,onChoice}={}) {
    this.clear();if(!task) return;
    const root=this.$('preview');
    if(stale) {root.append(this.node('p','条件已修改，旧结果不可保存。','warning'));return;}
    const labels={queued:'等待抓取',running:'正在按条件定位并提取',failed:'抓取失败',interrupted:'抓取中断',needs_choice:'请确认目标课程',succeeded:'匹配结果'};
    root.append(this.node('h2',labels[task.state] || '旧版只读记录'));
    if(task.error) {root.append(this.node('p',errorText(task.error),'warning'));return;}
    if(!task.result) return;
    const r=task.result, i=r.intent;
    if(i) root.append(this.node('p',`条件：${i.query} · 当前页已加载内容`));
    if(task.state==='needs_choice') for(const c of r.choices || []) root.append(this.button(`${c.title}${c.context?' · '+c.context:''}（课程 ID ${c.id}）`,()=>onChoice(c.id)));
    for(const warning of r.warnings || []) root.append(this.node('p',warning,'muted'));
    for(const n of r.navigation || []) root.append(this.link(`打开课程：${n.title}`,n.url));
    if(task.state==='succeeded' && !r.candidates.length) root.append(this.node('p','当前条件匹配 0 条；没有保存，也没有回退为整页采集。','warning'));
    if(r.candidates.length) root.append(this.node('p',`匹配 ${r.candidates.length} 条。核对后一次保存，无需逐条勾选。`));
    for(const c of r.candidates) {
      const card=this.node('article','');card.append(this.node('h3',c.raw.title),this.node('pre',c.raw.text));
      const fields=Object.entries(c.raw.fields).filter(([k,v])=>v && k!=='subtype').map(([k,v])=>`${FIELD_NAMES[k] || k}：${v}`).join('\n');
      if(fields) card.append(this.node('pre',fields));
      if(c.missing_fields?.length) card.append(this.node('p',`尚未确认：${c.missing_fields.map(k=>FIELD_NAMES[k] || k).join('、')}。`,'warning'));
      if(!c.save_allowed) card.append(this.node('p',errorText(c.save_reason),'warning'));
      card.append(this.link('打开原文',c.url));
      const details=this.node('details','');details.append(this.node('summary','原文依据'),this.node('pre',c.evidence.map(e=>`${e.locator}\n${e.text}`).join('\n')));card.append(details);root.append(card);
    }
    const ready=task.schema_version===2 && task.state==='succeeded' && r.candidates.length>0 && r.candidates.length<=30 && r.candidates.every(c=>c.save_allowed) && !task.submission;
    this.$('save').textContent=task.submission?'已提交，请查看结果':`保存匹配结果${r.candidates.length?`（${r.candidates.length}）`:''}`;
    this.$('save').disabled=!ready || saving;
    if(r.candidates.length>30) root.append(this.node('p',errorText('invalid_selection'),'warning'));
  }
  receipt(entry,cfg) {
    const root=this.$('results');root.replaceChildren();if(!entry) return;
    if(entry.state!=='confirmed') {root.append(this.node('p',`提交${entry.state==='auth_required'?'需要重新登录':entry.state==='rejected'?'被拒绝':'尚未确认'}。${entry.error?errorText(entry.error):'可稍后查询同一请求。'}`,'warning'));return;}
    const rows=entry.response.results, count=status=>rows.filter(r=>status.includes(r.status)).length;
    root.append(this.node('p',`后端已确认：新增 ${count(['new'])}，更新 ${count(['changed'])}，已有 ${count(['unchanged'])}，失败 ${count(['failed'])}。`));
    for(const r of rows) if(r.status==='failed') root.append(this.node('p',`${r.candidate_id}：${errorText(r.error)}`,'warning'));
    else root.append(this.link(`在工作台查看记录 ${r.item_id}`,`${cfg.server}/#/item/${r.item_id}`));
  }
}
