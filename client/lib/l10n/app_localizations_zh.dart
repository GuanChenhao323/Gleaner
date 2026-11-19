// ignore: unused_import
import 'package:intl/intl.dart' as intl;

import 'app_localizations.dart';

// ignore_for_file: type=lint

/// The translations for Chinese (`zh`).
class AppLocalizationsZh extends AppLocalizations {
  AppLocalizationsZh([String locale = 'zh']) : super(locale);

  @override
  String get appTitle => '拾课 Gleaner';

  @override
  String get navDesk => '工作台';

  @override
  String get navInbox => '收件箱';

  @override
  String get navCourses => '课程';

  @override
  String get navSources => '信息源';

  @override
  String get navSettings => '设置';

  @override
  String get navCompose => '写邮件';

  @override
  String get navTransfer => '扫码传输';

  @override
  String get navAccount => '我的账号';

  @override
  String get navMore => '更多';

  @override
  String get actionView => '查看';

  @override
  String get actionClose => '关闭';

  @override
  String get actionSave => '保存';

  @override
  String get actionCancel => '取消';

  @override
  String get actionGotIt => '知道了';

  @override
  String get actionSyncNow => '立即同步';

  @override
  String get login => '登录';

  @override
  String get loginOrRegister => '登录或注册';

  @override
  String get register => '创建账号';

  @override
  String get registerAndStart => '注册并开始';

  @override
  String get email => '邮箱';

  @override
  String get password => '密码';

  @override
  String get passwordMin8 => '密码（至少 8 位）';

  @override
  String get emailCode => '邮箱验证码';

  @override
  String get getCode => '获取验证码';

  @override
  String resendInSeconds(int seconds) {
    return '$seconds 秒后重发';
  }

  @override
  String get nickname => '昵称';

  @override
  String get grade => '年级';

  @override
  String get major => '专业';

  @override
  String get agreePrivacy => '我已阅读隐私说明';

  @override
  String get privacyAgreeDetail =>
      '拾课只保存 Moodle 等来源的登录会话，不保存统一认证密码；学校邮箱需使用“应用专用密码”，以 AES-GCM 加密保存；邮件只保存标题、发件人、摘要与链接；可随时删除账号与全部数据。';

  @override
  String get serverAddress => '服务器地址';

  @override
  String get haveAccountSignIn => '已有账号？登录';

  @override
  String get noAccountRegister => '还没有账号？注册';

  @override
  String codeSent(String email) {
    return '验证码已发送到 $email，10 分钟内有效';
  }

  @override
  String get guestDesk => '登录后，在这里查看今日待办和本周截止事项。';

  @override
  String get guestInbox => '登录后，在这里查看作业、通知和页面更新。';

  @override
  String get guestCourses => '登录后，在这里按课程查看作业和截止日期。';

  @override
  String get guestSources => '登录后，可在这里管理订阅的校园网页和 Moodle 信息源。';

  @override
  String get guestSettings => '登录后，可在这里管理个人资料和提醒设置。';

  @override
  String get sectionNotifications => '通知';

  @override
  String get sectionConnection => '连接';

  @override
  String get sectionAccount => '账号';

  @override
  String get quietHours => '免打扰';

  @override
  String get dailyDigest => '每日摘要';

  @override
  String dailyDigestAt(String time) {
    return '每天 $time';
  }

  @override
  String get digestAlsoEmail => '摘要同时发邮件';

  @override
  String get personalRules => '个性化规则';

  @override
  String get pushStatus => '推送状态';

  @override
  String get connected => '已连接';

  @override
  String get connecting => '连接中…';

  @override
  String get disconnected => '未连接';

  @override
  String get sync => '同步';

  @override
  String syncPending(int count) {
    return '$count 项待同步';
  }

  @override
  String get syncUpToDate => '已是最新';

  @override
  String get server => '服务器';

  @override
  String get privacy => '隐私说明';

  @override
  String get privacyBody =>
      'Moodle 等来源只保存登录会话，不保存统一认证密码；学校邮箱的应用专用密码与会话均用 AES-GCM 加密保存；邮件只保存标题、发件人、摘要与链接；可随时删除账号与全部数据。';

  @override
  String get changePassword => '修改密码';

  @override
  String get signOut => '退出登录';

  @override
  String get deleteAccount => '删除账号';

  @override
  String get language => '语言';

  @override
  String get languageEnglish => 'English';

  @override
  String get languageSimplified => '简体中文';

  @override
  String get languageTraditional => '繁體中文';

  @override
  String get inboxUnread => '未读';

  @override
  String get inboxStarred => '收藏';

  @override
  String get inboxTodo => '待办';

  @override
  String get inboxEvent => '日程';

  @override
  String get inboxNotice => '通知';

  @override
  String get inboxTrash => '回收站';

  @override
  String get statusOpen => '待完成';

  @override
  String get statusDone => '已完成';

  @override
  String get statusActive => '未归档';

  @override
  String get statusArchived => '已归档';

  @override
  String get statusUnread => '未读';

  @override
  String get statusRead => '已读';

  @override
  String get statusAll => '全部';

  @override
  String get newLabel => '新建标签';

  @override
  String get labels => '标签';

  @override
  String get pinSidebar => '固定侧栏';

  @override
  String get unpinSidebar => '取消固定';

  @override
  String get saved => '已保存';

  @override
  String get classmate => '同学';

  @override
  String get justNow => '刚刚';

  @override
  String get never => '从未';

  @override
  String minutesAgo(int count) {
    return '$count 分钟前';
  }

  @override
  String hoursAgo(int count) {
    return '$count 小时前';
  }

  @override
  String yesterdayAt(String time) {
    return '昨天 $time';
  }

  @override
  String get today => '今天';

  @override
  String get tomorrow => '明天';

  @override
  String get dayAfterTomorrow => '后天';

  @override
  String get yesterday => '昨天';

  @override
  String overdueHours(int count) {
    return '已截止 $count 小时';
  }

  @override
  String overdueDays(int count) {
    return '已截止 $count 天';
  }

  @override
  String remainingMinutes(int count) {
    return '还剩 $count 分钟';
  }

  @override
  String remainingHours(int count) {
    return '还剩 $count 小时';
  }

  @override
  String remainingDaysHours(int days, int hours) {
    return '还剩 $days 天 $hours 小时';
  }

  @override
  String remainingDays(int count) {
    return '还剩 $count 天';
  }

  @override
  String get kindAssignment => '待办任务';

  @override
  String get kindEvent => '日程活动';

  @override
  String get kindNotice => '通知';

  @override
  String get kindMail => '邮件';

  @override
  String get kindClip => '剪藏';

  @override
  String get kindPage => '网页';

  @override
  String get kindItem => '事项';

  @override
  String get channelWeb => '网站';

  @override
  String get channelMail => '邮件';

  @override
  String get sourceOk => '正常';

  @override
  String get sourceFailed => '检查失败';

  @override
  String get sourceNeedLogin => '需要重新登录';

  @override
  String get sourceWaiting => '等待首次检查';

  @override
  String get greetingLateNight => '夜深了';

  @override
  String get greetingMorning => '早上好';

  @override
  String get greetingNoon => '中午好';

  @override
  String get greetingAfternoon => '下午好';

  @override
  String get greetingEvening => '晚上好';

  @override
  String get priorityUrgent => '紧急';

  @override
  String get priorityNormal => '普通';

  @override
  String get priorityLow => '低';

  @override
  String get typeTodo => '待办';

  @override
  String get typeEvent => '日程';

  @override
  String get typeNotice => '通知';

  @override
  String get markOpen => '标为待完成';

  @override
  String get markDone => '标为已完成';

  @override
  String get unarchive => '取消归档';

  @override
  String get archive => '归档';

  @override
  String get markUnread => '标为未读';

  @override
  String get markRead => '标为已读';

  @override
  String get fieldTitle => '标题';

  @override
  String get fieldSummary => '摘要';

  @override
  String get fieldType => '类型';

  @override
  String get fieldDeadline => '截止时间';

  @override
  String get fieldStart => '开始时间';

  @override
  String get fieldEnd => '结束时间';

  @override
  String get fieldLocation => '地点';

  @override
  String get fieldRequirements => '要求';

  @override
  String get emptyValue => '（空）';

  @override
  String get done => '已完成';

  @override
  String get deskTodayFocus => '今天要事';

  @override
  String get deskThisWeek => '本周';

  @override
  String get deskNeedsAttention => '需处理';

  @override
  String get deskCalendar => '日历';

  @override
  String get deskHideCalendar => '收起日历';

  @override
  String get deskDueIn7Days => '7 天内截止';

  @override
  String get deskSourceIssues => '信息源异常';

  @override
  String get deskShowMore => '显示更多';

  @override
  String get deskInboxLink => '收件箱';

  @override
  String get filterAll => '全部';

  @override
  String get summary => '摘要';

  @override
  String get requirements => '要求';

  @override
  String get originalContent => '原文内容';

  @override
  String get sourceMonitor => '来源监测';

  @override
  String deadlineAt(String when) {
    return '截止于 $when';
  }

  @override
  String get openSource => '打开原始来源';

  @override
  String get edit => '修改';

  @override
  String get notImportant => '不重要';

  @override
  String get copyLink => '复制链接';

  @override
  String get star => '收藏';

  @override
  String get unstar => '取消收藏';

  @override
  String get weekdayMon => '周一';

  @override
  String get weekdayTue => '周二';

  @override
  String get weekdayWed => '周三';

  @override
  String get weekdayThu => '周四';

  @override
  String get weekdayFri => '周五';

  @override
  String get weekdaySat => '周六';

