import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:go_router/go_router.dart';

import '../../core/format.dart';
import '../../core/models.dart';
import '../../core/providers.dart';
import '../../core/session.dart';
import '../../core/store.dart';
import '../../theme.dart';
import '../../widgets/common.dart';

const widgetCatalog = {
  'deadlines': ('近期截止', Icons.timer_outlined),
  'inbox': ('未读通知', Icons.mark_email_unread_outlined),
  'calendar': ('本周任务分布', Icons.calendar_view_week),
  'todo': ('待办', Icons.checklist),
  'sources': ('来源状态', Icons.hub_outlined),
  'starred': ('收藏', Icons.star_outline),
};

class DashboardPage extends ConsumerStatefulWidget {
  const DashboardPage({super.key});
  @override
  ConsumerState<DashboardPage> createState() => _DashboardPageState();
}

class _DashboardPageState extends ConsumerState<DashboardPage> {
  bool editing = false;

  @override
  Widget build(BuildContext context) {
    final me = ref.watch(sessionProvider.select((s) => s.me));
    final feed = ref.watch(feedProvider);
    final layout = ref.watch(dashboardProvider);
    final t = Theme.of(context);
    final cs = t.colorScheme;
    final now = DateTime.now();
    final weekEnd = now.add(const Duration(days: 7));
    final assignments = ref.watch(deadlinesProvider);
    final dueWeek = assignments.where((i) => !i.isDone && i.deadline!.isAfter(now) && i.deadline!.isBefore(weekEnd)).length;
    final todo = feed.visible.where((i) => i.state.todo == 'todo' || i.state.todo == 'doing').length;
    final sources = ref.watch(sourcesProvider).asData?.value ?? const <Source>[];
    final troubled = sources.where((s) => s.status == 'failed' || s.status == 'need_login').length;
    final width = MediaQuery.sizeOf(context).width;
    final cols = width >= 1200 ? 3 : (width >= 760 ? 2 : 1);

    return Scaffold(
      body: RefreshIndicator(
        onRefresh: () async {
          await ref.read(feedProvider.notifier).refreshAll();
          ref.invalidate(sourcesProvider);
        },
        child: CustomScrollView(slivers: [
          SliverToBoxAdapter(
            child: Container(
              margin: const EdgeInsets.fromLTRB(16, 16, 16, 0),
              padding: const EdgeInsets.fromLTRB(24, 24, 24, 20),
              decoration: BoxDecoration(
                borderRadius: BorderRadius.circular(28),
                gradient: LinearGradient(
                  colors: [cs.primaryContainer, Color.lerp(cs.primaryContainer, Brand.wheat, 0.25)!],
                  begin: Alignment.topLeft,
                  end: Alignment.bottomRight,
                ),
              ),
              child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
                Row(crossAxisAlignment: CrossAxisAlignment.start, children: [
                  Expanded(
                    child: Text('${dayLabel(now)} · ${now.month}月${now.day}日', style: t.textTheme.labelLarge?.copyWith(color: cs.onPrimaryContainer.withValues(alpha: 0.8))),
                  ),
                  const ConnectionDot(showLabel: true),
                ]),
                const SizedBox(height: 4),
                Text('${greeting()}，${me?.name.isNotEmpty == true ? me!.name : '同学'}', style: t.textTheme.headlineMedium?.copyWith(color: cs.onPrimaryContainer)),
                const SizedBox(height: 6),
                Text(
                  dueWeek == 0 ? '未来 7 天没有待交的作业，可以喘口气了。' : '未来 7 天有 $dueWeek 项待完成，最近的一项${_nextDue(assignments)}',
                  style: t.textTheme.bodyMedium?.copyWith(color: cs.onPrimaryContainer.withValues(alpha: 0.85)),
                ),
                const SizedBox(height: 18),
                LayoutBuilder(builder: (context, c) {
                  final tileW = c.maxWidth < 640 ? (c.maxWidth - 12) / 2 : 160.0;
                  return Wrap(spacing: 12, runSpacing: 12, children: [
                  _Stat(width: tileW, label: '未读', value: feed.unread, icon: Icons.mark_email_unread_outlined, onTap: () => context.go('/inbox')),
                  _Stat(width: tileW, label: '7 天内截止', value: dueWeek, icon: Icons.timer_outlined, highlight: dueWeek > 0, onTap: () => context.go('/assignments')),
                  _Stat(width: tileW, label: '待办', value: todo, icon: Icons.checklist, onTap: () => context.go('/inbox?filter=todo')),
                  _Stat(width: tileW, label: '来源异常', value: troubled, icon: Icons.report_gmailerrorred, highlight: troubled > 0, onTap: () => context.go('/sources')),
                  ]);
                }),
              ]),
            ),
          ),
          SliverToBoxAdapter(
            child: Padding(
              padding: const EdgeInsets.fromLTRB(20, 20, 12, 4),
              child: Row(children: [
                Text('我的看板', style: t.textTheme.titleMedium),
                const Spacer(),
                if (editing)
                  TextButton.icon(onPressed: () => _addWidget(layout.asData?.value ?? []), icon: const Icon(Icons.add), label: const Text('添加组件')),
                TextButton.icon(
                  onPressed: () => setState(() => editing = !editing),
                  icon: Icon(editing ? Icons.check : Icons.dashboard_customize_outlined),
                  label: Text(editing ? '完成' : '编辑'),
                ),
              ]),
            ),
          ),
          layout.when(
            loading: () => const SliverToBoxAdapter(child: Padding(padding: EdgeInsets.all(40), child: Center(child: CircularProgressIndicator()))),
            error: (e, _) => SliverToBoxAdapter(child: Padding(padding: const EdgeInsets.all(24), child: Text('看板加载失败：$e'))),
            data: (ws) => editing ? _editor(ws) : _grid(ws, cols),
          ),
          const SliverToBoxAdapter(child: SizedBox(height: 96)),
        ]),
      ),
    );
  }

  String _nextDue(List<Item> list) {
    final now = DateTime.now();
    final next = list.where((i) => !i.isDone && i.deadline!.isAfter(now)).firstOrNull;
    if (next == null) return '。';
    return '「${next.title}」${countdown(next.deadline!)}。';
  }

  Widget _grid(List<DashWidget> ws, int cols) {
    return SliverPadding(
      padding: const EdgeInsets.symmetric(horizontal: 16),
      sliver: SliverToBoxAdapter(
        child: LayoutBuilder(builder: (context, c) {
          const gap = 14.0;
          final colW = (c.maxWidth - gap * (cols - 1)) / cols;
          return Wrap(spacing: gap, runSpacing: gap, children: [
            for (final w in ws)
              SizedBox(
                width: cols == 1 ? c.maxWidth : (w.span >= 2 ? colW * 2 + gap : colW).clamp(0, c.maxWidth),
                child: DashCard(widget: w),
              ),
          ]);
        }),
      ),
    );
  }

  Widget _editor(List<DashWidget> ws) {
    return SliverPadding(
      padding: const EdgeInsets.symmetric(horizontal: 16),
      sliver: SliverReorderableList(
        itemCount: ws.length,
        onReorderItem: (a, b) {
          final list = [...ws];
          list.insert(b, list.removeAt(a));
          ref.read(dashboardProvider.notifier).save(list);
        },
        itemBuilder: (context, i) {
          final w = ws[i];
          final meta = widgetCatalog[w.type];
          return Padding(
            key: ValueKey(w.id),
            padding: const EdgeInsets.only(bottom: 8),
            child: Card(
              child: ListTile(
                leading: ReorderableDragStartListener(index: i, child: const Icon(Icons.drag_indicator)),
                title: Text(w.title.isEmpty ? (meta?.$1 ?? w.type) : w.title),
                subtitle: Text(w.span >= 2 ? '宽组件' : '标准组件'),
                trailing: Row(mainAxisSize: MainAxisSize.min, children: [
                  IconButton(
                    tooltip: '切换宽度',
                    icon: Icon(w.span >= 2 ? Icons.close_fullscreen : Icons.open_in_full),
                    onPressed: () {
                      final list = [...ws];
                      list[i] = DashWidget(w.id, w.type, w.title, w.span >= 2 ? 1 : 2);
                      ref.read(dashboardProvider.notifier).save(list);
                    },
                  ),
                  IconButton(
                    tooltip: '移除',
                    icon: const Icon(Icons.delete_outline),
                    onPressed: () => ref.read(dashboardProvider.notifier).save([...ws]..removeAt(i)),
                  ),
                ]),
              ),
            ),
          );
        },
      ),
    );
  }

  Future<void> _addWidget(List<DashWidget> ws) async {
    final type = await showModalBottomSheet<String>(
      context: context,
      builder: (_) => SafeArea(
        child: Column(mainAxisSize: MainAxisSize.min, children: [
          for (final e in widgetCatalog.entries)
            ListTile(leading: Icon(e.value.$2), title: Text(e.value.$1), onTap: () => Navigator.pop(context, e.key)),
        ]),
      ),
    );
    if (type == null) return;
    final id = 'w${DateTime.now().millisecondsSinceEpoch}';
    await ref.read(dashboardProvider.notifier).save([...ws, DashWidget(id, type, widgetCatalog[type]!.$1, type == 'calendar' ? 2 : 1)]);
  }
}

