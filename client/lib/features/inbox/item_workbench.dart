// 工作台的事项管理部件（IC-002）：类型与处理状态、日程信息、字段修改与冲突处理、来源监测状态、版本差异。
import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../core/api.dart';
import '../../core/format.dart';
import '../../core/models.dart';
import '../../core/store.dart';
import '../../widgets/common.dart';

String typeLabel(String t) => switch (t) {
      'reference' => '资料',
      'todo' => '待办',
      'event' => '日程',
      _ => '通知',
    };

IconData typeIcon(String t) => switch (t) {
      'reference' => Icons.bookmark_outline,
      'todo' => Icons.task_alt,
      'event' => Icons.event,
      _ => Icons.campaign_outlined,
    };

Color typeColor(String t) => switch (t) {
      'todo' => const Color(0xFFD9534F),
      'event' => const Color(0xFFC9891F),
      _ => const Color(0xFFB07A28),
    };

String statusLabel(String s) => switch (s) {
      'open' => '待完成',
      'done' => '已完成',
      'active' => '未归档',
      'archived' => '已归档',
      'unread' => '未读',
      _ => '已读',
    };

/// 按类型切换处理状态的按钮文字。
String statusAction(Item i) => switch (i.type) {
      'todo' => i.isDone ? '标为待完成' : '标为已完成',
      'event' => i.state.archived ? '取消归档' : '归档',
      _ => i.state.read ? '标为未读' : '标为已读',
    };

const fieldLabels = {
  'title': '标题',
  'summary': '摘要',
  'type': '类型',
  'deadline_at': '截止时间',
  'start_at': '开始时间',
  'end_at': '结束时间',
  'location': '地点',
  'requirements': '要求',
};

String fieldText(String field, Object? v) {
  if (v == null || (v is String && v.isEmpty)) return '（空）';
  if (field.endsWith('_at') && v is num) return absolute(tsToDate(v)!);
  if (field == 'type') return typeLabel(v.toString());
  return v.toString();
}

void _toastError(BuildContext context, Object e) {
  if (context.mounted) toast(context, e is ApiException ? e.message : '操作失败：$e');
}

/// 执行需要联网的操作；失败时提示原因（例如离线、不支持监测）。
Future<void> _run(BuildContext context, Future<void> Function() op) async {
  try {
    await op();
  } catch (e) {
    if (context.mounted) _toastError(context, e);
  }
}

/// 类型、处理状态与切换按钮。
class TypeStatusRow extends ConsumerWidget {
  final Item item;
  const TypeStatusRow({super.key, required this.item});
  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final c = typeColor(item.type);
    return Wrap(spacing: 8, runSpacing: 8, crossAxisAlignment: WrapCrossAlignment.center, children: [
      Pill(typeLabel(item.type), color: c, icon: typeIcon(item.type)),
      Pill(statusLabel(item.status), color: Theme.of(context).colorScheme.onSurfaceVariant),
      if (item.origin == 'capture') Pill('插件采集', color: Theme.of(context).colorScheme.primary, icon: Icons.extension_outlined),
    ]);
  }
}

/// 日程：时间与地点。
class EventCard extends StatelessWidget {
  final Item item;
  const EventCard({super.key, required this.item});
  @override
  Widget build(BuildContext context) {
    final start = tsToDate(item.startAt);
    final end = tsToDate(item.endAt);
    if (start == null && item.location.isEmpty) return const SizedBox.shrink();
    final cs = Theme.of(context).colorScheme;
    return Card(
      child: Column(children: [
        if (start != null)
          ListTile(
            leading: const Icon(Icons.schedule),
            title: Text(end == null ? absolute(start) : '${absolute(start)} – ${end.hour.toString().padLeft(2, '0')}:${end.minute.toString().padLeft(2, '0')}'),
            subtitle: Text(start.isBefore(DateTime.now()) ? '已开始' : countdown(start), style: TextStyle(color: cs.onSurfaceVariant)),
          ),
        if (item.location.isNotEmpty) ListTile(leading: const Icon(Icons.place_outlined), title: Text(item.location)),
      ]),
    );
  }
}