  @override
  String get weekdaySun => '周日';

  @override
  String get generateQr => '生成二维码';

  @override
  String get orEnterCode => '或输入配对码';

  @override
  String get codeHint => '6 位配对码';

  @override
  String get join => '加入';

  @override
  String get scanQr => '扫描二维码';

  @override
  String get codeValid30m => '配对码 30 分钟内有效';

  @override
  String get paired => '已配对';

  @override
  String get waitingPair => '等待配对…';

  @override
  String get sendFile => '发送文件';

  @override
  String get files => '文件';

  @override
  String get noFilesYet => '还没有文件';

  @override
  String get send => '发送';

  @override
  String get to => '收件人';

  @override
  String get ccOptional => '抄送（可选）';

  @override
  String get subject => '主题';

  @override
  String get bodyHint => '正文';

  @override
  String get addAttachment => '添加附件';

  @override
  String get recentSent => '最近发送';

  @override
  String get noSubject => '（无主题）';

  @override
  String get pleaseFillRecipient => '请填写收件人';

  @override
  String get sent => '已发送';

  @override
  String get duplicateSend => '这封邮件之前已经发送过，没有重复发送';

  @override
  String sendFailed(String error) {
    return '发送失败：$error';
  }

  @override
  String get lastCheckFailed => '最近一次检查失败';

  @override
  String get lastSuccessCheck => '最后成功检查';

  @override
  String get reason => '原因';

  @override
  String get failedAt => '失败时间';

  @override
  String get nextCheck => '下次检查';

  @override
  String get goHandle => '去处理';

  @override
  String get fieldBody => '正文';

  @override
  String operationFailed(String error) {
    return '操作失败：$error';
  }

  @override
  String get pluginCapture => '插件采集';

  @override
  String get alreadyStarted => '已开始';

  @override
  String get conflictBanner => '你改过的内容在来源里也更新了，请确认保留哪一个';

  @override
  String mineValue(String value) {
    return '我的：$value';
  }

  @override
  String sourceValue(String value) {
    return '来源：$value';
  }

  @override
  String get keepMine => '保留我的';

  @override
  String get useSource => '采用来源';

  @override
  String get monitorUnsupported => '暂不支持自动检查，可打开原始来源手动核对';

  @override
  String get monitorDisabled => '已关闭自动检查';

  @override
  String get monitorPending => '已开启，等待第一次检查';

  @override
  String get monitorUnchanged => '最近一次检查：无变化';

  @override
  String get monitorChanged => '最近一次检查：发现变化';

  @override
  String get monitorFailed => '最近一次检查失败';

  @override
  String get errAuthExpired => '登录已过期：请在浏览器里重新登录该网站';

  @override
  String get errForbidden => '没有权限访问该页面';

  @override
  String get errNetwork => '网络错误';

  @override
  String get errNotFound => '页面上找不到这条事项';

  @override
  String get errParseFailed => '页面结构变了，暂时无法解析';

  @override
  String get errUnsupported => '该页面不再支持自动检查';

  @override
  String get lastSuccessNever => '还没有';

  @override
  String lastSuccessCheckLine(String when) {
    return '最后成功检查：$when';
  }

  @override
  String reasonLine(String reason) {
    return '原因：$reason';
  }

  @override
  String failedAtLine(String when) {
    return '失败时间：$when';
  }

  @override
  String nextCheckLine(String when) {
    return '下次检查：$when（需 Chrome 与本地后端运行）';
  }

  @override
  String get restoreSourceValue => '恢复来源值';

  @override
  String get willRestoreSource => '将恢复来源值';

  @override
  String get notSet => '未设置';

  @override
  String get choose => '选择';

  @override
  String get clear => '清空';

  @override
  String get editItem => '修改事项';

  @override
  String get editItemHint => '修改只影响你看到的内容；来源更新不会覆盖，若来源也改了会提示你确认。';

  @override
  String get editsSaved => '已保存修改';

  @override
  String oldValue(String value) {
    return '旧：$value';
  }

  @override
  String newValue(String value) {
    return '新：$value';
  }

  @override
  String get filterTodoTasks => '待办任务';

  @override
  String get filterEvents => '日程活动';

  @override
  String get filterNotices => '通知';

  @override
  String get todayShort => '今';

  @override
  String monthDay(int month, int day) {
    return '$month月$day日';
  }

  @override
  String scorePoints(num score) {
    return '$score 分';
  }

  @override
  String get webMaterial => '网页资料';

  @override
  String get sourceDeleted => '来源已删除';

  @override
  String originalTitle(String title) {
    return '原标题：$title';
  }

  @override
  String get sourceAndReliability => '来源与可靠性';

  @override
  String get unknownSource => '未知来源';

  @override
  String get lastSaved => '最后保存';

  @override
  String get crossChannelMerge => '跨渠道合并';

  @override
  String sameItemMerged(String channels) {
    return '同一事项出现在 $channels，已合并为一条';
  }

  @override
  String get whyPushed => '为什么推给你';

  @override
  String changedToType(String type) {
    return '已改为$type';
  }

  @override
  String get goWorkbench => '去工作台';

  @override
  String get changeTypeFailed => '修改类型失败，请重试';

  @override
  String get notImportantToast => '已降低该来源的权重，系统会逐步贴合你的习惯';

  @override
  String get copiedTitleLink => '已复制标题与链接';

  @override
  String changeTypeCurrent(String type) {
    return '更改类型，当前为$type';
  }

  @override
  String get completed => '已完成';

  @override
  String get manuallyCorrected => '（已手动修正）';

  @override
  String get editHistory => '修改历史';

  @override
  String versionsCount(int count) {
    return '$count 个版本';
  }

  @override
  String get firstSeen => '首次发现';

  @override
  String get contentUpdated => '内容更新';

  @override
  String get noDeadlines => '没有截止';

  @override
  String get unreadStatus => '未读';

  @override
  String attachmentsCount(int count) {
    return '$count 个附件';
  }

  @override
  String get deskEmptyToday => '今天没有要紧的';

  @override
  String deskEmptyFilter(String filter) {
    return '暂无$filter';
  }

  @override
  String get statusChanged => '变更';

  @override
  String get statusUrgent => '紧急';

  @override
  String sourceNeedLoginNamed(String name) {
    return '「$name」需要重新登录';
  }

  @override
  String sourceCheckFailedNamed(String name) {
    return '「$name」检查失败';
  }

  @override
  String andMoreItems(int count) {
    return '等 $count 项';
  }

  @override
  String get summaryLlmHint => '由大模型生成 · 仅作导读，以原文为准';

  @override
  String get summaryRuleHint => '规则提取 · 仅作导读，以原文为准';

  @override
  String get attachments => '附件';

  @override
  String get sourceRawFields => '来源原始字段';

  @override
  String get sfCourse => '课程';

  @override
  String get sfSemester => '学期';

  @override
  String get sfWeek => '周次';

  @override
  String get sfWeekday => '星期';

  @override
  String get sfPeriod => '节次';

  @override
  String get sfDatetime => '原始时间';

  @override
  String get sfOffice => '办公室';

  @override
  String get sfDepartment => '部门';

  @override
  String get sfRole => '角色';

  @override
  String get sfPhone => '电话';

  @override
  String get sfEmail => '邮箱';

  @override
  String get sfSubtype => '资料类别';

  @override
  String get conditionSourceCheck => '条件来源检查';

  @override
  String get viewSourceCheckSettings => '查看来源与检查设置';

  @override
  String get browserSourceCheck => '浏览器来源检查';

  @override
  String get snapshotOnlyNoBg => '仅保存快照 · 暂不支持后台检查';

  @override
  String get myNotes => '我的备注（来源更新不会覆盖）';

  @override
  String get groupOverdue => '已过截止';

  @override
  String get groupNextWeek => '下周';

  @override
  String get groupLater => '之后';

  @override
  String get groupNoDeadline => '未设截止时间';

  @override
  String get assignments => '作业';

  @override
  String get noAssignmentsYet => '还没有作业';

  @override
  String doneCount(int count) {
    return '$count 项已完成';
  }

  @override
  String get noNotices => '暂无通知';

  @override
  String get statusPending => '待完成';

  @override
  String get courseNeedNetwork => '课程信息需要联网获取';

  @override
  String get courseNotFound => '找不到课程';

  @override
  String get backToCourses => '返回课程列表';

  @override
  String get markReadShort => '标为已读';

  @override
  String get markUnreadShort => '标为未读';

  @override
  String get addTodo => '加入待办';

  @override
  String get removeTodo => '移出待办';

  @override
  String get calMonth => '月';

  @override
  String get calTwoWeeks => '两周';

  @override
  String get calWeek => '周';

  @override
  String get brandFallback => '拾';

  @override
  String get bcNotExecuted => '待首次检查';

  @override
  String get bcUnchanged => '检查成功 · 无变化';

  @override
  String get bcChanged => '已发现来源变化';

  @override
  String get bcNeedLogin => '请在学校原站重新登录';

  @override
  String get bcAccountMismatch => '学校账号已切换 · 旧绑定已停止';

  @override
  String get bcSelectionMissing => '原文定位失效 · 需要重新采集';

  @override
  String get bcViewMismatch => '原学期／周次视图失效 · 需要重新采集';

  @override
  String get bcRouteMismatch => '来源路由已改变 · 需要重新采集';

  @override
  String get bcRenderTimeout => '页面加载超时';

  @override
  String get bcPermissionDenied => '浏览器来源权限不足';

  @override
  String get bcUnsupported => '暂不支持监测';

  @override
  String get bcFailed => '检查失败';

  @override
  String get rrRejected => '检查结果校验失败 · 资料保留，监测已暂停';