class _Stat extends StatelessWidget {
  final String label;
  final int value;
  final IconData icon;
  final bool highlight;
  final VoidCallback onTap;
  final double width;
  const _Stat({required this.label, required this.value, required this.icon, required this.onTap, this.highlight = false, this.width = 160});

  @override
  Widget build(BuildContext context) {
    final cs = Theme.of(context).colorScheme;
    return Material(
      color: cs.surface.withValues(alpha: 0.75),
      borderRadius: BorderRadius.circular(18),
      child: InkWell(
        borderRadius: BorderRadius.circular(18),
        onTap: onTap,
        child: Container(
          width: width,
          padding: const EdgeInsets.all(14),
          child: Row(children: [
            Container(
              padding: const EdgeInsets.all(8),
              decoration: BoxDecoration(color: (highlight ? Brand.wheat : cs.primary).withValues(alpha: 0.15), borderRadius: BorderRadius.circular(12)),
              child: Icon(icon, size: 20, color: highlight ? Brand.wheat : cs.primary),
            ),
            const SizedBox(width: 12),
            Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
              Text('$value', style: Theme.of(context).textTheme.titleLarge?.copyWith(fontWeight: FontWeight.w800)),
              Text(label, style: Theme.of(context).textTheme.labelSmall?.copyWith(color: cs.onSurfaceVariant)),
            ]),
          ]),
        ),
      ),
    );
  }
}

