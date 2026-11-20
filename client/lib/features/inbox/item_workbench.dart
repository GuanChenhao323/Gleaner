// 工作台的事项管理部件（IC-002）：类型与处理状态、日程信息、字段修改与冲突处理、来源监测状态、版本差异。
import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../core/api.dart';
import '../../core/format.dart';
import '../../core/models.dart';
import '../../core/store.dart';
import '../../l10n/app_localizations.dart';
import '../../widgets/common.dart';

String typeLabel(String t, BuildContext context) {
  final l10n = AppLocalizations.of(context);
  return switch (t) {
    'reference' => l10n.typeReference,
    'todo' => l10n.typeTodo,
    'event' => l10n.typeEvent,
    _ => l10n.typeNotice,
  };
}

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

String statusLabel(String s, BuildContext context) {
  final l10n = AppLocalizations.of(context);
  return switch (s) {
    'open' => l10n.statusOpen,
    'done' => l10n.statusDone,
    'active' => l10n.statusActive,
    'archived' => l10n.statusArchived,
    'unread' => l10n.statusUnread,
    _ => l10n.statusRead,
  };
}

String statusAction(Item i, BuildContext context) {
  final l10n = AppLocalizations.of(context);
  return switch (i.type) {
    'todo' => i.isDone ? l10n.markOpen : l10n.markDone,
    'event' => i.state.archived ? l10n.unarchive : l10n.archive,
    _ => i.state.read ? l10n.markUnread : l10n.markRead,
  };
}

String fieldLabel(String field, BuildContext context) {
  final l10n = AppLocalizations.of(context);
  return switch (field) {
    'title' => l10n.fieldTitle,
    'summary' => l10n.fieldSummary,
    'type' => l10n.fieldType,
    'deadline_at' => l10n.fieldDeadline,
    'start_at' => l10n.fieldStart,
    'end_at' => l10n.fieldEnd,
    'location' => l10n.fieldLocation,
    'requirements' => l10n.fieldRequirements,
    'body' => l10n.fieldBody,
    _ => field,
  };
}

String fieldText(String field, Object? v, BuildContext context) {
  final l10n = AppLocalizations.of(context);
  if (v == null || (v is String && v.isEmpty)) return l10n.emptyValue;
  if (field.endsWith('_at') && v is num) return absolute(tsToDate(v)!, context);
  if (field == 'type') return typeLabel(v.toString(), context);
  return v.toString();
}

void _toastError(BuildContext context, Object e) {
  final l10n = AppLocalizations.of(context);
  if (context.mounted) toast(context, e is ApiException ? e.message : l10n.operationFailed('$e'));
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
      Pill(typeLabel(item.type, context), color: c, icon: typeIcon(item.type)),
      Pill(statusLabel(item.status, context), color: Theme.of(context).colorScheme.onSurfaceVariant),
      if (item.origin == 'capture')
        Pill(AppLocalizations.of(context).pluginCapture, color: Theme.of(context).colorScheme.primary, icon: Icons.extension_outlined),
    ]);
  }
}