  @override
  String get rrPurged => '关联资料已彻底删除 · 请在原网页重新提取';

  @override
  String get rrStarting => '自动监测启动中 · 等待首次刷新';

  @override
  String get rrUserBusy => '监测页正在编辑 · 延后刷新';

  @override
  String get rrTabMissing => '监测页已关闭 · 请打开原页后重新绑定';

  @override
  String get rrTabRebind => '浏览器会话已重启 · 请重新绑定监测页';

  @override
  String get rrTabAmbiguous => '打开了多个相同网页 · 请保留一个监测页';

  @override
  String get rrSingleAccount => '本站已绑定另一账号 · 已暂停';

  @override
  String get rrRestored => '来源已恢复 · 检查暂停，须重新测试';

  @override
  String get rrDocsRestored => '资料已恢复 · 来源检查保持暂停';

  @override
  String get rrDocsTrashed => '关联资料已移入回收站 · 检查已暂停';

  @override
  String get rrPrivateRequired => '检测到登录账号 · 请按需要登录的来源重新采集';

  @override
  String get rrVerified => '重读验证通过 · 待检查';

  @override
  String get rrAccountUnknown => '无法核对来源账号 · 保留手动采集';

  @override
  String get rrAccountMismatch => '来源账号不符 · 已暂停';

  @override
  String get rrNoMatch => '本次未匹配 · 已保留旧资料';

  @override
  String get rrPreviewOnly => '本次内容不完整 · 未覆盖资料';

  @override
  String get rrUnsupported => '暂不支持后台重读';

  @override
  String get rrWorkerInterrupted => '浏览器任务中断 · 可重试';

  @override
  String get deadlineCalendar => '截止日历';

  @override
  String get rsExpired => '检查已超时 · 等待浏览器重试';

  @override
  String get rsQueued => '已排队 · 等待执行';

  @override
  String get rsChecking => '浏览器检查中';

  @override
  String get rsWaitChrome => '等待本机 Chrome';

  @override
  String get rsLoginReuse => '复用当前Chrome会话（用户确认）';

  @override
  String get rsLoginNone => '无需登录（声明）';

  @override
  String get rsLoginRequired => '需要登录';

  @override
  String get rsIdResidentGeneric => '专用监测页 · 单账号会话（用户确认）';

  @override
  String get rsIdResidentSchool => '原学校账号 · 专用监测页';

  @override
  String get rsIdPublic => '无需登录（用户声明）';

  @override
  String get rsAccountUnchecked => '账号未核对';

  @override
  String get rsIdSchoolChrome => '原学校账号 · 本机 Chrome';

  @override
  String get rsTitleTimeline => 'Moodle 活动摘要';

  @override
  String get rsTitleTeacher => '教师资料';

  @override
  String get rsTitleWeb => '网页资料';

  @override
  String get rsScopeTitle => '标题与链接标题';

  @override
  String get rsScopeTimeline => '当前已加载活动 · 摘要整组';

  @override
  String get rsScopeBody => '正文与列表 · 整组匹配';

  @override
  String get rsScopeOriginal => '原条件与约定视图';

  @override
  String get rsWaitLocalChrome => '等待本机Chrome执行';

  @override
  String get rsStartingCheck => '正在启动／检查';

  @override
  String get rsPeriodicPaused => '定期监测已暂停';

  @override
  String get rsPartialPaused => '部分规则已暂停';

  @override
  String get rsPeriodicOn => '定期监测中';

  @override
  String get rsManualOnly => '仅手动检查';

  @override
  String get rsAwaitFirstRefresh => '等待首次刷新';

  @override
  String get rsDedicatedMonitor => '专用监测页';

  @override
  String labelCreated(String name) {
    return '已创建「$name」';
  }

  @override
  String labelDeleted(String name) {
    return '已删除「$name」';
  }

  @override
  String deleteLabelTitle(String name) {
    return '删除「$name」？';
  }

  @override
  String get deleteLabelBody => '事项上的该标签会被一并去掉，收藏星标不受影响。';

  @override
  String get actionDelete => '删除';

  @override
  String get searchInboxHint => '搜索标题、课程、来源';

  @override
  String get inboxEmptyFilter => '当前筛选没有事项';

  @override
  String get tagItem => '给事项打标签';

  @override
  String get loadingLabels => '正在加载标签';

  @override
  String get labelsLoadFailed => '标签加载失败';

  @override
  String get retry => '重试';

  @override
  String get noLabelsYet => '还没有标签，可以先创建一个。';

  @override
  String get newLabelAction => '新建标签';

  @override
  String get labelNameHint => '例如：收藏、作业、社团';

  @override
  String get color => '颜色';

  @override
  String get create => '创建';

  @override
  String get movedToTrash => '已移入回收站，资料与历史保留。';

  @override
  String get restoredItem => '已恢复资料；来源检查保持暂停。';

  @override
  String get undo => '撤销';

  @override
  String get accountChanged => '工作台账号已变化';

  @override
  String restoreIncomplete(String error) {
    return '恢复未完成：$error';
  }

  @override
  String actionUnconfirmed(String error) {
    return '操作未确认：$error';
  }

  @override
  String get restoreToInbox => '恢复到收件箱';

  @override
  String get moveToTrash => '移入回收站';

  @override
  String get cannotOpenItem => '无法打开这条事项';

  @override
  String get itemNotFound => '事项不存在或不属于当前账号。请确认工作台与插件使用同一拾课 Gleaner 邮箱。';

  @override
  String get loginExpired => '登录已失效，请在工作台重新登录。';

  @override
  String get detailLoadFailed => '未能读取详情，请检查后端连接后重试。';

  @override
  String currentDeskAccount(String email) {
    return '当前工作台账号：$email';
  }

  @override
  String get notSignedIn => '未登录';

  @override
  String get backToSources => '返回信息源';

  @override
  String get notProvided => '未提供';

  @override
  String get sourceDeadline => '来源截止时间';

  @override
  String get submitRequirements => '提交要求';

  @override
  String get sourceFields => '来源字段';

  @override
  String beforeChange(String value) {
    return '变更前：\n$value';
  }

  @override
  String afterChange(String value) {
    return '变更后：\n$value';
  }

  @override
  String timelineMaterial(int count) {
    return '活动摘要资料 · $count 条活动';
  }

  @override
  String webSnapshot(int count) {
    return '网页资料快照 · $count 个片段';
  }

  @override
  String activityN(int n, String title) {
    return '活动 $n：$title';
  }

  @override
  String fragmentN(int n, String title) {
    return '片段 $n：$title';
  }

  @override
  String get openActivity => '打开活动详情';

  @override
  String courseField(String value) {
    return '课程：$value';
  }

  @override
  String wcCond(String value) {
    return '条件：$value';
  }

  @override
  String get wcIdentitySchool => '来源身份：原学校账号 · 本机 Chrome';

  @override
  String get wcScopeTimeline => '范围：当前已加载 Timeline 活动';

  @override
  String get wcMatchTitle => '匹配位置：标题与链接标题';

  @override
  String get wcMatchBody => '匹配位置：正文与列表';

  @override
  String wcAlias(String value) {
    return '来源别名：$value';
  }

  @override
  String get wcLoginNone => '原站登录要求：无需登录（用户声明）';

  @override
  String get wcLoginRequired => '原站登录要求：需要登录';

  @override
  String wcAccount(String value) {
    return '来源账号：$value';
  }

  @override
  String get wcAccountUnchecked => '未核对';

  @override
  String get wcPrivateOnly => '资料可见：仅自己';

  @override
  String get wcTimelineHint =>
      '这是活动提醒摘要，未读取详情正文，不代表完整作业或已确认的日历事件。日期和时间均保留原文，缺失时不推测。';

  @override
  String get wcLinkedHint => '仅约定视图中的匹配片段，不代表完整文章或邮件。原条件已关联信息源，检查方式与状态请在来源中查看。';

  @override
  String get wcUnlinkedHint =>
      '仅当前已加载内容，不代表完整文章或邮件。来源别名由用户声明；来源检查未启用，账号证明与后台能力须分别核对。';

  @override
  String get wcUpdateOnChange => '检查成功且内容变化时更新同一资料的来源版本，个人备注与状态保留。';

  @override
  String get wcUpdateOnRecapture => '同来源标签、URL、条件及范围，重新提取并明确保存后更新本资料版本。';

  @override
  String wcDateText(String value) {
    return '日期原文：$value';
  }

  @override
  String wcTimeText(String value) {
    return '时间原文：$value';
  }

  @override
  String wcDomEvidence(String value) {
    return 'DOM 依据：$value';
  }

  @override
  String get aliasMissing => '未提供';

  @override
  String get changeNoteSep => '；';

  @override
  String get changeNameSep => '、';

  @override
  String changeDays(int count) {
    return '$count 天';
  }

  @override
  String changeHours(int count) {
    return '$count 小时';
  }

  @override
  String changeDeadlineAdvanced(String span, String from, String to) {
    return '截止提前 $span（$from → $to）';
  }

  @override
  String changeDeadlinePostponed(String span, String from, String to) {
    return '截止推迟 $span（$from → $to）';
  }

  @override
  String changeDeadlineAdded(String when) {
    return '新增截止时间 $when';
  }

  @override
  String get changeDeadlineRemoved => '截止时间被移除';

  @override
  String changeAttachmentReplaced(String names) {
    return '附件替换：$names';
  }

  @override
  String changeAttachmentAdded(String names) {
    return '新增附件：$names';
  }

  @override
  String changeAttachmentRemoved(String names) {
    return '附件被移除：$names';
  }