class DashCard extends ConsumerWidget {
  final DashWidget widget;
  const DashCard({super.key, required this.widget});

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final meta = widgetCatalog[widget.type];
    final t = Theme.of(context);
    return Card(
      child: Padding(
        padding: const EdgeInsets.fromLTRB(18, 16, 18, 16),
        child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
          Row(children: [
            Icon(meta?.$2 ?? Icons.widgets_outlined, size: 18, color: t.colorScheme.primary),
            const SizedBox(width: 8),
            Text(widget.title.isEmpty ? (meta?.$1 ?? '') : widget.title, style: t.textTheme.titleSmall?.copyWith(fontWeight: FontWeight.w700)),
          ]),
          const SizedBox(height: 12),
          switch (widget.type) {
            'deadlines' => const _DeadlineTimeline(),
            'inbox' => const _UnreadList(),
            'calendar' => const _WeekLoad(),
            'todo' => const _TodoList(),
            'sources' => const _SourceHealth(),
            'starred' => const _StarredList(),
            _ => const Text('未知组件'),
          },
        ]),
      ),
    );
  }
}

class _MiniRow extends StatelessWidget {
  final Item item;
  final Widget? trailing;
  final Widget? leading;
  const _MiniRow(this.item, {this.trailing, this.leading});
  @override
  Widget build(BuildContext context) {
    final cs = Theme.of(context).colorScheme;
    return InkWell(
      borderRadius: BorderRadius.circular(10),
      onTap: () => context.push('/item/${item.id}'),
      child: Padding(
        padding: const EdgeInsets.symmetric(vertical: 7, horizontal: 2),
        child: Row(children: [
          leading ?? Container(width: 4, height: 32, decoration: BoxDecoration(color: Brand.course(item.course), borderRadius: BorderRadius.circular(2))),
          const SizedBox(width: 10),
          Expanded(
            child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
              Text(item.title, maxLines: 1, overflow: TextOverflow.ellipsis, style: const TextStyle(fontWeight: FontWeight.w600)),
              Text(item.course.isNotEmpty ? shortCourse(item.course) : (item.source?.name ?? ''),
                  maxLines: 1, overflow: TextOverflow.ellipsis, style: TextStyle(color: cs.onSurfaceVariant, fontSize: 12)),
            ]),
          ),
          ?trailing,
        ]),
      ),
    );
  }
}

class _DeadlineTimeline extends ConsumerWidget {
  const _DeadlineTimeline();
  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final now = DateTime.now();
    final list = ref.watch(deadlinesProvider).where((i) => !i.isDone && i.deadline!.isAfter(now)).take(6).toList();
    if (list.isEmpty) return const _Muted('近期没有截止事项');
    return Column(children: [for (final i in list) _MiniRow(i, trailing: DeadlineBadge(i.deadline!))]);
  }
}

class _UnreadList extends ConsumerWidget {
  const _UnreadList();
  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final list = ref.watch(feedProvider.select((s) => s.visible.where((i) => !i.state.read && i.kind != 'assignment').take(5).toList()));
    if (list.isEmpty) return const _Muted('全部读完了');
    return Column(children: [
      for (final i in list)
        _MiniRow(i,
            leading: Icon(kindIcon(i.kind), size: 20, color: Theme.of(context).colorScheme.primary),
            trailing: Text(relative(i.sortTime), style: Theme.of(context).textTheme.labelSmall)),
    ]);
  }
}

