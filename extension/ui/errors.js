
const ERRORS={query_required:'请输入想抓取的内容。',query_too_long:'条件请控制在 200 字以内。',unsupported_query:'暂支持课程名、标题关键词及人员联系方式。可写“课程：网络编程；关键词：实验”，复杂时间和语义条件暂不支持。',
  wrong_section:'这个条件与当前页面类型不符，请打开对应网页后重试。',need_login:'请先在原站自行登录，再点击提取。',unsupported:'当前网页尚未适配。',unsupported_dom:'尚未可靠识别此页面结构，未抓取内容。',
  frame_unsupported:'当前内容位于嵌入页面中，请打开独立内容页后重试。',backend_login_required:'请展开连接设置，登录 Campus Radar。',backend_account_changed:'Campus Radar 账号已变化，请重新抓取。',backend_unavailable:'本地后端不可用，提交尚未确认。',backend_timeout:'后端响应超时，可稍后查询同一提交。',
  permission_denied:'缺少当前站点权限，请点击抓取并允许访问。',render_timeout:'页面加载超时，请等待原页内容加载后重试。',page_read_failed:'无法读取原页，页面可能已经关闭。',page_not_ready:'页面内容尚未就绪。',selection_missing:'所需内容已失效，请回原页确认后重试。',
  route_mismatch:'原页地址或视图已改变，请重新打开插件并抓取。',account_mismatch:'学校账号在读取期间变化，请确认后重试。',account_unknown:'无法可靠识别学校账号，当前只能预览。',preview_only:'结果存在不完整内容或身份不足，请打开详情或缩小条件后重试。',
  attachments_only:'当前页只有作业附件名称与链接，未读取附件正文；仅供预览，不作为完整作业保存。',navigation_only:'这是当前页的课程入口／概览，仅供预览。请打开课程或输入“课程名的作业”读取完整事项。',section_preview_only:'这是当前已加载的区块预览，未确认为完整独立事项，暂不保存。',identity_unknown:'原站身份尚未确认，仅供预览。',fields_missing:'部分指定字段未找到，不推测缺失内容。',detail_required:'当前只有摘要／入口，请进入详情后重新抓取。',query_changed:'条件已修改，请重新抓取。',preview_required:'请先完成当前条件的抓取预览。',
  worker_interrupted:'读取被中断，未确认完成，请重新抓取。',worker_timeout:'后台暂未响应，可重新打开插件查询任务，避免重复提交。',worker_unavailable:'扩展后台不可用，请重新加载扩展。',draft_not_found:'预览已经过期或不存在，请重新抓取。',draft_limit:'本地预览已达容量上限，请在最近记录中管理旧草稿。',
  content_too_large:'匹配内容超过安全上限，请缩小范围。',candidate_limit:'匹配数量过多，请缩小条件。',invalid_response:'后端响应异常，未确认保存。',invalid_capture_response:'后端逐项回执异常，未确认保存。',idempotency_conflict:'同一请求的内容发生冲突，请重新抓取。',invalid_selection:'一次仅能保存 1–30 条完整匹配结果，请缩小范围。'};
export const FIELD_NAMES={course:'课程',semester:'学期',week:'周次',weekday:'星期',period:'节次',datetime_text:'时间原文',date_text:'日期原文',email:'邮箱',office:'办公室',phone:'电话',role:'职务',department:'部门',published_text:'发布时间原文',valid_until_text:'有效期原文',native_occurrence_id:'课次身份'};
Object.assign(ERRORS,{unsupported_region:'指定区块不存在、未显示或结构尚未识别；未将它当作零匹配，请确认原页已加载。',timeline_preview_only:'这是时间线活动摘要，时间保留原文。请打开原文详情后重新抓取并保存。',contact_preview_only:'这是联系信息预览，不创建作业或待办。'});
Object.assign(ERRORS,{unsupported:'此页面不能注入网页读取脚本，请打开普通 HTTP(S) 网页。',page_too_large:'页面结构过大，未完成读取。请在内容更集中的页面重试。',source_label_required:'请选择公开网页，或填写私人来源标签并点确定，再保存资料。',specialized_source_required:'这个站点须使用校园专用读取规则。'});
ERRORS.restricted_page='浏览器限制在此页面运行扩展读取脚本，请打开普通网站页面。';
export const errorText=code=>ERRORS[code] || `操作未完成：${code}`;


Object.assign(ERRORS,{bad_credentials:'工作台邮箱或密码错误，请核对后重试。',invalid_server:'请输入有效的 HTTP(S) 后端地址。',unauthorized:'工作台登录已失效，请重新登录后重试原提交。',invalid_session_response:'工作台身份响应异常，请检查后端连接。',outbox_full:'待提交内容已达容量上限，请先处理未确认记录。'});