  @override
  String get changeAttachmentUpdated => '附件内容更新';

  @override
  String get changeRequirements => '提交要求变化';

  @override
  String get changeEventTime => '活动时间变化';

  @override
  String get changeLocation => '地点变化';

  @override
  String get changeType => '类型变化';

  @override
  String get changeTitle => '标题修改';

  @override
  String get changeWording => '内容措辞调整';

  @override
  String get sourceSessionExpired => '登录会话已失效，请到“来源”重新登录';

  @override
  String get eventReminder => '截止提醒';

  @override
  String get eventImportantChange => '重要变更';

  @override
  String get eventNewItem => '新事项';

  @override
  String get digestTitle => '今日摘要';

  @override
  String digestBody(int newCount, int upcoming) {
    return '过去 24 小时 $newCount 条新事项，$upcoming 项即将截止';
  }

  @override
  String get reasonBlocked => '命中屏蔽词';

  @override
  String reasonKeyword(String words) {
    return '关键词：$words';
  }

  @override
  String get reasonDue24h => '24 小时内截止';

  @override
  String get reasonDue7d => '7 天内截止';

  @override
  String get reasonYourCourse => '你的课程';

  @override
  String get reasonCourseItem => '课程事项';

  @override
  String get reasonGradeMajorMatch => '符合你的年级/专业';

  @override
  String get reasonOtherAudience => '面向其他年级或专业';

  @override
  String get reasonImportantChange => '重要变更';

  @override
  String get errMoodleNeedLogin => '尚未登录该 Moodle 来源';

  @override
  String get courseOpenCount => '待完成';

  @override
  String get noCoursesYet => '还没有课程';

  @override
  String get noCoursesHint =>
      '添加 Moodle 来源后，每门课会有一个主页。添加“教师信息”模板可以补充老师的办公室与邮箱。';

  @override
  String get noCourseTodos => '暂无待办';

  @override
  String get addFacultySourceHint => '添加“教师信息”来源以显示老师联系方式';

  @override
  String get captureFromWeb => '从网页采集';

  @override
  String get refreshSourceListTooltip => '刷新列表状态（不访问来源网页）';

  @override
  String get cannotReadSources => '无法读取信息源';

  @override
  String get savedPages => '已保存页面';

  @override
  String get periodicRules => '定期规则';

  @override
  String get needsAttention => '需要处理';

  @override
  String get changesFound => '本次发现变化';

  @override
  String get mySources => '我的信息源';

  @override
  String get noReadingSources => '还没有保留原条件的信息源。请在原网页通过插件提取、预览并保存。';

  @override
  String get monitorTabHint =>
      '专用监测标签页需要保持打开；可以关闭工作台页面。请保持Chrome、扩展和本地服务运行，检查可能延后。';

  @override
  String deletedSourcesTitle(int count) {
    return '已删除来源（$count）';
  }

  @override
  String get deletedSourcesSubtitle => '恢复后保持暂停；彻底删除会永久清除关联资料与历史。';

  @override
  String deletedSourcesUnavailable(String error) {
    return '已删除来源暂不可用：$error';
  }

  @override
  String get legacyDemoTitle => '旧资料与演示订阅';

  @override
  String get legacyDemoSubtitle => '保留已有数据；缺少原条件时请打开原网页重新采集。';

  @override
  String get chromeConnectedHint => '本机 Chrome 近期已连接 · 原站登录状态逐来源检查';

  @override
  String get chromeDisconnectedHint => '尚未检测到执行设备近期连接 · 保留上次成功结果';

  @override
  String get checkQueued => '检查已排队；结果确认后更新状态。';

  @override
  String get periodicResumed => '定期检查已恢复。';

  @override
  String get periodicPaused => '定期检查已暂停，仍可手动检查。';

  @override
  String get pageCheckQueued => '整页检查已排队；同页规则共享刷新。';

  @override
  String get pagePlanUpdated => '整页监测计划已更新。';

  @override
  String get sourceDeletedKeep => '来源已删除，资料与历史保留。';

  @override
  String get sourceDeletedTrash => '来源已删除，关联资料已移入回收站。';

  @override
  String get deleteSourceTitle => '删除信息源？';

  @override
  String get deleteSourceBody =>
      '停止此来源的手动和定期检查。默认保留已保存资料、备注及历史版本。可从“已删除来源”手动恢复；旧任务不会自动恢复。';

  @override
  String get deleteSourceAlsoTrash => '同时将关联资料移入个人回收站';

  @override
  String get deleteSourceAlsoTrashHint => '也会在引用这些资料的其他来源中隐藏；可从收件箱回收站恢复。';

  @override
  String get deleteSourceAction => '删除来源';

  @override
  String get restoreSourceAction => '恢复来源';

  @override
  String get purgeForever => '彻底删除';

  @override
  String get checkStoppedKept => '检查已停止 · 资料与历史按原选择保留';

  @override
  String get sourceRestoredPaused => '来源已恢复并暂停；请重新测试重读。';

  @override
  String get manageLegacySources => '管理旧模板／演示来源';

  @override
  String get legacyCaptureSubtitle => '旧采集资料 · 未自动迁入条件监测';

  @override
  String legacyCapturesFailed(String error) {
    return '旧资料读取失败：$error';
  }

  @override
  String statusRefreshFailed(String error) {
    return '状态刷新失败：$error';
  }

  @override
  String get profileTitle => '个人资料';

  @override
  String get coursesCommaHint => '我的课程（用、分隔）';

  @override
  String get coursesHintSample => '网络编程、操作系统';

  @override
  String get gradeHintSample => '2024级';

  @override
  String get majorHintSample => '计算机';

  @override
  String get profileMatchHint => '年级、专业与课程用于判断通知是否与你相关。';

  @override
  String get quietStartHelp => '免打扰开始';

  @override
  String get quietEndHelp => '免打扰结束';

  @override
  String get digestTimeHelp => '每日摘要时间';

  @override
  String get currentPassword => '当前密码';

  @override
  String get newPasswordMin8 => '新密码（至少 8 位）';

  @override
  String get passwordChangedToast => '密码已修改，其他设备需要重新登录';

  @override
  String get confirmChangePassword => '确认修改';

  @override
  String get deleteAccountTitle => '删除账号？';

  @override
  String get deleteAccountBody => '将删除你的账号、订阅、登录会话、个人状态与发信记录，且无法恢复。请输入密码确认。';

  @override
  String get deleteForever => '永久删除';

  @override
  String get rulesSavedToast => '规则已保存，对之后的新事项生效';

  @override
  String get priorityFormula =>
      '优先级 = 100 ×（0.30 来源权重 + 0.25 关键词 + 0.25 截止临近 + 0.20 与你匹配）';

  @override
  String get priorityBands => '≥ 80 紧急（推送到手机）· 40–79 普通 · < 40 只进信息流与摘要';

  @override
  String get ruleKeyword => '关键词';

  @override
  String get ruleSenderWhitelist => '白名单发件人';

  @override
  String get ruleKeywordHint => '例如：保研、奖学金';

  @override
  String get ruleBlock => '屏蔽';

  @override
  String get actionAdd => '添加';

  @override
  String get noCustomRules => '还没有自定义规则';

  @override
  String get defaultKeywordsHint => '默认关键词：截止、deadline、考试、调课、取消。';

  @override
  String get teachersHeader => '教师';

  @override
  String get orEnterPairCode => '或输入配对码';

  @override
  String get pairCodeHint => '6 位配对码';

  @override
  String get joinPair => '加入';

  @override
  String get pairCodeTtl => '配对码 30 分钟内有效';

  @override
  String get filesHeader => '文件';

  @override
  String transferCorrupt(String name) {
    return '「$name」校验失败，请重新发送';
  }

  @override
  String transferPaused(String name) {
    return '网络中断，「$name」已暂停';
  }

  @override
  String get deviceBrowser => '浏览器';

  @override
  String purgeTitle(String title) {
    return '彻底删除「$title」？';
  }

  @override
  String purgeBody(int items, int versions, int checks) {
    return '将永久删除此来源、$items 份关联资料、$versions 个历史版本及 $checks 条检查记录。包括收件箱和回收站中的关联资料、个人备注与状态。';
  }

  @override
  String purgeRemovedRules(int count) {
    return '另有 $count 条规则只引用这些资料，将一并移除。';
  }

  @override
  String purgePausedRules(int count) {
    return '另有 $count 条规则包含这些资料，将暂停并要求重新提取；其余资料保留。';
  }

  @override
  String get purgePreviewInvalidate =>
      '该账号之前未完成的采集预览将统一失效，需要重新提取。其他已保存资料保留。插件离线时，旧缓存会在重新连接后清理。';

  @override
  String get purgeIrreversible => '此操作不可恢复。之后可以重新采集同一网页和条件，作为新资料保存。';

  @override
  String get purgeConfirmCheck => '我确认永久删除上述资料和历史版本';

  @override
  String get sourcePurgedOk => '来源、关联资料与历史已彻底删除。请重新提取后保存。';

  @override
  String sourcePurgedPartial(String error) {
    return '服务器已彻底删除；本机缓存清理待重试：$error';
  }

  @override
  String get accountChangedConfirm => '工作台账号已变化，请重新确认。';
}

/// The translations for Chinese, as used in Taiwan (`zh_TW`).
class AppLocalizationsZhTw extends AppLocalizationsZh {
  AppLocalizationsZhTw() : super('zh_TW');

  @override
  String get appTitle => '拾课 Gleaner';

  @override
  String get navDesk => '工作台';

  @override
  String get navInbox => '收件匣';

  @override
  String get navCourses => '課程';

  @override
  String get navSources => '資訊來源';

