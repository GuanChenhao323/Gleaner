import 'package:flutter/material.dart';
import 'package:intl/intl.dart';

import '../l10n/app_localizations.dart';
import '../theme.dart';
import 'models.dart';

AppLocalizations _l10n(BuildContext context) => AppLocalizations.of(context);

String _hm(AppLocalizations l10n, DateTime t) => DateFormat.Hm(l10n.localeName).format(t);
String _md(AppLocalizations l10n, DateTime t) => DateFormat.MMMd(l10n.localeName).format(t);
String _ymd(AppLocalizations l10n, DateTime t) => DateFormat.yMMMd(l10n.localeName).format(t);

String weekday(DateTime d, BuildContext context) {
  final l10n = _l10n(context);
  return switch (d.weekday) {
    1 => l10n.weekdayMon,
    2 => l10n.weekdayTue,
    3 => l10n.weekdayWed,
    4 => l10n.weekdayThu,
    5 => l10n.weekdayFri,
    6 => l10n.weekdaySat,
    _ => l10n.weekdaySun,
  };
}

String relative(DateTime? t, BuildContext context, {DateTime? now}) {
  final l10n = _l10n(context);
  if (t == null) return l10n.never;
  final n = now ?? DateTime.now();
  final diff = n.difference(t);
  if (diff.isNegative) return absolute(t, context);
  if (diff.inMinutes < 1) return l10n.justNow;
  if (diff.inMinutes < 60) return l10n.minutesAgo(diff.inMinutes);
  if (diff.inHours < 24 && t.day == n.day) return l10n.hoursAgo(diff.inHours);
  final y = n.subtract(const Duration(days: 1));
  if (t.year == y.year && t.month == y.month && t.day == y.day) return l10n.yesterdayAt(_hm(l10n, t));
  if (diff.inDays < 7) return '${weekday(t, context)} ${_hm(l10n, t)}';
  return t.year == n.year ? _md(l10n, t) : _ymd(l10n, t);
}

String absolute(DateTime t, BuildContext context) {
  final l10n = _l10n(context);
  final n = DateTime.now();
  final day = t.year == n.year ? _md(l10n, t) : _ymd(l10n, t);
  return '$day ${weekday(t, context)} ${_hm(l10n, t)}';
}

String dayLabel(DateTime d, BuildContext context) {
  final l10n = _l10n(context);
  final n = DateTime.now();
  final today = DateTime(n.year, n.month, n.day);
  final dd = DateTime(d.year, d.month, d.day);
  final delta = dd.difference(today).inDays;
  if (delta == 0) return l10n.today;
  if (delta == 1) return l10n.tomorrow;
  if (delta == 2) return l10n.dayAfterTomorrow;
  if (delta == -1) return l10n.yesterday;
  return '${_md(l10n, d)} ${weekday(d, context)}';
}

String countdown(DateTime due, BuildContext context, {DateTime? now}) {
  final l10n = _l10n(context);
  final n = now ?? DateTime.now();
  final d = due.difference(n);
  if (d.isNegative) {
    final p = n.difference(due);
    if (p.inHours < 24) return l10n.overdueHours(p.inHours);
    return l10n.overdueDays(p.inDays);
  }
  if (d.inMinutes < 60) return l10n.remainingMinutes(d.inMinutes);
  if (d.inHours < 24) return l10n.remainingHours(d.inHours);
  final days = d.inDays;
  final hours = d.inHours - days * 24;
  return hours > 0 && days < 3 ? l10n.remainingDaysHours(days, hours) : l10n.remainingDays(days);
}

enum Urgency { overdue, critical, soon, later, none }

Urgency urgencyOf(DateTime? due) {
  if (due == null) return Urgency.none;
  final h = due.difference(DateTime.now()).inHours;
  if (h < 0) return Urgency.overdue;
  if (h < 24) return Urgency.critical;
  if (h < 72) return Urgency.soon;
  return Urgency.later;
}

Color urgencyColor(BuildContext context, Urgency u) {
  final s = Theme.of(context).colorScheme;
  return switch (u) {
    Urgency.overdue => Brand.dueOverdue,
    Urgency.critical => Brand.dueCritical,
    Urgency.soon => Brand.dueSoon,
    Urgency.later => s.onSurfaceVariant,
    Urgency.none => s.outline,
  };
}