/// 来源变化与用户修改冲突：两边都显示，由用户选择（产品定义 2.4 节）。
class ConflictBanner extends ConsumerWidget {
  final Item item;
  const ConflictBanner({super.key, required this.item});
  @override
  Widget build(BuildContext context, WidgetRef ref) {
    if (item.conflicts.isEmpty) return const SizedBox.shrink();
    final cs = Theme.of(context).colorScheme;
    final store = ref.read(feedProvider.notifier);
    final fields = item.fields;
    return Container(
      margin: const EdgeInsets.only(top: 12),
      padding: const EdgeInsets.all(14),
      decoration: BoxDecoration(color: cs.errorContainer, borderRadius: BorderRadius.circular(16)),
      child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
        Row(children: [
          Icon(Icons.call_split, color: cs.onErrorContainer),
          const SizedBox(width: 8),
          Expanded(
            child: Text('你改过的内容在来源里也更新了，请确认保留哪一个',
                style: TextStyle(color: cs.onErrorContainer, fontWeight: FontWeight.w700)),
          ),
        ]),
        for (final f in item.conflicts) ...[
          const SizedBox(height: 10),
          Text(fieldLabels[f] ?? f, style: TextStyle(color: cs.onErrorContainer, fontWeight: FontWeight.w600)),
          Text('我的：${fieldText(f, fields[f]?.value)}', style: TextStyle(color: cs.onErrorContainer)),
          Text('来源：${fieldText(f, fields[f]?.source)}', style: TextStyle(color: cs.onErrorContainer)),
          Wrap(spacing: 8, children: [
            TextButton(
              onPressed: () => _run(context, () => store.resolveConflict(item, f, 'mine')),
              child: const Text('保留我的'),
            ),
            TextButton(
              onPressed: () => _run(context, () => store.resolveConflict(item, f, 'source')),
              child: const Text('采用来源'),
            ),
          ]),
        ],
      ]),
    );
  }
}

/// 来源监测状态：最后成功检查时间、最近结果、失败原因与开关（US09）。
class MonitorCard extends ConsumerWidget {
  final Item item;
  const MonitorCard({super.key, required this.item});

  static String statusText(MonitorInfo m) => switch (m.status) {
        'unsupported' => '暂不支持自动检查，可打开原始来源手动核对',
        'disabled' => '已关闭自动检查',
        'pending' => '已开启，等待第一次检查',
        'unchanged' => '最近一次检查：无变化',
        'changed' => '最近一次检查：发现变化',
        'failed' => '最近一次检查失败',
        _ => m.status,
      };

  static String errorText(MonitorInfo m) => switch (m.errorCode) {
        'auth_expired' || 'need_login' => '登录已过期：请在浏览器里重新登录该网站',
        'forbidden' => '没有权限访问该页面',
        'network' || 'failed' => '网络错误',
        'not_found' => '页面上找不到这条事项',
        'parse_failed' => '页面结构变了，暂时无法解析',
        'unsupported' => '该页面不再支持自动检查',
        _ => m.errorCode,
      };

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final m = item.monitor;
    final cs = Theme.of(context).colorScheme;
    final failed = m.status == 'failed';
    final color = failed ? cs.error : (m.status == 'changed' ? cs.tertiary : cs.onSurfaceVariant);
    return Card(
      child: Column(children: [
        ListTile(
          leading: Icon(failed ? Icons.sync_problem : Icons.radar, color: color),
          title: Text(statusText(m), style: TextStyle(color: failed ? cs.error : null, fontWeight: failed ? FontWeight.w700 : null)),
          subtitle: Text(
            [
              // 失败不更新最后成功检查时间，所以这里永远是真正成功的那一次
              '最后成功检查：${m.lastSuccessAt == null ? '还没有' : relative(tsToDate(m.lastSuccessAt))}',
              if (failed) '原因：${m.errorMessage.isNotEmpty ? m.errorMessage : errorText(m)}',
              if (m.lastCheckedAt != null && failed) '失败时间：${relative(tsToDate(m.lastCheckedAt))}',
              if (m.enabled && m.nextCheckAt != null) '下次检查：${absolute(tsToDate(m.nextCheckAt)!)}（需 Chrome 与本地后端运行）',
            ].join('\n'),
          ),
          isThreeLine: failed || (m.enabled && m.nextCheckAt != null),
          trailing: item.origin == 'capture' && m.supported
              ? Switch(
                  value: m.enabled,
                  onChanged: (v) => _run(context, () => ref.read(feedProvider.notifier).setMonitor(item, v)),
                )
              : null,
        ),
      ]),
    );
  }
}

