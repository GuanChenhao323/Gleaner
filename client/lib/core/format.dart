import 'package:flutter/material.dart';
import 'package:intl/intl.dart';

import '../theme.dart';
import 'models.dart';

final _md = DateFormat('M月d日');
final _hm = DateFormat('HH:mm');
final _ymd = DateFormat('yyyy年M月d日');
const _weekdays = ['周一', '周二', '周三', '周四', '周五', '周六', '周日'];

String weekday(DateTime d) => _weekdays[d.weekday - 1];

/// “最后检查：10 分钟前”这类相对时间。
String relative(DateTime? t, {DateTime? now}) {
  if (t == null) return '从未';
  final n = now ?? DateTime.now();
  final diff = n.difference(t);
  if (diff.isNegative) return absolute(t);
  if (diff.inMinutes < 1) return '刚刚';
  if (diff.inMinutes < 60) return '${diff.inMinutes} 分钟前';
  if (diff.inHours < 24 && t.day == n.day) return '${diff.inHours} 小时前';
  final y = n.subtract(const Duration(days: 1));
  if (t.year == y.year && t.month == y.month && t.day == y.day) return '昨天 ${_hm.format(t)}';
  if (diff.inDays < 7) return '${weekday(t)} ${_hm.format(t)}';
  return t.year == n.year ? _md.format(t) : _ymd.format(t);
}

String absolute(DateTime t) {
  final n = DateTime.now();
  final day = t.year == n.year ? _md.format(t) : _ymd.format(t);
  return '$day ${weekday(t)} ${_hm.format(t)}';
}

String dayLabel(DateTime d) {
  final n = DateTime.now();
  final today = DateTime(n.year, n.month, n.day);
  final dd = DateTime(d.year, d.month, d.day);
  final delta = dd.difference(today).inDays;
  if (delta == 0) return '今天';
  if (delta == 1) return '明天';
  if (delta == 2) return '后天';
  if (delta == -1) return '昨天';
  return '${_md.format(d)} ${weekday(d)}';
}

/// 截止倒计时：“还剩 2 天 3 小时”“已截止 1 天”。
String countdown(DateTime due, {DateTime? now}) {
  final n = now ?? DateTime.now();
  final d = due.difference(n);
  if (d.isNegative) {
    final p = n.difference(due);
    if (p.inHours < 24) return '已截止 ${p.inHours} 小时';
    return '已截止 ${p.inDays} 天';
  }
  if (d.inMinutes < 60) return '还剩 ${d.inMinutes} 分钟';
  if (d.inHours < 24) return '还剩 ${d.inHours} 小时';
  final days = d.inDays;
  final hours = d.inHours - days * 24;
  return hours > 0 && days < 3 ? '还剩 $days 天 $hours 小时' : '还剩 $days 天';
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
    Urgency.overdue => s.outline,
    Urgency.critical => Brand.urgent,
    Urgency.soon => Brand.wheat,
    Urgency.later => s.primary,
    Urgency.none => s.outline,
  };
}

String kindLabel(String kind) => switch (kind) {
      'assignment' => '作业',
      'notice' => '通知',
      'mail' => '邮件',
      'rss' => '通知',
      _ => '事项',
    };

IconData kindIcon(String kind) => switch (kind) {
      'assignment' => Icons.assignment_outlined,
      'notice' => Icons.campaign_outlined,
      'mail' => Icons.mail_outline,
      _ => Icons.article_outlined,
    };

IconData sourceIcon(String type) => switch (type) {
      'moodle' => Icons.school_outlined,
      'web' => Icons.public,
      'rss' => Icons.rss_feed,
      'teacher' => Icons.badge_outlined,
      'imap' || 'pop3' => Icons.mail_outline,
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

String channelLabel(String c) => switch (c) {
      'moodle' => 'Moodle',
      'web' => '网站',
      'rss' => 'RSS',
      'imap' => '邮件',
      'pop3' => '邮件',
      _ => c,
    };

/// 来源状态：区分“没有更新”“检查失败”“需要重新登录”。
({String label, Color color, IconData icon}) sourceStatus(BuildContext context, Source s) {
  final cs = Theme.of(context).colorScheme;
  return switch (s.status) {
    'ok' => (label: '正常', color: Brand.ok, icon: Icons.check_circle),
    'failed' => (label: '检查失败', color: cs.error, icon: Icons.error),
    'need_login' => (label: '需要重新登录', color: Brand.wheat, icon: Icons.lock_clock),
    _ => (label: '等待首次检查', color: cs.outline, icon: Icons.hourglass_top),
  };
}

String shortCourse(String course) {
  final parts = course.split(' ');
  return parts.length > 1 && RegExp(r'^[A-Z]{2,5}\d{3,5}$').hasMatch(parts.first) ? parts.sublist(1).join(' ') : course;
}

String greeting() {
  final h = DateTime.now().hour;
  if (h < 5) return '夜深了';
  if (h < 11) return '早上好';
  if (h < 13) return '中午好';
  if (h < 18) return '下午好';
  return '晚上好';
}

bool sameDay(DateTime a, DateTime b) => a.year == b.year && a.month == b.month && a.day == b.day;

String priorityLabel(String p) => switch (p) { 'urgent' => '紧急', 'normal' => '普通', _ => '低' };

DateTime? itemDeadline(Item i) => i.deadline;