class _TodoList extends ConsumerWidget {
  const _TodoList();
  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final list = ref.watch(feedProvider.select((s) => s.visible.where((i) => i.state.todo == 'todo' || i.state.todo == 'doing').take(6).toList()));
    if (list.isEmpty) return const _Muted('左滑任意事项即可加入待办');
    return Column(children: [
      for (final i in list)
        _MiniRow(i,
            leading: Checkbox(value: false, onChanged: (_) => ref.read(feedProvider.notifier).setState(i, todo: 'done')),
            trailing: i.deadline != null ? DeadlineBadge(i.deadline!) : null),
    ]);
  }
}

class _StarredList extends ConsumerWidget {
  const _StarredList();
  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final list = ref.watch(feedProvider.select((s) => s.visible.where((i) => i.state.starred).take(6).toList()));
    if (list.isEmpty) return const _Muted('收藏的通知会出现在这里，方便报名时再找到');
    return Column(children: [for (final i in list) _MiniRow(i, leading: const Icon(Icons.star_rounded, color: Brand.wheat, size: 20))]);
  }
}

/// 本周每天的截止数量：一眼看出任务是否扎堆。
class _WeekLoad extends ConsumerWidget {
  const _WeekLoad();
  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final cs = Theme.of(context).colorScheme;
    final now = DateTime.now();
    final start = DateTime(now.year, now.month, now.day);
    final list = ref.watch(deadlinesProvider).where((i) => !i.isDone).toList();
    final days = List.generate(7, (d) => start.add(Duration(days: d)));
    final counts = [for (final d in days) list.where((i) => sameDay(i.deadline!, d)).toList()];
    final maxN = counts.fold<int>(1, (m, l) => l.length > m ? l.length : m);
    return SizedBox(
      height: 150,
      child: Row(crossAxisAlignment: CrossAxisAlignment.end, children: [
        for (var d = 0; d < 7; d++)
          Expanded(
            child: Tooltip(
              message: counts[d].isEmpty ? '没有截止' : counts[d].map((i) => i.title).join('\n'),
              child: Padding(
                padding: const EdgeInsets.symmetric(horizontal: 4),
                child: Column(mainAxisAlignment: MainAxisAlignment.end, children: [
                  if (counts[d].isNotEmpty) Text('${counts[d].length}', style: const TextStyle(fontWeight: FontWeight.w800)),
                  const SizedBox(height: 4),
                  AnimatedContainer(
                    duration: const Duration(milliseconds: 400),
                    height: 8 + 80.0 * counts[d].length / maxN,
                    decoration: BoxDecoration(
                      borderRadius: BorderRadius.circular(8),
                      color: counts[d].length >= 2 ? Brand.wheat : (counts[d].isEmpty ? cs.surfaceContainerHighest : cs.primary),
                    ),
                  ),
                  const SizedBox(height: 8),
                  Text(d == 0 ? '今天' : weekday(days[d]), style: TextStyle(fontSize: 12, color: d == 0 ? cs.primary : cs.onSurfaceVariant, fontWeight: d == 0 ? FontWeight.w700 : null)),
                  Text('${days[d].day}', style: TextStyle(fontSize: 11, color: cs.onSurfaceVariant)),
                ]),
              ),
            ),
          ),
      ]),
    );
  }
}

class _SourceHealth extends ConsumerWidget {
  const _SourceHealth();
  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final s = ref.watch(sourcesProvider);
    return s.when(
      loading: () => const LinearProgressIndicator(),
      error: (e, _) => _Muted('离线：显示缓存内容'),
      data: (list) {
        if (list.isEmpty) return const _Muted('还没有添加来源');
        return Column(children: [
          for (final src in list.take(6))
            InkWell(
              borderRadius: BorderRadius.circular(10),
              onTap: () => context.go('/sources'),
              child: Padding(
                padding: const EdgeInsets.symmetric(vertical: 6),
                child: Row(children: [
                  Icon(sourceIcon(src.type), size: 20),
                  const SizedBox(width: 10),
                  Expanded(
                    child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
                      Text(src.name, maxLines: 1, overflow: TextOverflow.ellipsis, style: const TextStyle(fontWeight: FontWeight.w600)),
                      Text('最后检查：${relative(tsToDate(src.lastSuccessAt))}', style: TextStyle(fontSize: 12, color: Theme.of(context).colorScheme.onSurfaceVariant)),
                    ]),
                  ),
                  SourceStatusPill(src),
                ]),
              ),
            ),
        ]);
      },
    );
  }
}

class _Muted extends StatelessWidget {
  final String text;
  const _Muted(this.text);
  @override
  Widget build(BuildContext context) => Padding(
        padding: const EdgeInsets.symmetric(vertical: 14),
        child: Text(text, style: TextStyle(color: Theme.of(context).colorScheme.onSurfaceVariant)),
      );
}