/// 修改字段对话框：改过的字段与来源版本分开保存，可一键恢复来源值。
Future<void> showEditFields(BuildContext context, WidgetRef ref, Item item) async {
  final fields = item.fields;
  final text = {
    for (final f in ['title', 'summary', 'location', 'requirements'])
      f: TextEditingController(text: (fields[f]?.value ?? '').toString()),
  };
  String type = item.type;
  final times = <String, DateTime?>{
    for (final f in ['deadline_at', 'start_at', 'end_at']) f: tsToDate(fields[f]?.value),
  };
  final reset = <String>{};

  Future<DateTime?> pick(BuildContext ctx, DateTime? init) async {
    final now = DateTime.now();
    final d = await showDatePicker(
      context: ctx,
      initialDate: init ?? now,
      firstDate: DateTime(now.year - 2),
      lastDate: DateTime(now.year + 5),
    );
    if (d == null || !ctx.mounted) return null;
    final t = await showTimePicker(context: ctx, initialTime: TimeOfDay.fromDateTime(init ?? DateTime(d.year, d.month, d.day, 23, 59)));
    return DateTime(d.year, d.month, d.day, t?.hour ?? 23, t?.minute ?? 59);
  }

  final saved = await showDialog<bool>(
    context: context,
    builder: (ctx) => StatefulBuilder(
      builder: (ctx, setLocal) {
        Widget resetBtn(String f) => fields[f]?.edited == true && !reset.contains(f)
            ? TextButton(onPressed: () => setLocal(() => reset.add(f)), child: const Text('恢复来源值'))
            : (reset.contains(f) ? const Text('将恢复来源值', style: TextStyle(fontSize: 12)) : const SizedBox.shrink());
        Widget timeRow(String f) => Row(children: [
              Expanded(
                child: Text('${fieldLabels[f]}：${times[f] == null ? '未设置' : absolute(times[f]!)}'),
              ),
              TextButton(
                onPressed: () async {
                  final v = await pick(ctx, times[f]);
                  if (v != null) {
                    setLocal(() {
                      times[f] = v;
                      reset.remove(f);
                    });
                  }
                },
                child: const Text('选择'),
              ),
              if (times[f] != null)
                TextButton(
                  onPressed: () => setLocal(() {
                    times[f] = null;
                    reset.remove(f);
                  }),
                  child: const Text('清空'),
                ),
              resetBtn(f),
            ]);
        return AlertDialog(
          title: const Text('修改事项'),
          content: SizedBox(
            width: 520,
            child: SingleChildScrollView(
              child: Column(mainAxisSize: MainAxisSize.min, crossAxisAlignment: CrossAxisAlignment.start, children: [
                const Text('修改只影响你看到的内容；来源更新不会覆盖，若来源也改了会提示你确认。', style: TextStyle(fontSize: 12)),
                const SizedBox(height: 12),
                SegmentedButton<String>(
                  segments: const [
                    ButtonSegment(value: 'todo', label: Text('待办'), icon: Icon(Icons.task_alt)),
                    ButtonSegment(value: 'event', label: Text('日程'), icon: Icon(Icons.event)),
                    ButtonSegment(value: 'reference', label: Text('资料')),
                    ButtonSegment(value: 'notice', label: Text('通知'), icon: Icon(Icons.campaign_outlined)),
                  ],
                  selected: {type},
                  onSelectionChanged: (s) => setLocal(() {
                    type = s.first;
                    reset.remove('type');
                  }),
                ),
                for (final f in ['title', 'summary', 'location', 'requirements']) ...[
                  const SizedBox(height: 8),
                  TextField(
                    controller: text[f],
                    maxLines: f == 'summary' || f == 'requirements' ? 3 : 1,
                    decoration: InputDecoration(labelText: fieldLabels[f], isDense: true),
                    onChanged: (_) => setLocal(() => reset.remove(f)),
                  ),
                  Align(alignment: Alignment.centerRight, child: resetBtn(f)),
                ],
                const SizedBox(height: 4),
                for (final f in ['deadline_at', 'start_at', 'end_at']) timeRow(f),
              ]),
            ),
          ),
          actions: [
            TextButton(onPressed: () => Navigator.pop(ctx, false), child: const Text('取消')),
            FilledButton(onPressed: () => Navigator.pop(ctx, true), child: const Text('保存')),
          ],
        );
      },
    ),
  );
  if (saved != true || !context.mounted) return;
  // 只提交真的改了的字段：与当前生效值相同的不发，免得把“没改”记成用户修改
  final set = <String, dynamic>{};
  for (final f in ['title', 'summary', 'location', 'requirements']) {
    final v = text[f]!.text.trim();
    if (!reset.contains(f) && v != (fields[f]?.value ?? '').toString()) set[f] = v;
  }
  if (!reset.contains('type') && type != item.type) set['type'] = type;
  for (final f in ['deadline_at', 'start_at', 'end_at']) {
    if (reset.contains(f)) continue;
    final v = times[f] == null ? null : times[f]!.millisecondsSinceEpoch / 1000;
    final old = fields[f]?.value;
    final same = (v == null && old == null) || (v != null && old is num && (v - old).abs() < 60);
    if (!same) set[f] = v;
  }
  if (set.isEmpty && reset.isEmpty) return;
  try {
    await ref.read(feedProvider.notifier).editFields(item, set: set, reset: reset.toList());
    if (context.mounted) toast(context, '已保存修改');
  } catch (e) {
    if (context.mounted) _toastError(context, e);
  }
}