/// 日程：时间与地点。
class EventCard extends StatelessWidget {
  final Item item;
  const EventCard({super.key, required this.item});
  @override
  Widget build(BuildContext context) {
    final l10n = AppLocalizations.of(context);
    final start = tsToDate(item.startAt);
    final end = tsToDate(item.endAt);
    if (start == null && item.location.isEmpty) return const SizedBox.shrink();
    final cs = Theme.of(context).colorScheme;
    return Card(
      child: Column(children: [
        if (start != null)
          ListTile(
            leading: const Icon(Icons.schedule),
            title: Text(end == null ? absolute(start, context) : '${absolute(start, context)} – ${end.hour.toString().padLeft(2, '0')}:${end.minute.toString().padLeft(2, '0')}'),
            subtitle: Text(start.isBefore(DateTime.now()) ? l10n.alreadyStarted : countdown(start, context), style: TextStyle(color: cs.onSurfaceVariant)),
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
    final l10n = AppLocalizations.of(context);
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
            child: Text(l10n.conflictBanner, style: TextStyle(color: cs.onErrorContainer, fontWeight: FontWeight.w700)),
          ),
        ]),
        for (final f in item.conflicts) ...[
          const SizedBox(height: 10),
          Text(fieldLabel(f, context), style: TextStyle(color: cs.onErrorContainer, fontWeight: FontWeight.w600)),
          Text(l10n.mineValue(fieldText(f, fields[f]?.value, context)), style: TextStyle(color: cs.onErrorContainer)),
          Text(l10n.sourceValue(fieldText(f, fields[f]?.source, context)), style: TextStyle(color: cs.onErrorContainer)),
          Wrap(spacing: 8, children: [
            TextButton(
              onPressed: () => _run(context, () => store.resolveConflict(item, f, 'mine')),
              child: Text(l10n.keepMine),
            ),
            TextButton(
              onPressed: () => _run(context, () => store.resolveConflict(item, f, 'source')),
              child: Text(l10n.useSource),
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

  static String statusText(MonitorInfo m, AppLocalizations l10n) => switch (m.status) {
        'unsupported' => l10n.monitorUnsupported,
        'disabled' => l10n.monitorDisabled,
        'pending' => l10n.monitorPending,
        'unchanged' => l10n.monitorUnchanged,
        'changed' => l10n.monitorChanged,
        'failed' => l10n.monitorFailed,
        _ => m.status,
      };

  static String errorText(MonitorInfo m, AppLocalizations l10n) => switch (m.errorCode) {
        'auth_expired' || 'need_login' => l10n.errAuthExpired,
        'forbidden' => l10n.errForbidden,
        'network' || 'failed' => l10n.errNetwork,
        'not_found' => l10n.errNotFound,
        'parse_failed' => l10n.errParseFailed,
        'unsupported' => l10n.errUnsupported,
        _ => m.errorCode,
      };

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final l10n = AppLocalizations.of(context);
    final m = item.monitor;
    final cs = Theme.of(context).colorScheme;
    final failed = m.status == 'failed';
    final color = failed ? cs.error : (m.status == 'changed' ? cs.tertiary : cs.onSurfaceVariant);
    return Card(
      child: Column(children: [
        ListTile(
          leading: Icon(failed ? Icons.sync_problem : Icons.radar, color: color),
          title: Text(statusText(m, l10n), style: TextStyle(color: failed ? cs.error : null, fontWeight: failed ? FontWeight.w700 : null)),
          subtitle: Text(
            [
              l10n.lastSuccessCheckLine(m.lastSuccessAt == null ? l10n.lastSuccessNever : relative(tsToDate(m.lastSuccessAt), context)),
              if (failed) l10n.reasonLine(localizeMonitorReason(m, l10n)),
              if (m.lastCheckedAt != null && failed) l10n.failedAtLine(relative(tsToDate(m.lastCheckedAt), context)),
              if (m.enabled && m.nextCheckAt != null) l10n.nextCheckLine(absolute(tsToDate(m.nextCheckAt)!, context)),
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

  final l10n = AppLocalizations.of(context);
  final saved = await showDialog<bool>(
    context: context,
    builder: (ctx) {
      final dlg = AppLocalizations.of(ctx);
      return StatefulBuilder(
        builder: (ctx, setLocal) {
          Widget resetBtn(String f) => fields[f]?.edited == true && !reset.contains(f)
              ? TextButton(onPressed: () => setLocal(() => reset.add(f)), child: Text(dlg.restoreSourceValue))
              : (reset.contains(f) ? Text(dlg.willRestoreSource, style: const TextStyle(fontSize: 12)) : const SizedBox.shrink());
          Widget timeRow(String f) => Row(children: [
                Expanded(
                  child: Text('${fieldLabel(f, ctx)}：${times[f] == null ? dlg.notSet : absolute(times[f]!, ctx)}'),
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
                  child: Text(dlg.choose),
                ),
                if (times[f] != null)
                  TextButton(
                    onPressed: () => setLocal(() {
                      times[f] = null;
                      reset.remove(f);
                    }),
                    child: Text(dlg.clear),
                  ),
                resetBtn(f),
              ]);
          return AlertDialog(
            title: Text(dlg.editItem),
            content: SizedBox(
              width: 520,
              child: SingleChildScrollView(
                child: Column(mainAxisSize: MainAxisSize.min, crossAxisAlignment: CrossAxisAlignment.start, children: [
                  Text(dlg.editItemHint, style: const TextStyle(fontSize: 12)),
                  const SizedBox(height: 12),
                  SegmentedButton<String>(
                    segments: [
                      ButtonSegment(value: 'todo', label: Text(dlg.typeTodo), icon: const Icon(Icons.task_alt)),
                      ButtonSegment(value: 'event', label: Text(dlg.typeEvent), icon: const Icon(Icons.event)),
                      ButtonSegment(value: 'reference', label: Text(dlg.typeReference)),
                      ButtonSegment(value: 'notice', label: Text(dlg.typeNotice), icon: const Icon(Icons.campaign_outlined)),
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
                      decoration: InputDecoration(labelText: fieldLabel(f, ctx), isDense: true),
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
              TextButton(onPressed: () => Navigator.pop(ctx, false), child: Text(dlg.actionCancel)),
              FilledButton(onPressed: () => Navigator.pop(ctx, true), child: Text(dlg.actionSave)),
            ],
          );
        },
      );
    },
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
    if (context.mounted) toast(context, l10n.editsSaved);
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
    final l10n = AppLocalizations.of(context);
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
      final label = fieldLabel(f, context);
      final long = f == 'body' || f == 'summary';
      rows.add(Padding(
        padding: const EdgeInsets.only(top: 6),
        child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
          Text(label, style: const TextStyle(fontWeight: FontWeight.w600, fontSize: 12)),
          Text(l10n.oldValue(_short(fieldText(f, a, context), long)),
              style: TextStyle(fontSize: 12, color: cs.error, decoration: TextDecoration.lineThrough)),
          Text(l10n.newValue(_short(fieldText(f, b, context), long)), style: TextStyle(fontSize: 12, color: cs.primary)),
        ]),
      ));
    }
    if (rows.isEmpty) return const SizedBox.shrink();
    return Column(crossAxisAlignment: CrossAxisAlignment.start, children: rows);
  }

  static String _short(String s, bool long) => long && s.length > 300 ? '${s.substring(0, 300)}…' : s;
}
