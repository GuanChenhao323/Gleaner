import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:go_router/go_router.dart';

import '../../core/format.dart';
import '../../core/models.dart';
import '../../core/providers.dart';
import '../../core/store.dart';
import '../../theme.dart';
import '../../widgets/common.dart';

class AssignmentsPage extends ConsumerStatefulWidget {
  const AssignmentsPage({super.key});
  @override
  ConsumerState<AssignmentsPage> createState() => _AssignmentsPageState();
}

class _AssignmentsPageState extends ConsumerState<AssignmentsPage> {
  String? course;
  bool showDone = false;

  @override
  Widget build(BuildContext context) {
    final all = ref.watch(assignmentsProvider);
    final courses = {for (final a in all) if (a.course.isNotEmpty) a.course}.toList()..sort();
    final list = all.where((a) => course == null || a.course == course).toList();
    final now = DateTime.now();
    final today = DateTime(now.year, now.month, now.day);
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
        key = '未设截止时间';
      } else if (d.isBefore(now)) {
        key = '已过截止';
      } else {
        final delta = DateTime(d.year, d.month, d.day).difference(today).inDays;
        key = delta == 0
            ? '今天'
            : delta == 1
                ? '明天'
                : delta < 7 - (today.weekday - 1)
                    ? '本周'
                    : delta < 14 - (today.weekday - 1)
                        ? '下周'
                        : '之后';
      }
      groups.putIfAbsent(key, () => []).add(a);
    }
    const order = ['已过截止', '今天', '明天', '本周', '下周', '之后', '未设截止时间'];
    final cs = Theme.of(context).colorScheme;

    return Scaffold(
      body: CustomScrollView(slivers: [
        SliverAppBar(
          pinned: true,
          title: const Text('作业'),
          actions: [
            FilterChip(label: const Text('显示已完成'), selected: showDone, onSelected: (v) => setState(() => showDone = v)),
            const SizedBox(width: 12),
          ],
          bottom: courses.isEmpty
              ? null
              : PreferredSize(
                  preferredSize: const Size.fromHeight(52),
                  child: SizedBox(
                    height: 52,
                    child: ListView(scrollDirection: Axis.horizontal, padding: const EdgeInsets.symmetric(horizontal: 16, vertical: 8), children: [
                      Padding(
                        padding: const EdgeInsets.only(right: 8),
                        child: ChoiceChip(label: const Text('全部课程'), selected: course == null, showCheckmark: false, onSelected: (_) => setState(() => course = null)),
                      ),
                      for (final c in courses)
                        Padding(
                          padding: const EdgeInsets.only(right: 8),
                          child: ChoiceChip(
                            avatar: CircleAvatar(backgroundColor: Brand.course(c), radius: 5),
                            label: Text(shortCourse(c)),
                            selected: course == c,
                            showCheckmark: false,
                            onSelected: (_) => setState(() => course = course == c ? null : c),
                          ),
                        ),
                    ]),
                  ),
                ),
        ),
        if (list.isEmpty)
          const SliverFillRemaining(
            hasScrollBody: false,
            child: EmptyState(icon: Icons.assignment_outlined, title: '还没有作业', message: '添加 Moodle 来源并登录一次，所有课程的作业会按截止时间汇总到这里。'),
          )
        else
          SliverPadding(
            padding: const EdgeInsets.fromLTRB(16, 0, 16, 96),
            sliver: SliverList.list(children: [
              for (final k in order)
                if (groups[k] != null) ...[
                  SectionHeader(k, trailing: '${groups[k]!.length} 项'),
                  for (final a in groups[k]!) _AssignmentTile(a),
                ],
              if (showDone && done.isNotEmpty) ...[
                SectionHeader('已完成', trailing: '${done.length} 项'),
                for (final a in done) _AssignmentTile(a),
              ],
              if (!showDone && done.isNotEmpty)
                Padding(
                  padding: const EdgeInsets.only(top: 16),
                  child: Center(child: Text('另有 ${done.length} 项已完成', style: TextStyle(color: cs.onSurfaceVariant))),
                ),
            ]),
          ),
      ]),
    );
  }
}

class _AssignmentTile extends ConsumerWidget {
  final Item a;
  const _AssignmentTile(this.a);

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final cs = Theme.of(context).colorScheme;
    final c = Brand.course(a.course);
    return Padding(
      padding: const EdgeInsets.only(bottom: 8),
      child: Material(
        color: cs.surfaceContainerLow,
        borderRadius: BorderRadius.circular(16),
        clipBehavior: Clip.antiAlias,
        child: InkWell(
          onTap: () => context.push('/item/${a.id}'),
          child: IntrinsicHeight(
            child: Row(crossAxisAlignment: CrossAxisAlignment.stretch, children: [
              Container(width: 5, color: c),
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
                          color: a.isDone ? cs.onSurfaceVariant : null,
                        )),
                    const SizedBox(height: 6),
                    Wrap(spacing: 10, runSpacing: 6, crossAxisAlignment: WrapCrossAlignment.center, children: [
                      CourseTag(a.course),
                      if (a.deadline != null) Text(absolute(a.deadline!), style: TextStyle(fontSize: 12, color: cs.onSurfaceVariant)),
                      if (a.attachments.isNotEmpty) Pill('${a.attachments.length} 个附件', color: cs.outline, icon: Icons.attach_file),
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
