import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:go_router/go_router.dart';

import '../../core/format.dart';
import '../../core/models.dart';
import '../../core/store.dart';
import '../../l10n/app_localizations.dart';
import '../../widgets/common.dart';

const deadlineGroupOrder = ['overdue', 'today', 'tomorrow', 'thisWeek', 'nextWeek', 'later', 'noDeadline'];

String deadlineGroupLabel(String key, AppLocalizations l10n) => switch (key) {
      'overdue' => l10n.groupOverdue,
      'today' => l10n.today,
      'tomorrow' => l10n.tomorrow,
      'thisWeek' => l10n.deskThisWeek,
      'nextWeek' => l10n.groupNextWeek,
      'later' => l10n.groupLater,
      'noDeadline' => l10n.groupNoDeadline,
      _ => key,
    };

({Map<String, List<Item>> groups, List<Item> done}) groupAssignmentsByDeadline(List<Item> list, {DateTime? now}) {
  final n = now ?? DateTime.now();
  final today = DateTime(n.year, n.month, n.day);
  final groups = <String, List<Item>>{};
  final done = <Item>[];
  for (final a in list) {
    if (a.isDone) {
      done.add(a);
      continue;
    }
    final d = a.deadline;
    final String key;
    if (d == null) {
      key = 'noDeadline';
    } else if (d.isBefore(n)) {
      key = 'overdue';
    } else {
      final delta = DateTime(d.year, d.month, d.day).difference(today).inDays;
      key = delta == 0
          ? 'today'
          : delta == 1
              ? 'tomorrow'
              : delta < 7 - (today.weekday - 1)
                  ? 'thisWeek'
                  : delta < 14 - (today.weekday - 1)
                      ? 'nextWeek'
                      : 'later';
    }
    groups.putIfAbsent(key, () => []).add(a);
  }
  return (groups: groups, done: done);
}

class AssignmentTile extends ConsumerWidget {
  final Item a;
  final bool showCourse;
  const AssignmentTile(this.a, {super.key, this.showCourse = true});

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final l10n = AppLocalizations.of(context);
    final cs = Theme.of(context).colorScheme;
    final accent = dueRowAccent(done: a.isDone, priority: a.priority, deadline: a.deadline);
    return Padding(
      padding: const EdgeInsets.only(bottom: 8),
      child: Material(
        color: cs.surface,
        shape: RoundedRectangleBorder(
          borderRadius: BorderRadius.circular(16),
          side: BorderSide(color: cs.outlineVariant),
        ),
        clipBehavior: Clip.antiAlias,
        child: InkWell(
          onTap: () => context.push('/item/${a.id}'),
          child: IntrinsicHeight(
            child: Row(crossAxisAlignment: CrossAxisAlignment.stretch, children: [
              Container(width: 3, color: accent ?? cs.outlineVariant),
              Checkbox(
                value: a.isDone,
                shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(6)),
                onChanged: (v) => ref.read(feedProvider.notifier).setState(a, todo: v == true ? 'done' : 'todo'),
              ),
              Expanded(
                child: Padding(
                  padding: const EdgeInsets.symmetric(vertical: 12),
                  child: Column(crossAxisAlignment: CrossAxisAlignment.start, mainAxisAlignment: MainAxisAlignment.center, children: [
                    Text(a.title,
                        style: TextStyle(
                          fontWeight: FontWeight.w600,
                          decoration: a.isDone ? TextDecoration.lineThrough : null,
                          color: a.isDone ? cs.onSurfaceVariant : cs.onSurface,
                        )),
                    const SizedBox(height: 6),
                    Wrap(spacing: 10, runSpacing: 6, crossAxisAlignment: WrapCrossAlignment.center, children: [
                      if (showCourse) CourseTag(a.course, muted: true),
                      if (a.deadline != null) Text(absolute(a.deadline!, context), style: TextStyle(fontSize: 12, color: cs.onSurfaceVariant)),
                      if (a.attachments.isNotEmpty) Pill(l10n.attachmentsCount(a.attachments.length), color: cs.outline, icon: Icons.attach_file),
                      if (a.importantChange && a.changeNote.isNotEmpty) ChangeBadge(a.changeNote),
                    ]),
                  ]),
                ),
              ),
              if (a.deadline != null) Padding(padding: const EdgeInsets.all(12), child: Center(child: DeadlineBadge(a.deadline!, done: a.isDone))),
            ]),
          ),
        ),
      ),
    );
  }
}