  @override
  String get navSettings => '設定';

  @override
  String get navCompose => '寫郵件';

  @override
  String get navTransfer => '掃碼傳輸';

  @override
  String get navAccount => '我的帳號';

  @override
  String get navMore => '更多';

  @override
  String get actionView => '查看';

  @override
  String get actionClose => '關閉';

  @override
  String get actionSave => '儲存';

  @override
  String get actionCancel => '取消';

  @override
  String get actionGotIt => '知道了';

  @override
  String get actionSyncNow => '立即同步';

  @override
  String get login => '登入';

  @override
  String get loginOrRegister => '登入或註冊';

  @override
  String get register => '建立帳號';

  @override
  String get registerAndStart => '註冊並開始';

  @override
  String get email => '電子郵件';

  @override
  String get password => '密碼';

  @override
  String get passwordMin8 => '密碼（至少 8 位）';

  @override
  String get emailCode => '電子郵件驗證碼';

  @override
  String get getCode => '取得驗證碼';

  @override
  String resendInSeconds(int seconds) {
    return '$seconds 秒後重發';
  }

  @override
  String get nickname => '暱稱';

  @override
  String get grade => '年級';

  @override
  String get major => '主修';

  @override
  String get agreePrivacy => '我已閱讀隱私說明';

  @override
  String get privacyAgreeDetail =>
      '拾課只保存 Moodle 等來源的登入工作階段，不保存統一認證密碼；學校信箱需使用「應用程式專用密碼」，以 AES-GCM 加密保存；郵件只保存標題、寄件人、摘要與連結；可隨時刪除帳號與全部資料。';

  @override
  String get serverAddress => '伺服器位址';

  @override
  String get haveAccountSignIn => '已有帳號？登入';

  @override
  String get noAccountRegister => '還沒有帳號？註冊';

  @override
  String codeSent(String email) {
    return '驗證碼已傳送到 $email，10 分鐘內有效';
  }

  @override
  String get guestDesk => '登入後，在這裡查看今日待辦與本週截止事項。';

  @override
  String get guestInbox => '登入後，在這裡查看作業、通知與頁面更新。';

  @override
  String get guestCourses => '登入後，在這裡依課程查看作業與截止日期。';

  @override
  String get guestSources => '登入後，可在這裡管理訂閱的校園網頁與 Moodle 資訊來源。';

  @override
  String get guestSettings => '登入後，可在這裡管理個人資料與提醒設定。';

  @override
  String get sectionNotifications => '通知';

  @override
  String get sectionConnection => '連線';

  @override
  String get sectionAccount => '帳號';

  @override
  String get quietHours => '勿擾';

  @override
  String get dailyDigest => '每日摘要';

  @override
  String dailyDigestAt(String time) {
    return '每天 $time';
  }

  @override
  String get digestAlsoEmail => '摘要同時寄送郵件';

  @override
  String get personalRules => '個人化規則';

  @override
  String get pushStatus => '推播狀態';

  @override
  String get connected => '已連線';

  @override
  String get connecting => '連線中…';

  @override
  String get disconnected => '未連線';

  @override
  String get sync => '同步';

  @override
  String syncPending(int count) {
    return '$count 項待同步';
  }

  @override
  String get syncUpToDate => '已是最新';

  @override
  String get server => '伺服器';

  @override
  String get privacy => '隱私說明';

  @override
  String get privacyBody =>
      'Moodle 等來源只保存登入工作階段，不保存統一認證密碼；學校信箱的應用程式專用密碼與工作階段均以 AES-GCM 加密保存；郵件只保存標題、寄件人、摘要與連結；可隨時刪除帳號與全部資料。';

  @override
  String get changePassword => '修改密碼';

  @override
  String get signOut => '登出';

  @override
  String get deleteAccount => '刪除帳號';

  @override
  String get language => '語言';

  @override
  String get languageEnglish => 'English';

  @override
  String get languageSimplified => '简体中文';

  @override
  String get languageTraditional => '繁體中文';

  @override
  String get inboxUnread => '未讀';

  @override
  String get inboxStarred => '收藏';

  @override
  String get inboxTodo => '待辦';

  @override
  String get inboxEvent => '行程';

  @override
  String get inboxNotice => '通知';

  @override
  String get inboxTrash => '回收桶';

  @override
  String get statusOpen => '待完成';

  @override
  String get statusDone => '已完成';

  @override
  String get statusActive => '未封存';

  @override
  String get statusArchived => '已封存';

  @override
  String get statusUnread => '未讀';

  @override
  String get statusRead => '已讀';

  @override
  String get statusAll => '全部';

  @override
  String get newLabel => '新建標籤';

  @override
  String get labels => '標籤';

  @override
  String get pinSidebar => '固定側欄';

  @override
  String get unpinSidebar => '取消固定';

  @override
  String get saved => '已儲存';

  @override
  String get classmate => '同學';

  @override
  String get justNow => '剛剛';

  @override
  String get never => '從未';

  @override
  String minutesAgo(int count) {
    return '$count 分鐘前';
  }

  @override
  String hoursAgo(int count) {
    return '$count 小時前';
  }

  @override
  String yesterdayAt(String time) {
    return '昨天 $time';
  }

  @override
  String get today => '今天';

  @override
  String get tomorrow => '明天';

  @override
  String get dayAfterTomorrow => '後天';

  @override
  String get yesterday => '昨天';

  @override
  String overdueHours(int count) {
    return '已截止 $count 小時';
  }

  @override
  String overdueDays(int count) {
    return '已截止 $count 天';
  }

  @override
  String remainingMinutes(int count) {
    return '還剩 $count 分鐘';
  }

  @override
  String remainingHours(int count) {
    return '還剩 $count 小時';
  }

  @override
  String remainingDaysHours(int days, int hours) {
    return '還剩 $days 天 $hours 小時';
  }

  @override
  String remainingDays(int count) {
    return '還剩 $count 天';
  }

  @override
  String get kindAssignment => '待辦任務';

  @override
  String get kindEvent => '行程活動';

  @override
  String get kindNotice => '通知';

  @override
  String get kindMail => '郵件';

  @override
  String get kindClip => '剪藏';

  @override
  String get kindPage => '網頁';

  @override
  String get kindItem => '事項';

  @override
  String get channelWeb => '網站';

  @override
  String get channelMail => '郵件';

  @override
  String get sourceOk => '正常';

  @override
  String get sourceFailed => '檢查失敗';

  @override
  String get sourceNeedLogin => '需要重新登入';

  @override
  String get sourceWaiting => '等待首次檢查';

  @override
  String get greetingLateNight => '夜深了';

  @override
  String get greetingMorning => '早安';

  @override
  String get greetingNoon => '午安';

  @override
  String get greetingAfternoon => '下午好';

  @override
  String get greetingEvening => '晚上好';

  @override
  String get priorityUrgent => '緊急';

  @override
  String get priorityNormal => '普通';

  @override
  String get priorityLow => '低';

  @override
  String get typeTodo => '待辦';

  @override
  String get typeEvent => '行程';

  @override
  String get typeNotice => '通知';

  @override
  String get markOpen => '標為待完成';

  @override
  String get markDone => '標為已完成';

  @override
  String get unarchive => '取消封存';

  @override
  String get archive => '封存';

  @override
  String get markUnread => '標為未讀';

  @override
  String get markRead => '標為已讀';

  @override
  String get fieldTitle => '標題';

  @override
  String get fieldSummary => '摘要';

  @override
  String get fieldType => '類型';

  @override
  String get fieldDeadline => '截止時間';

  @override
  String get fieldStart => '開始時間';

  @override
  String get fieldEnd => '結束時間';

  @override
  String get fieldLocation => '地點';

  @override
  String get fieldRequirements => '要求';

  @override
  String get emptyValue => '（空）';

  @override
  String get done => '已完成';

  @override
  String get deskTodayFocus => '今天要事';

  @override
  String get deskThisWeek => '本週';

  @override
  String get deskNeedsAttention => '需處理';

  @override
  String get deskCalendar => '日曆';

  @override
  String get deskHideCalendar => '收起日曆';

  @override
  String get deskDueIn7Days => '7 天內截止';

  @override
  String get deskSourceIssues => '資訊來源異常';

  @override
  String get deskShowMore => '顯示更多';

  @override
  String get deskInboxLink => '收件匣';

  @override
  String get filterAll => '全部';

  @override
  String get summary => '摘要';

  @override
  String get requirements => '要求';

  @override
  String get originalContent => '原文內容';

  @override
  String get sourceMonitor => '來源監測';

  @override
  String deadlineAt(String when) {
    return '截止於 $when';
  }

  @override
  String get openSource => '開啟原始來源';

  @override
  String get edit => '修改';

  @override
  String get notImportant => '不重要';

  @override
  String get copyLink => '複製連結';

  @override
  String get star => '收藏';

  @override
  String get unstar => '取消收藏';

  @override
  String get weekdayMon => '週一';

  @override
  String get weekdayTue => '週二';

  @override
  String get weekdayWed => '週三';

  @override
  String get weekdayThu => '週四';

  @override
  String get weekdayFri => '週五';

  @override
  String get weekdaySat => '週六';

  @override
  String get weekdaySun => '週日';

  @override
  String get generateQr => '產生 QR 碼';

  @override
  String get orEnterCode => '或輸入配對碼';

  @override
  String get codeHint => '6 位配對碼';

  @override
  String get join => '加入';

  @override
  String get scanQr => '掃描 QR 碼';

  @override
  String get codeValid30m => '配對碼 30 分鐘內有效';

  @override
  String get paired => '已配對';

