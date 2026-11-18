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

/// 课程列表：点进详情看该课全部作业。
class CoursesPage extends ConsumerWidget {
  const CoursesPage({super.key});

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final courses = ref.watch(coursesProvider);
    final w = MediaQuery.sizeOf(context).width;
    final cols = w >= 1300 ? 3 : (w >= 800 ? 2 : 1);
    return Scaffold(
      body: courses.when(
        loading: () => const Center(child: CircularProgressIndicator()),
        error: (e, _) => EmptyState(icon: Icons.cloud_off, title: '课程信息需要联网获取', message: '$e'),
        data: (list) => list.isEmpty
            ? const EmptyState(icon: Icons.class_outlined, title: '还没有课程', message: '添加 Moodle 来源后，每门课会有一个主页。添加“教师信息”模板可以补充老师的办公室与邮箱。')
            : GridView.builder(
                padding: const EdgeInsets.fromLTRB(16, 8, 16, 96),
                gridDelegate: SliverGridDelegateWithFixedCrossAxisCount(crossAxisCount: cols, mainAxisSpacing: 14, crossAxisSpacing: 14, mainAxisExtent: 360),
                itemCount: list.length,
                itemBuilder: (_, i) => _CourseCard(list[i]),
              ),
      ),
    );
  }
}

class _CourseCard extends StatelessWidget {
  final Course c;
  const _CourseCard(this.c);

  void _open(BuildContext context) => context.push('/courses/detail', extra: c.name);

  @override
  Widget build(BuildContext context) {
    final t = Theme.of(context);
    final cs = t.colorScheme;
    final color = Brand.course(c.name);
    final open = c.assignments.where((a) => !a.isDone && (a.deadline?.isAfter(DateTime.now()) ?? false)).toList();
    final code = c.name.split(' ').first;
    return Card(
      clipBehavior: Clip.antiAlias,
      child: InkWell(
        onTap: () => _open(context),
        child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
          Container(
            padding: const EdgeInsets.fromLTRB(18, 16, 18, 14),
            decoration: BoxDecoration(gradient: LinearGradient(colors: [color.withValues(alpha: 0.22), color.withValues(alpha: 0.06)])),
            child: Row(children: [
              Expanded(
                child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
                  if (code != c.name) Text(code, style: t.textTheme.labelMedium?.copyWith(color: color, fontWeight: FontWeight.w800)),
                  Text(shortCourse(c.name), style: t.textTheme.titleMedium?.copyWith(fontWeight: FontWeight.w800), maxLines: 1, overflow: TextOverflow.ellipsis),
                ]),
              ),
              Column(children: [
                Text('${open.length}', style: t.textTheme.headlineSmall?.copyWith(fontWeight: FontWeight.w800, color: color)),
                Text('待完成', style: t.textTheme.labelSmall),
              ]),
            ]),
          ),
          Expanded(
            child: ListView(
              padding: const EdgeInsets.fromLTRB(12, 8, 12, 8),
              physics: const NeverScrollableScrollPhysics(),
              children: [
                for (final a in open.take(3))
                  ListTile(
                    dense: true,
                    contentPadding: const EdgeInsets.symmetric(horizontal: 6),
                    leading: const Icon(Icons.assignment_outlined, size: 20),
                    title: Text(a.title, maxLines: 1, overflow: TextOverflow.ellipsis),
                    trailing: DeadlineBadge(a.deadline!),
                    onTap: () => context.push('/item/${a.id}'),
                  ),
                for (final n in c.notices.take(2))
                  ListTile(
                    dense: true,
                    contentPadding: const EdgeInsets.symmetric(horizontal: 6),
                    leading: Icon(kindIcon(n.kind), size: 20),
                    title: Text(n.title, maxLines: 1, overflow: TextOverflow.ellipsis),
                    subtitle: Text(relative(n.sortTime)),
                    onTap: () => context.push('/item/${n.id}'),
                  ),
                if (open.isEmpty && c.notices.isEmpty)
                  Padding(padding: const EdgeInsets.all(12), child: Text('暂无待办', style: TextStyle(color: cs.onSurfaceVariant))),
              ],
            ),
          ),
          const Divider(),
          Padding(
            padding: const EdgeInsets.fromLTRB(14, 6, 14, 12),
            child: c.teachers.isEmpty
                ? Text('添加“教师信息”来源以显示老师联系方式', style: TextStyle(fontSize: 12, color: cs.onSurfaceVariant))
                : Column(children: [for (final te in c.teachers.take(1)) _TeacherRow(te)]),
          ),
        ]),
      ),
    );
  }
}

class _TeacherRow extends StatelessWidget {
  final Teacher t;
  const _TeacherRow(this.t);
  @override
  Widget build(BuildContext context) {
    final cs = Theme.of(context).colorScheme;
    return Row(children: [
      Avatar(t.name, size: 34),
      const SizedBox(width: 10),
      Expanded(
        child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
          Text('${t.name} ${t.title}', style: const TextStyle(fontWeight: FontWeight.w700)),
          Text('${t.office}  ·  ${t.phone}', style: TextStyle(fontSize: 12, color: cs.onSurfaceVariant), maxLines: 1, overflow: TextOverflow.ellipsis),
        ]),
      ),
      if (t.email.isNotEmpty)
        IconButton(
          tooltip: t.email,
          icon: const Icon(Icons.alternate_email),
          onPressed: () {
            Clipboard.setData(ClipboardData(text: t.email));
            launchUrl(Uri.parse('mailto:${t.email}'));
          },
        ),
    ]);
  }
}