Color? dueRowAccent({required bool done, required String priority, DateTime? deadline}) {
  if (done) return null;
  if (priority == 'urgent') return Brand.dueCritical;
  return switch (urgencyOf(deadline)) {
    Urgency.critical => Brand.dueCritical,
    Urgency.overdue => Brand.dueOverdue,
    Urgency.soon => Brand.dueSoon,
    _ => null,
  };
}

String kindLabel(String kind, BuildContext context) {
  final l10n = _l10n(context);
  return switch (kind) {
    'assignment' => l10n.kindAssignment,
    'event' => l10n.kindEvent,
    'notice' => l10n.kindNotice,
    'mail' => l10n.kindMail,
    'rss' => l10n.kindNotice,
    'clip' => l10n.kindClip,
    'page' => l10n.kindPage,
    _ => l10n.kindItem,
  };
}

IconData kindIcon(String kind) => switch (kind) {
      'event' => Icons.event_outlined,
      'assignment' => Icons.assignment_outlined,
      'notice' => Icons.campaign_outlined,
      'mail' => Icons.mail_outline,
      'clip' => Icons.bookmark_add_outlined,
      'page' => Icons.web,
      _ => Icons.article_outlined,
    };

IconData sourceIcon(String type) => switch (type) {
      'moodle' => Icons.school_outlined,
      'web' => Icons.public,
      'rss' => Icons.rss_feed,
      'teacher' => Icons.badge_outlined,
      'imap' || 'pop3' => Icons.mail_outline,
      'browser' => Icons.web,
      'clip' => Icons.bookmarks_outlined,
      _ => Icons.link,
    };

IconData templateIcon(String name) => switch (name) {
      'school' => Icons.school_outlined,
      'campaign' => Icons.campaign_outlined,
      'rss_feed' => Icons.rss_feed,
      'badge' => Icons.badge_outlined,
      'mail' => Icons.mail_outline,
      'mark_email_unread' => Icons.mark_email_unread_outlined,
      _ => Icons.link,
    };

String channelLabel(String c, BuildContext context) {
  final l10n = _l10n(context);
  return switch (c) {
    'moodle' => 'Moodle',
    'web' => l10n.channelWeb,
    'rss' => 'RSS',
    'imap' => l10n.channelMail,
    'pop3' => l10n.channelMail,
    _ => c,
  };
}

({String label, Color color, IconData icon}) sourceStatus(BuildContext context, Source s) {
  final l10n = _l10n(context);
  final cs = Theme.of(context).colorScheme;
  return switch (s.status) {
    'ok' => (label: l10n.sourceOk, color: Brand.ok, icon: Icons.check_circle),
    'failed' => (label: l10n.sourceFailed, color: cs.error, icon: Icons.error),
    'need_login' => (label: l10n.sourceNeedLogin, color: Brand.wheat, icon: Icons.lock_clock),
    _ => (label: l10n.sourceWaiting, color: cs.outline, icon: Icons.hourglass_top),
  };
}

String shortCourse(String course) {
  final parts = course.split(' ');
  return parts.length > 1 && RegExp(r'^[A-Z]{2,5}\d{3,5}$').hasMatch(parts.first) ? parts.sublist(1).join(' ') : course;
}

String greeting(BuildContext context) {
  final l10n = _l10n(context);
  final h = DateTime.now().hour;
  if (h < 5) return l10n.greetingLateNight;
  if (h < 11) return l10n.greetingMorning;
  if (h < 13) return l10n.greetingNoon;
  if (h < 18) return l10n.greetingAfternoon;
  return l10n.greetingEvening;
}

bool sameDay(DateTime a, DateTime b) => a.year == b.year && a.month == b.month && a.day == b.day;

String priorityLabel(String p, BuildContext context) {
  final l10n = _l10n(context);
  return switch (p) {
    'urgent' => l10n.priorityUrgent,
    'normal' => l10n.priorityNormal,
    _ => l10n.priorityLow,
  };
}

DateTime? itemDeadline(Item i) => i.deadline;

/// Localize server-generated change notes (always stored in zh-CN).
String localizeChangeNote(String note, BuildContext context) {
  final l10n = _l10n(context);
  if (note.trim().isEmpty) return note;
  final parts = note.split('；');
  return parts
      .map((p) => _localizeChangePart(p.trim(), l10n))
      .where((s) => s.isNotEmpty)
      .join(l10n.changeNoteSep);
}