  @override
  String get waitingPair => '等待配對…';

  @override
  String get sendFile => '傳送檔案';

  @override
  String get files => '檔案';

  @override
  String get noFilesYet => '還沒有檔案';

  @override
  String get send => '傳送';

  @override
  String get to => '收件人';

  @override
  String get ccOptional => '副本（選填）';

  @override
  String get subject => '主旨';

  @override
  String get bodyHint => '內文';

  @override
  String get addAttachment => '新增附件';

  @override
  String get recentSent => '最近傳送';

  @override
  String get noSubject => '（無主旨）';

  @override
  String get pleaseFillRecipient => '請填寫收件人';

  @override
  String get sent => '已傳送';

  @override
  String get duplicateSend => '這封郵件先前已傳送，沒有重複傳送';

  @override
  String sendFailed(String error) {
    return '傳送失敗：$error';
  }

  @override
  String get lastCheckFailed => '最近一次檢查失敗';

  @override
  String get lastSuccessCheck => '最後成功檢查';

  @override
  String get reason => '原因';

  @override
  String get failedAt => '失敗時間';

  @override
  String get nextCheck => '下次檢查';

  @override
  String get goHandle => '去處理';

  @override
  String get fieldBody => '正文';

  @override
  String operationFailed(String error) {
    return '操作失敗：$error';
  }

  @override
  String get pluginCapture => '外掛採集';

  @override
  String get alreadyStarted => '已開始';

  @override
  String get conflictBanner => '你改過的內容在來源裡也更新了，請確認保留哪一個';

  @override
  String mineValue(String value) {
    return '我的：$value';
  }

  @override
  String sourceValue(String value) {
    return '來源：$value';
  }

  @override
  String get keepMine => '保留我的';

  @override
  String get useSource => '採用來源';

  @override
  String get monitorUnsupported => '暫不支援自動檢查，可打開原始來源手動核對';

  @override
  String get monitorDisabled => '已關閉自動檢查';

  @override
  String get monitorPending => '已開啟，等待第一次檢查';

  @override
  String get monitorUnchanged => '最近一次檢查：無變化';

  @override
  String get monitorChanged => '最近一次檢查：發現變化';

  @override
  String get monitorFailed => '最近一次檢查失敗';

  @override
  String get errAuthExpired => '登入已過期：請在瀏覽器裡重新登入該網站';

  @override
  String get errForbidden => '沒有權限造訪該頁面';

  @override
  String get errNetwork => '網路錯誤';

  @override
  String get errNotFound => '頁面上找不到這條事項';

  @override
  String get errParseFailed => '頁面結構變了，暫時無法解析';

  @override
  String get errUnsupported => '該頁面不再支援自動檢查';

  @override
  String get lastSuccessNever => '還沒有';

  @override
  String lastSuccessCheckLine(String when) {
    return '最後成功檢查：$when';
  }

  @override
  String reasonLine(String reason) {
    return '原因：$reason';
  }

  @override
  String failedAtLine(String when) {
    return '失敗時間：$when';
  }

  @override
  String nextCheckLine(String when) {
    return '下次檢查：$when（需 Chrome 與本機後端運行）';
  }

  @override
  String get restoreSourceValue => '恢復來源值';

  @override
  String get willRestoreSource => '將恢復來源值';

  @override
  String get notSet => '未設定';

  @override
  String get choose => '選擇';

  @override
  String get clear => '清空';

  @override
  String get editItem => '修改事項';

  @override
  String get editItemHint => '修改只影響你看到的內容；來源更新不會覆蓋，若來源也改了會提示你確認。';

  @override
  String get editsSaved => '已儲存修改';

  @override
  String oldValue(String value) {
    return '舊：$value';
  }

  @override
  String newValue(String value) {
    return '新：$value';
  }

  @override
  String get filterTodoTasks => '待辦任務';

  @override
  String get filterEvents => '日程活動';

  @override
  String get filterNotices => '通知';

  @override
  String get todayShort => '今';

  @override
  String monthDay(int month, int day) {
    return '$month月$day日';
  }

  @override
  String scorePoints(num score) {
    return '$score 分';
  }

  @override
  String get webMaterial => '網頁資料';

  @override
  String get sourceDeleted => '來源已刪除';

  @override
  String originalTitle(String title) {
    return '原標題：$title';
  }

  @override
  String get sourceAndReliability => '來源與可靠性';

  @override
  String get unknownSource => '未知來源';

  @override
  String get lastSaved => '最後儲存';

  @override
  String get crossChannelMerge => '跨渠道合併';

  @override
  String sameItemMerged(String channels) {
    return '同一事項出現在 $channels，已合併為一條';
  }

  @override
  String get whyPushed => '為什麼推給你';

  @override
  String changedToType(String type) {
    return '已改為$type';
  }

  @override
  String get goWorkbench => '去工作台';

  @override
  String get changeTypeFailed => '修改類型失敗，請重試';

  @override
  String get notImportantToast => '已降低該來源的權重，系統會逐步貼合你的習慣';

  @override
  String get copiedTitleLink => '已複製標題與連結';

  @override
  String changeTypeCurrent(String type) {
    return '更改類型，目前為$type';
  }

  @override
  String get completed => '已完成';

  @override
  String get manuallyCorrected => '（已手動修正）';

  @override
  String get editHistory => '修改歷史';

  @override
  String versionsCount(int count) {
    return '$count 個版本';
  }

  @override
  String get firstSeen => '首次發現';

  @override
  String get contentUpdated => '內容更新';

  @override
  String get noDeadlines => '沒有截止';

  @override
  String get unreadStatus => '未讀';

  @override
  String attachmentsCount(int count) {
    return '$count 個附件';
  }

  @override
  String get deskEmptyToday => '今天沒有要緊的';

  @override
  String deskEmptyFilter(String filter) {
    return '暫無$filter';
  }

  @override
  String get statusChanged => '變更';

  @override
  String get statusUrgent => '緊急';

  @override
  String sourceNeedLoginNamed(String name) {
    return '「$name」需要重新登入';
  }

  @override
  String sourceCheckFailedNamed(String name) {
    return '「$name」檢查失敗';
  }

  @override
  String andMoreItems(int count) {
    return '等 $count 項';
  }

  @override
  String get summaryLlmHint => '由大模型生成 · 僅作導讀，以原文為準';

  @override
  String get summaryRuleHint => '規則提取 · 僅作導讀，以原文為準';

  @override
  String get attachments => '附件';

  @override
  String get sourceRawFields => '來源原始欄位';

  @override
  String get sfCourse => '課程';

  @override
  String get sfSemester => '學期';

  @override
  String get sfWeek => '週次';

  @override
  String get sfWeekday => '星期';

  @override
  String get sfPeriod => '節次';

  @override
  String get sfDatetime => '原始時間';

  @override
  String get sfOffice => '辦公室';

  @override
  String get sfDepartment => '部門';

  @override
  String get sfRole => '角色';

  @override
  String get sfPhone => '電話';

  @override
  String get sfEmail => '郵箱';

  @override
  String get sfSubtype => '資料類別';

  @override
  String get conditionSourceCheck => '條件來源檢查';

  @override
  String get viewSourceCheckSettings => '查看來源與檢查設定';

  @override
  String get browserSourceCheck => '瀏覽器來源檢查';

  @override
  String get snapshotOnlyNoBg => '僅儲存快照 · 暫不支援背景檢查';

  @override
  String get myNotes => '我的備註（來源更新不會覆蓋）';

  @override
  String get groupOverdue => '已過截止';

  @override
  String get groupNextWeek => '下週';

  @override
  String get groupLater => '之後';

  @override
  String get groupNoDeadline => '未設截止時間';

  @override
  String get assignments => '作業';

  @override
  String get noAssignmentsYet => '還沒有作業';

  @override
  String doneCount(int count) {
    return '$count 項已完成';
  }

  @override
  String get noNotices => '暫無通知';

  @override
  String get statusPending => '待完成';

  @override
  String get courseNeedNetwork => '課程資訊需要連網取得';

  @override
  String get courseNotFound => '找不到課程';

  @override
  String get backToCourses => '返回課程列表';

  @override
  String get markReadShort => '標為已讀';

  @override
  String get markUnreadShort => '標為未讀';

  @override
  String get addTodo => '加入待辦';

  @override
  String get removeTodo => '移出待辦';

  @override
  String get calMonth => '月';

  @override
  String get calTwoWeeks => '兩週';

  @override
  String get calWeek => '週';

  @override
  String get brandFallback => '拾';

  @override
  String get bcNotExecuted => '待首次檢查';

  @override
  String get bcUnchanged => '檢查成功 · 無變化';

  @override
  String get bcChanged => '已發現來源變化';

  @override
  String get bcNeedLogin => '請在學校原站重新登入';

  @override
  String get bcAccountMismatch => '學校帳號已切換 · 舊綁定已停止';

  @override
  String get bcSelectionMissing => '原文定位失效 · 需要重新採集';

  @override
  String get bcViewMismatch => '原學期／週次視圖失效 · 需要重新採集';

  @override
  String get bcRouteMismatch => '來源路由已改變 · 需要重新採集';

  @override
  String get bcRenderTimeout => '頁面載入逾時';

  @override
  String get bcPermissionDenied => '瀏覽器來源權限不足';

  @override
  String get bcUnsupported => '暫不支援監測';

  @override
  String get bcFailed => '檢查失敗';

  @override
  String get rrRejected => '檢查結果校驗失敗 · 資料保留，監測已暫停';

  @override
  String get rrPurged => '關聯資料已徹底刪除 · 請在原網頁重新提取';

  @override
  String get rrStarting => '自動監測啟動中 · 等待首次刷新';

