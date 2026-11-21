import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:go_router/go_router.dart';
import 'package:url_launcher/url_launcher.dart';

import '../../core/format.dart';
import '../../core/models.dart';
import '../../core/providers.dart';
import '../../l10n/app_localizations.dart';
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
    final l10n = AppLocalizations.of(context);
    final courses = ref.watch(coursesProvider);
    final cs = Theme.of(context).colorScheme;
    final t = Theme.of(context);

    return Scaffold(
      appBar: AppBar(
        leading: IconButton(icon: const Icon(Icons.arrow_back), onPressed: () => context.go('/courses')),
        actions: [
          FilterChip(label: Text(l10n.completed), selected: showDone, onSelected: (v) => setState(() => showDone = v)),
          const SizedBox(width: 12),
        ],
      ),
      body: courses.when(
        loading: () => const Center(child: CircularProgressIndicator()),
        error: (e, _) => EmptyState(icon: Icons.cloud_off, title: l10n.courseNeedNetwork, message: '$e'),
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
              title: l10n.courseNotFound,
              message: widget.name,
              action: TextButton(onPressed: () => context.go('/courses'), child: Text(l10n.backToCourses)),
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
                    Text(l10n.statusPending, style: t.textTheme.labelSmall),
                  ]),
                ]),
              ),
              const SizedBox(height: 20),
              SectionHeader(l10n.assignments, trailing: '${c.assignments.length}'),
              if (c.assignments.isEmpty)
                Padding(
                  padding: const EdgeInsets.fromLTRB(4, 8, 4, 16),
                  child: Text(l10n.noAssignmentsYet, style: TextStyle(color: cs.onSurfaceVariant)),
                )
              else ...[
                for (final k in deadlineGroupOrder)
                  if (grouped.groups[k] != null) ...[
                    SectionHeader(deadlineGroupLabel(k, l10n), trailing: '${grouped.groups[k]!.length}'),
                    for (final a in grouped.groups[k]!) AssignmentTile(a, showCourse: false),
                  ],
                if (showDone && grouped.done.isNotEmpty) ...[
                  SectionHeader(l10n.completed, trailing: '${grouped.done.length}'),
                  for (final a in grouped.done) AssignmentTile(a, showCourse: false),
                ],
                if (!showDone && grouped.done.isNotEmpty)
                  Padding(
                    padding: const EdgeInsets.only(top: 8, bottom: 8),
                    child: Center(child: Text(l10n.doneCount(grouped.done.length), style: TextStyle(color: cs.onSurfaceVariant))),
                  ),
              ],
              const SizedBox(height: 12),
              SectionHeader(l10n.inboxNotice, trailing: c.notices.isEmpty ? null : '${c.notices.length}'),
              if (c.notices.isEmpty)
                Padding(
                  padding: const EdgeInsets.fromLTRB(4, 8, 4, 16),
                  child: Text(l10n.noNotices, style: TextStyle(color: cs.onSurfaceVariant)),
                )
              else
                for (final n in c.notices)
                  ListTile(
                    contentPadding: EdgeInsets.zero,
                    leading: Icon(kindIcon(n.kind)),
                    title: Text(n.title, maxLines: 2, overflow: TextOverflow.ellipsis),
                    subtitle: Text(relative(n.sortTime, context)),
                    trailing: Text(kindLabel(n.kind, context), style: TextStyle(fontSize: 12, color: cs.onSurfaceVariant)),
                    onTap: () => context.push('/item/${n.id}'),
                  ),
              const SizedBox(height: 12),
              SectionHeader(AppLocalizations.of(context).teachersHeader),
              if (c.teachers.isEmpty)
                Padding(
                  padding: const EdgeInsets.fromLTRB(4, 8, 4, 16),
                  child: Text(AppLocalizations.of(context).addFacultySourceHint, style: TextStyle(color: cs.onSurfaceVariant)),
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