String _localizeChangePart(String part, AppLocalizations l10n) {
  if (part.isEmpty) return part;

  final advanced = RegExp(r'^截止提前 (.+?)（(.+?) → (.+?)）$').firstMatch(part);
  if (advanced != null) {
    return l10n.changeDeadlineAdvanced(
      _localizeChangeSpan(advanced.group(1)!, l10n),
      advanced.group(2)!,
      advanced.group(3)!,
    );
  }
  final postponed = RegExp(r'^截止推迟 (.+?)（(.+?) → (.+?)）$').firstMatch(part);
  if (postponed != null) {
    return l10n.changeDeadlinePostponed(
      _localizeChangeSpan(postponed.group(1)!, l10n),
      postponed.group(2)!,
      postponed.group(3)!,
    );
  }
  final added = RegExp(r'^新增截止时间 (.+)$').firstMatch(part);
  if (added != null) return l10n.changeDeadlineAdded(added.group(1)!);
  if (part == '截止时间被移除') return l10n.changeDeadlineRemoved;

  final replaced = RegExp(r'^附件替换：(.+)$').firstMatch(part);
  if (replaced != null) {
    return l10n.changeAttachmentReplaced(_localizeNameList(replaced.group(1)!, l10n));
  }
  final attAdded = RegExp(r'^新增附件：(.+)$').firstMatch(part);
  if (attAdded != null) {
    return l10n.changeAttachmentAdded(_localizeNameList(attAdded.group(1)!, l10n));
  }
  final attRemoved = RegExp(r'^附件被移除：(.+)$').firstMatch(part);
  if (attRemoved != null) {
    return l10n.changeAttachmentRemoved(_localizeNameList(attRemoved.group(1)!, l10n));
  }
  if (part == '附件内容更新') return l10n.changeAttachmentUpdated;
  if (part == '提交要求变化') return l10n.changeRequirements;
  if (part == '活动时间变化') return l10n.changeEventTime;
  if (part == '地点变化') return l10n.changeLocation;
  if (part == '类型变化') return l10n.changeType;
  if (part == '标题修改') return l10n.changeTitle;
  if (part == '内容措辞调整') return l10n.changeWording;
  return part;
}

String _localizeChangeSpan(String span, AppLocalizations l10n) {
  final days = RegExp(r'^(\d+)\s*天$').firstMatch(span);
  if (days != null) return l10n.changeDays(int.parse(days.group(1)!));
  final hours = RegExp(r'^(\d+)\s*小时$').firstMatch(span);
  if (hours != null) return l10n.changeHours(int.parse(hours.group(1)!));
  return span;
}

String _localizeNameList(String names, AppLocalizations l10n) =>
    names.split('、').where((s) => s.isNotEmpty).join(l10n.changeNameSep);

/// Localize server score/match reasons (always stored in zh-CN).
String localizeReasons(List<String> reasons, BuildContext context) {
  final l10n = _l10n(context);
  return reasons.map((r) => localizeReason(r, l10n)).where((s) => s.isNotEmpty).join(' · ');
}

String localizeReason(String reason, AppLocalizations l10n) {
  final r = reason.trim();
  if (r.isEmpty) return r;
  if (r == '命中屏蔽词') return l10n.reasonBlocked;
  if (r == '24 小时内截止') return l10n.reasonDue24h;
  if (r == '7 天内截止') return l10n.reasonDue7d;
  if (r == '你的课程') return l10n.reasonYourCourse;
  if (r == '课程事项') return l10n.reasonCourseItem;
  if (r == '符合你的年级/专业') return l10n.reasonGradeMajorMatch;
  if (r == '面向其他年级或专业') return l10n.reasonOtherAudience;
  if (r == '重要变更') return l10n.reasonImportantChange;
  final kw = RegExp(r'^关键词：(.+)$').firstMatch(r);
  if (kw != null) {
    return l10n.reasonKeyword(kw.group(1)!.split('、').where((s) => s.isNotEmpty).join(l10n.changeNameSep));
  }
  return r;
}

String localizeMonitorReason(MonitorInfo m, AppLocalizations l10n) {
  final coded = switch (m.errorCode) {
    'auth_expired' || 'need_login' => l10n.errAuthExpired,
    'forbidden' => l10n.errForbidden,
    'network' || 'failed' => l10n.errNetwork,
    'not_found' => l10n.errNotFound,
    'parse_failed' => l10n.errParseFailed,
    'unsupported' => l10n.errUnsupported,
    _ => '',
  };
  if (coded.isNotEmpty) return coded;
  final msg = m.errorMessage.trim();
  if (msg == '尚未登录该 Moodle 来源') return l10n.errMoodleNeedLogin;
  if (msg.isNotEmpty) return msg;
  return m.errorCode;
}