  @override
  String get rrUserBusy => '監測頁正在編輯 · 延後刷新';

  @override
  String get rrTabMissing => '監測頁已關閉 · 請打開原頁後重新綁定';

  @override
  String get rrTabRebind => '瀏覽器工作階段已重啟 · 請重新綁定監測頁';

  @override
  String get rrTabAmbiguous => '打開了多個相同網頁 · 請保留一個監測頁';

  @override
  String get rrSingleAccount => '本站已綁定另一帳號 · 已暫停';

  @override
  String get rrRestored => '來源已恢復 · 檢查暫停，須重新測試';

  @override
  String get rrDocsRestored => '資料已恢復 · 來源檢查保持暫停';

  @override
  String get rrDocsTrashed => '關聯資料已移入回收站 · 檢查已暫停';

  @override
  String get rrPrivateRequired => '偵測到登入帳號 · 請按需要登入的來源重新採集';

  @override
  String get rrVerified => '重讀驗證通過 · 待檢查';

  @override
  String get rrAccountUnknown => '無法核對來源帳號 · 保留手動採集';

  @override
  String get rrAccountMismatch => '來源帳號不符 · 已暫停';

  @override
  String get rrNoMatch => '本次未匹配 · 已保留舊資料';

  @override
  String get rrPreviewOnly => '本次內容不完整 · 未覆蓋資料';

  @override
  String get rrUnsupported => '暫不支援背景重讀';

  @override
  String get rrWorkerInterrupted => '瀏覽器任務中斷 · 可重試';

  @override
  String get deadlineCalendar => '截止日曆';

  @override
  String get rsExpired => '檢查已逾時 · 等待瀏覽器重試';

  @override
  String get rsQueued => '已排隊 · 等待執行';

  @override
  String get rsChecking => '瀏覽器檢查中';

  @override
  String get rsWaitChrome => '等待本機 Chrome';

  @override
  String get rsLoginReuse => '複用目前 Chrome 工作階段（使用者確認）';

  @override
  String get rsLoginNone => '無需登入（聲明）';

  @override
  String get rsLoginRequired => '需要登入';

  @override
  String get rsIdResidentGeneric => '專用監測頁 · 單帳號工作階段（使用者確認）';

  @override
  String get rsIdResidentSchool => '原學校帳號 · 專用監測頁';

  @override
  String get rsIdPublic => '無需登入（使用者聲明）';

  @override
  String get rsAccountUnchecked => '帳號未核對';

  @override
  String get rsIdSchoolChrome => '原學校帳號 · 本機 Chrome';

  @override
  String get rsTitleTimeline => 'Moodle 活動摘要';

  @override
  String get rsTitleTeacher => '教師資料';

  @override
  String get rsTitleWeb => '網頁資料';

  @override
  String get rsScopeTitle => '標題與連結標題';

  @override
  String get rsScopeTimeline => '目前已載入活動 · 摘要整組';

  @override
  String get rsScopeBody => '正文與列表 · 整組匹配';

  @override
  String get rsScopeOriginal => '原條件與約定視圖';

  @override
  String get rsWaitLocalChrome => '等待本機 Chrome 執行';

  @override
  String get rsStartingCheck => '正在啟動／檢查';

  @override
  String get rsPeriodicPaused => '定期監測已暫停';

  @override
  String get rsPartialPaused => '部分規則已暫停';

  @override
  String get rsPeriodicOn => '定期監測中';

  @override
  String get rsManualOnly => '僅手動檢查';

  @override
  String get rsAwaitFirstRefresh => '等待首次刷新';

  @override
  String get rsDedicatedMonitor => '專用監測頁';

  @override
  String labelCreated(String name) {
    return '已建立「$name」';
  }

  @override
  String labelDeleted(String name) {
    return '已刪除「$name」';
  }

  @override
  String deleteLabelTitle(String name) {
    return '刪除「$name」？';
  }

  @override
  String get deleteLabelBody => '事項上的該標籤會一併去掉，收藏星標不受影響。';

  @override
  String get actionDelete => '刪除';

  @override
  String get searchInboxHint => '搜尋標題、課程、來源';

  @override
  String get inboxEmptyFilter => '目前篩選沒有事項';

  @override
  String get tagItem => '替事項加上標籤';

  @override
  String get loadingLabels => '正在載入標籤';

  @override
  String get labelsLoadFailed => '標籤載入失敗';

  @override
  String get retry => '重試';

  @override
  String get noLabelsYet => '還沒有標籤，可以先建立一個。';

  @override
  String get newLabelAction => '新建標籤';

  @override
  String get labelNameHint => '例如：收藏、作業、社團';

  @override
  String get color => '顏色';

  @override
  String get create => '建立';

  @override
  String get movedToTrash => '已移入回收站，資料與歷史保留。';

  @override
  String get restoredItem => '已恢復資料；來源檢查保持暫停。';

  @override
  String get undo => '撤銷';

  @override
  String get accountChanged => '工作台帳號已變化';

  @override
  String restoreIncomplete(String error) {
    return '恢復未完成：$error';
  }

  @override
  String actionUnconfirmed(String error) {
    return '操作未確認：$error';
  }

  @override
  String get restoreToInbox => '恢復到收件匣';

  @override
  String get moveToTrash => '移入回收站';

  @override
  String get cannotOpenItem => '無法打開這條事項';

  @override
  String get itemNotFound => '事項不存在或不屬於目前帳號。請確認工作台與外掛使用同一拾課 Gleaner 郵箱。';

  @override
  String get loginExpired => '登入已失效，請在工作台重新登入。';

  @override
  String get detailLoadFailed => '未能讀取詳情，請檢查後端連線後重試。';

  @override
  String currentDeskAccount(String email) {
    return '目前工作台帳號：$email';
  }

  @override
  String get notSignedIn => '未登入';

  @override
  String get backToSources => '返回資訊源';

  @override
  String get notProvided => '未提供';

  @override
  String get sourceDeadline => '來源截止時間';

  @override
  String get submitRequirements => '提交要求';

  @override
  String get sourceFields => '來源欄位';

  @override
  String beforeChange(String value) {
    return '變更前：\n$value';
  }

  @override
  String afterChange(String value) {
    return '變更後：\n$value';
  }

  @override
  String timelineMaterial(int count) {
    return '活動摘要資料 · $count 條活動';
  }

  @override
  String webSnapshot(int count) {
    return '網頁資料快照 · $count 個片段';
  }

  @override
  String activityN(int n, String title) {
    return '活動 $n：$title';
  }

  @override
  String fragmentN(int n, String title) {
    return '片段 $n：$title';
  }

  @override
  String get openActivity => '打開活動詳情';

  @override
  String courseField(String value) {
    return '課程：$value';
  }

  @override
  String wcCond(String value) {
    return '條件：$value';
  }

  @override
  String get wcIdentitySchool => '來源身分：原學校帳號 · 本機 Chrome';

  @override
  String get wcScopeTimeline => '範圍：目前已載入 Timeline 活動';

  @override
  String get wcMatchTitle => '匹配位置：標題與連結標題';

  @override
  String get wcMatchBody => '匹配位置：正文與列表';

  @override
  String wcAlias(String value) {
    return '來源別名：$value';
  }

  @override
  String get wcLoginNone => '原站登入要求：無需登入（使用者聲明）';

  @override
  String get wcLoginRequired => '原站登入要求：需要登入';

  @override
  String wcAccount(String value) {
    return '來源帳號：$value';
  }

  @override
  String get wcAccountUnchecked => '未核對';

  @override
  String get wcPrivateOnly => '資料可見：僅自己';

  @override
  String get wcTimelineHint =>
      '這是活動提醒摘要，未讀取詳情正文，不代表完整作業或已確認的日曆事件。日期與時間均保留原文，缺失時不推測。';

  @override
  String get wcLinkedHint => '僅約定視圖中的匹配片段，不代表完整文章或郵件。原條件已關聯資訊源，檢查方式與狀態請在來源中查看。';

  @override
  String get wcUnlinkedHint => '僅目前已載入內容，不代表完整文章或郵件。來源別名由使用者聲明；來源檢查未啟用。';

  @override
  String get wcUpdateOnChange => '檢查成功且內容變化時更新同一資料的來源版本，個人備註與狀態保留。';

  @override
  String get wcUpdateOnRecapture => '同來源標籤、URL、條件及範圍，重新提取並明確儲存後更新本資料版本。';

  @override
  String wcDateText(String value) {
    return '日期原文：$value';
  }

  @override
  String wcTimeText(String value) {
    return '時間原文：$value';
  }

  @override
  String wcDomEvidence(String value) {
    return 'DOM 依據：$value';
  }

  @override
  String get aliasMissing => '未提供';

  @override
  String get changeNoteSep => '；';

  @override
  String get changeNameSep => '、';

  @override
  String changeDays(int count) {
    return '$count 天';
  }

  @override
  String changeHours(int count) {
    return '$count 小時';
  }

  @override
  String changeDeadlineAdvanced(String span, String from, String to) {
    return '截止提前 $span（$from → $to）';
  }

  @override
  String changeDeadlinePostponed(String span, String from, String to) {
    return '截止延後 $span（$from → $to）';
  }

  @override
  String changeDeadlineAdded(String when) {
    return '新增截止時間 $when';
  }

  @override
  String get changeDeadlineRemoved => '截止時間被移除';

  @override
  String changeAttachmentReplaced(String names) {
    return '附件替換：$names';
  }

  @override
  String changeAttachmentAdded(String names) {
    return '新增附件：$names';
  }

  @override
  String changeAttachmentRemoved(String names) {
    return '附件被移除：$names';
  }

