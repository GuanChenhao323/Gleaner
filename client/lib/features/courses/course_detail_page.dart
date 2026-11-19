import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:go_router/go_router.dart';
import 'package:url_launcher/url_launcher.dart';

import '../../core/format.dart';
import '../../core/models.dart';
import '../../core/providers.dart';
import '../../theme.dart';
import '../../widgets/common.dart';
import 'assignment_list.dart';

class CourseDetailPage extends ConsumerStatefulWidget {
  final String name;
  const CourseDetailPage({super.key, required this.name});

  @override
  ConsumerState<CourseDetailPage> createState() => _CourseDetailPageState();
}

class _CourseDetailPageState extends ConsumerState<CourseDetailPage> {
  bool showDone = false;

  @override
  Widget build(BuildContext context) {
    final courses = ref.watch(coursesProvider);
    final cs = Theme.of(context).colorScheme;
    final t = Theme.of(context);

    return Scaffold(
      appBar: AppBar(
        leading: IconButton(icon: const Icon(Icons.arrow_back), onPressed: () => context.go('/courses')),
        actions: [
          FilterChip(label: const Text('已完成'), selected: showDone, onSelected: (v) => setState(() => showDone = v)),
          const SizedBox(width: 12),
        ],
      ),
      body: courses.when(
        loading: () => const Center(child: CircularProgressIndicator()),
        error: (e, _) => EmptyState(icon: Icons.cloud_off, title: '课程信息需要联网获取', message: '$e'),
        data: (list) {
          Course? match;
          for (final c in list) {
            if (c.name == widget.name) {
              match = c;
              break;
            }
          }
          if (match == null) {
            return EmptyState(
              icon: Icons.class_outlined,
              title: '找不到课程',
              message: widget.name,
              action: TextButton(onPressed: () => context.go('/courses'), child: const Text('返回课程列表')),
            );
          }
          final c = match;
          final color = Brand.course(c.name);
          final code = c.name.split(' ').first;
          final grouped = groupAssignmentsByDeadline(c.assignments);
          final openCount = c.assignments.where((a) => !a.isDone).length;

          return ListView(
            padding: const EdgeInsets.fromLTRB(16, 0, 16, 96),
            children: [
              Container(
                padding: const EdgeInsets.fromLTRB(18, 16, 18, 16),
                decoration: BoxDecoration(
                  borderRadius: BorderRadius.circular(20),
                  gradient: LinearGradient(colors: [color.withValues(alpha: 0.22), color.withValues(alpha: 0.06)]),
                ),
                child: Row(children: [
                  Expanded(
                    child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
                      if (code != c.name) Text(code, style: t.textTheme.labelMedium?.copyWith(color: color, fontWeight: FontWeight.w800)),
                      Text(shortCourse(c.name), style: t.textTheme.headlineSmall?.copyWith(fontWeight: FontWeight.w800)),
                    ]),
                  ),
                  Column(children: [
                    Text('$openCount', style: t.textTheme.headlineSmall?.copyWith(fontWeight: FontWeight.w800, color: color)),
                    Text('待完成', style: t.textTheme.labelSmall),
                  ]),
                ]),
              ),
              const SizedBox(height: 20),
              SectionHeader('作业', trailing: '${c.assignments.length}'),
              if (c.assignments.isEmpty)
                Padding(
                  padding: const EdgeInsets.fromLTRB(4, 8, 4, 16),
                  child: Text('还没有作业', style: TextStyle(color: cs.onSurfaceVariant)),
                )
              else ...[
                for (final k in deadlineGroupOrder)
                  if (grouped.groups[k] != null) ...[
                    SectionHeader(k, trailing: '${grouped.groups[k]!.length}'),
                    for (final a in grouped.groups[k]!) AssignmentTile(a, showCourse: false),
                  ],
                if (showDone && grouped.done.isNotEmpty) ...[
                  SectionHeader('已完成', trailing: '${grouped.done.length}'),
                  for (final a in grouped.done) AssignmentTile(a, showCourse: false),
                ],
                if (!showDone && grouped.done.isNotEmpty)
                  Padding(
                    padding: const EdgeInsets.only(top: 8, bottom: 8),
                    child: Center(child: Text('${grouped.done.length} 项已完成', style: TextStyle(color: cs.onSurfaceVariant))),
                  ),
              ],
              const SizedBox(height: 12),
              SectionHeader('通知', trailing: c.notices.isEmpty ? null : '${c.notices.length}'),
              if (c.notices.isEmpty)
                Padding(
                  padding: const EdgeInsets.fromLTRB(4, 8, 4, 16),
                  child: Text('暂无通知', style: TextStyle(color: cs.onSurfaceVariant)),
                )
              else
                for (final n in c.notices)
                  ListTile(
                    contentPadding: EdgeInsets.zero,
                    leading: Icon(kindIcon(n.kind)),
                    title: Text(n.title, maxLines: 2, overflow: TextOverflow.ellipsis),
                    subtitle: Text(relative(n.sortTime)),
                    trailing: Text(kindLabel(n.kind), style: TextStyle(fontSize: 12, color: cs.onSurfaceVariant)),
                    onTap: () => context.push('/item/${n.id}'),
                  ),
              const SizedBox(height: 12),
              const SectionHeader('教师'),
              if (c.teachers.isEmpty)
                Padding(
                  padding: const EdgeInsets.fromLTRB(4, 8, 4, 16),
                  child: Text('添加“教师信息”来源以显示老师联系方式', style: TextStyle(color: cs.onSurfaceVariant)),
                )
              else
                for (final te in c.teachers) _TeacherTile(te),
            ],
          );
        },
      ),
    );
  }
}

class _TeacherTile extends StatelessWidget {
  final Teacher t;
  const _TeacherTile(this.t);

  @override
  Widget build(BuildContext context) {
    final cs = Theme.of(context).colorScheme;
    return ListTile(
      contentPadding: EdgeInsets.zero,
      leading: Avatar(t.name, size: 40),
      title: Text('${t.name} ${t.title}', style: const TextStyle(fontWeight: FontWeight.w700)),
      subtitle: Text('${t.office}  ·  ${t.phone}', style: TextStyle(color: cs.onSurfaceVariant)),
      trailing: t.email.isEmpty
          ? null
          : IconButton(
              tooltip: t.email,
              icon: const Icon(Icons.alternate_email),
              onPressed: () {
                Clipboard.setData(ClipboardData(text: t.email));
                launchUrl(Uri.parse('mailto:${t.email}'));
              },
            ),
    );
  }
}