/// 版本差异：相邻两个版本的来源内容逐字段对比（US08）。
class VersionDiff extends StatelessWidget {
  final ItemVersion version;
  final ItemVersion? previous;
  const VersionDiff({super.key, required this.version, this.previous});

  static const _fields = ['title', 'deadline_at', 'start_at', 'end_at', 'location', 'requirements', 'type', 'summary', 'body'];

  @override
  Widget build(BuildContext context) {
    final cs = Theme.of(context).colorScheme;
    final rows = <Widget>[];
    final prev = previous?.snapshot ?? const {};
    final cur = version.snapshot;
    for (final f in _fields) {
      Object? a = prev[f];
      Object? b = cur[f];
      // 旧版本没存快照字段时，退回 changed_fields 里的新旧值
      if (cur.isEmpty || (!cur.containsKey(f) && version.changed.containsKey(f))) {
        final pair = version.changed[f];
        if (pair is List && pair.length == 2) {
          a = pair[0];
          b = pair[1];
        }
      }
      if ('${a ?? ''}' == '${b ?? ''}') continue;
      final label = f == 'body' ? '正文' : (fieldLabels[f] ?? f);
      final long = f == 'body' || f == 'summary';
      rows.add(Padding(
        padding: const EdgeInsets.only(top: 6),
        child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
          Text(label, style: const TextStyle(fontWeight: FontWeight.w600, fontSize: 12)),
          Text('旧：${_short(fieldText(f, a), long)}',
              style: TextStyle(fontSize: 12, color: cs.error, decoration: TextDecoration.lineThrough)),
          Text('新：${_short(fieldText(f, b), long)}', style: TextStyle(fontSize: 12, color: cs.primary)),
        ]),
      ));
    }
    if (rows.isEmpty) return const SizedBox.shrink();
    return Column(crossAxisAlignment: CrossAxisAlignment.start, children: rows);
  }

  static String _short(String s, bool long) => long && s.length > 300 ? '${s.substring(0, 300)}…' : s;
}