  @override
  String get changeAttachmentUpdated => '附件內容更新';

  @override
  String get changeRequirements => '提交要求變化';

  @override
  String get changeEventTime => '活動時間變化';

  @override
  String get changeLocation => '地點變化';

  @override
  String get changeType => '類型變化';

  @override
  String get changeTitle => '標題修改';

  @override
  String get changeWording => '內容措辭調整';

  @override
  String get sourceSessionExpired => '登入工作階段已失效，請到「來源」重新登入';

  @override
  String get eventReminder => '截止提醒';

  @override
  String get eventImportantChange => '重要變更';

  @override
  String get eventNewItem => '新事項';

  @override
  String get digestTitle => '今日摘要';

  @override
  String digestBody(int newCount, int upcoming) {
    return '過去 24 小時 $newCount 條新事項，$upcoming 項即將截止';
  }

  @override
  String get reasonBlocked => '命中屏蔽詞';

  @override
  String reasonKeyword(String words) {
    return '關鍵詞：$words';
  }

  @override
  String get reasonDue24h => '24 小時內截止';

  @override
  String get reasonDue7d => '7 天內截止';

  @override
  String get reasonYourCourse => '你的課程';

  @override
  String get reasonCourseItem => '課程事項';

  @override
  String get reasonGradeMajorMatch => '符合你的年級/專業';

  @override
  String get reasonOtherAudience => '面向其他年級或專業';

  @override
  String get reasonImportantChange => '重要變更';

  @override
  String get errMoodleNeedLogin => '尚未登入該 Moodle 來源';

  @override
  String get courseOpenCount => '待完成';

  @override
  String get noCoursesYet => '還沒有課程';

  @override
  String get noCoursesHint => '新增 Moodle 來源後，每門課會有一個主頁。新增「教師資訊」範本可補上老師辦公室與信箱。';

  @override
  String get noCourseTodos => '暫無待辦';

  @override
  String get addFacultySourceHint => '新增「教師資訊」來源以顯示老師聯絡方式';

  @override
  String get captureFromWeb => '從網頁採集';

  @override
  String get refreshSourceListTooltip => '重新整理列表狀態（不造訪來源網頁）';

  @override
  String get cannotReadSources => '無法讀取資訊源';

  @override
  String get savedPages => '已儲存頁面';

  @override
  String get periodicRules => '定期規則';

  @override
  String get needsAttention => '需要處理';

  @override
  String get changesFound => '本次發現變化';

  @override
  String get mySources => '我的資訊源';

  @override
  String get noReadingSources => '還沒有保留原條件的資訊源。請在原網頁透過外掛擷取、預覽並儲存。';

  @override
  String get monitorTabHint =>
      '專用監測分頁需保持開啟；可關閉工作台頁面。請保持 Chrome、擴充功能與本機服務運行，檢查可能延後。';

  @override
  String deletedSourcesTitle(int count) {
    return '已刪除來源（$count）';
  }

  @override
  String get deletedSourcesSubtitle => '復原後保持暫停；徹底刪除會永久清除關聯資料與歷史。';

  @override
  String deletedSourcesUnavailable(String error) {
    return '已刪除來源暫不可用：$error';
  }

  @override
  String get legacyDemoTitle => '舊資料與示範訂閱';

  @override
  String get legacyDemoSubtitle => '保留既有資料；缺少原條件時請開啟原網頁重新採集。';

  @override
  String get chromeConnectedHint => '本機 Chrome 近期已連線 · 原站登入狀態逐來源檢查';

  @override
  String get chromeDisconnectedHint => '尚未偵測到執行裝置近期連線 · 保留上次成功結果';

  @override
  String get checkQueued => '檢查已排隊；結果確認後更新狀態。';

  @override
  String get periodicResumed => '定期檢查已恢復。';

  @override
  String get periodicPaused => '定期檢查已暫停，仍可手動檢查。';

  @override
  String get pageCheckQueued => '整頁檢查已排隊；同頁規則共享重新整理。';

  @override
  String get pagePlanUpdated => '整頁監測計畫已更新。';

  @override
  String get sourceDeletedKeep => '來源已刪除，資料與歷史保留。';

  @override
  String get sourceDeletedTrash => '來源已刪除，關聯資料已移入回收筒。';

  @override
  String get deleteSourceTitle => '刪除資訊源？';

  @override
  String get deleteSourceBody =>
      '停止此來源的手動與定期檢查。預設保留已儲存資料、備註及歷史版本。可從「已刪除來源」手動復原；舊任務不會自動恢復。';

  @override
  String get deleteSourceAlsoTrash => '同時將關聯資料移入個人回收筒';

  @override
  String get deleteSourceAlsoTrashHint => '也會在引用這些資料的其他來源中隱藏；可從收件匣回收筒復原。';

  @override
  String get deleteSourceAction => '刪除來源';

  @override
  String get restoreSourceAction => '復原來源';

  @override
  String get purgeForever => '徹底刪除';

  @override
  String get checkStoppedKept => '檢查已停止 · 資料與歷史依原選擇保留';

  @override
  String get sourceRestoredPaused => '來源已復原並暫停；請重新測試重讀。';

  @override
  String get manageLegacySources => '管理舊範本／示範來源';

  @override
  String get legacyCaptureSubtitle => '舊採集資料 · 未自動遷入條件監測';

  @override
  String legacyCapturesFailed(String error) {
    return '舊資料讀取失敗：$error';
  }

  @override
  String statusRefreshFailed(String error) {
    return '狀態重新整理失敗：$error';
  }

  @override
  String get profileTitle => '個人資料';

  @override
  String get coursesCommaHint => '我的課程（用、分隔）';

  @override
  String get coursesHintSample => '網路程式設計、作業系統';

  @override
  String get gradeHintSample => '2024級';

  @override
  String get majorHintSample => '電腦科學';

  @override
  String get profileMatchHint => '年級、專業與課程用於判斷通知是否與你相關。';

  @override
  String get quietStartHelp => '免打擾開始';

  @override
  String get quietEndHelp => '免打擾結束';

  @override
  String get digestTimeHelp => '每日摘要時間';

  @override
  String get currentPassword => '目前密碼';

  @override
  String get newPasswordMin8 => '新密碼（至少 8 位）';

  @override
  String get passwordChangedToast => '密碼已修改，其他裝置需要重新登入';

  @override
  String get confirmChangePassword => '確認修改';

  @override
  String get deleteAccountTitle => '刪除帳號？';

  @override
  String get deleteAccountBody => '將刪除你的帳號、訂閱、登入工作階段、個人狀態與寄信紀錄，且無法復原。請輸入密碼確認。';

  @override
  String get deleteForever => '永久刪除';

  @override
  String get rulesSavedToast => '規則已儲存，對之後的新事項生效';

  @override
  String get priorityFormula =>
      '優先級 = 100 ×（0.30 來源權重 + 0.25 關鍵詞 + 0.25 截止臨近 + 0.20 與你匹配）';

  @override
  String get priorityBands => '≥ 80 緊急（推送到手機）· 40–79 普通 · < 40 只進資訊流與摘要';

  @override
  String get ruleKeyword => '關鍵詞';

  @override
  String get ruleSenderWhitelist => '白名單寄件人';

  @override
  String get ruleKeywordHint => '例如：保研、獎學金';

  @override
  String get ruleBlock => '屏蔽';

  @override
  String get actionAdd => '新增';

  @override
  String get noCustomRules => '還沒有自訂規則';

  @override
  String get defaultKeywordsHint => '預設關鍵詞：截止、deadline、考試、調課、取消。';

  @override
  String get teachersHeader => '教師';

  @override
  String get orEnterPairCode => '或輸入配對碼';

  @override
  String get pairCodeHint => '6 位配對碼';

  @override
  String get joinPair => '加入';

  @override
  String get pairCodeTtl => '配對碼 30 分鐘內有效';

  @override
  String get filesHeader => '檔案';

  @override
  String transferCorrupt(String name) {
    return '「$name」校驗失敗，請重新傳送';
  }

  @override
  String transferPaused(String name) {
    return '網路中斷，「$name」已暫停';
  }

  @override
  String get deviceBrowser => '瀏覽器';

  @override
  String purgeTitle(String title) {
    return '徹底刪除「$title」？';
  }

  @override
  String purgeBody(int items, int versions, int checks) {
    return '將永久刪除此來源、$items 份關聯資料、$versions 個歷史版本及 $checks 條檢查紀錄。包括收件匣與回收筒中的關聯資料、個人備註與狀態。';
  }

  @override
  String purgeRemovedRules(int count) {
    return '另有 $count 條規則只引用這些資料，將一併移除。';
  }

  @override
  String purgePausedRules(int count) {
    return '另有 $count 條規則包含這些資料，將暫停並要求重新擷取；其餘資料保留。';
  }

  @override
  String get purgePreviewInvalidate =>
      '此帳號之前未完成的採集預覽將統一失效，需要重新擷取。其他已儲存資料保留。外掛離線時，舊快取會在重新連線後清理。';

  @override
  String get purgeIrreversible => '此操作不可復原。之後可以重新採集同一網頁與條件，作為新資料儲存。';

  @override
  String get purgeConfirmCheck => '我確認永久刪除上述資料與歷史版本';

  @override
  String get sourcePurgedOk => '來源、關聯資料與歷史已徹底刪除。請重新擷取後儲存。';

  @override
  String sourcePurgedPartial(String error) {
    return '伺服器已徹底刪除；本機快取清理待重試：$error';
  }

  @override
  String get accountChangedConfirm => '工作台帳號已變化，請重新確認。';
}
