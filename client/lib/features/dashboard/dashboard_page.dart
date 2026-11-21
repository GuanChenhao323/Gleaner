import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:go_router/go_router.dart';

import '../../core/format.dart';
import '../../core/models.dart';
import '../../core/providers.dart';
import '../../core/session.dart';
import '../../core/store.dart';
import '../../l10n/app_localizations.dart';
import '../../theme.dart';
import '../../widgets/common.dart';
import '../inbox/item_workbench.dart' show typeIcon, typeLabel;
import 'deadline_calendar.dart';

enum _TypeFilter { all, todo, event, notice }

bool _typeMatches(Item i, _TypeFilter f) => switch (f) {
      _TypeFilter.all => true,
      _TypeFilter.todo => i.type == 'todo' && !i.isDone,
      _TypeFilter.event => i.type == 'event',
      _TypeFilter.notice => i.type == 'notice',
    };

String _typeFilterLabel(_TypeFilter f, AppLocalizations l10n) => switch (f) {
      _TypeFilter.all => l10n.filterAll,
      _TypeFilter.todo => l10n.filterTodoTasks,
      _TypeFilter.event => l10n.filterEvents,
      _TypeFilter.notice => l10n.filterNotices,
    };

/// 工作台：今日要事 + 本周一眼 + 异常信息源。
class DashboardPage extends ConsumerStatefulWidget {
  final String? initialType;
  final int? focusItemId;
  const DashboardPage({super.key, this.initialType, this.focusItemId});

  @override
  ConsumerState<DashboardPage> createState() => _DashboardPageState();
}

class _DashboardPageState extends ConsumerState<DashboardPage> {
  late _TypeFilter typeFilter = _TypeFilter.values.firstWhere((f) => f.name == widget.initialType, orElse: () => _TypeFilter.all);
  bool showCalendar = false;
  int focusLimit = 8;

  void _selectFilter(_TypeFilter filter) {
    setState(() {
      typeFilter = filter;
      focusLimit = 8;
    });
  }

  @override
  Widget build(BuildContext context) {
    final l10n = AppLocalizations.of(context);
    final me = ref.watch(sessionProvider.select((s) => s.me));
    final feed = ref.watch(feedProvider);
    final t = Theme.of(context);
    final cs = t.colorScheme;
    final now = DateTime.now();
    final weekEnd = now.add(const Duration(days: 7));
    final assignments = ref.watch(deadlinesProvider);
    final dueWeek = assignments.where((i) => !i.isDone && i.deadline!.isAfter(now) && i.deadline!.isBefore(weekEnd)).length;
    final sources = ref.watch(sourcesProvider).asData?.value ?? const <Source>[];
    final troubled = sources.where((s) => s.status == 'failed' || s.status == 'need_login').toList();
    final focus = _todayFocus(feed.visible, assignments, typeFilter);
    final target = feed.items[widget.focusItemId];
    if (target != null && typeFilter.name == widget.initialType && focus.remove(target)) {
      focus.insert(0, target);
    }
    final focusCard = _FocusCard(
      items: focus.take(focusLimit).toList(),
      filter: typeFilter,
      onFilter: _selectFilter,
      onMore: typeFilter != _TypeFilter.all && focus.length > focusLimit
          ? () => setState(() => focusLimit += 8)
          : null,
    );
    final wide = MediaQuery.sizeOf(context).width >= 960;

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
              padding: const EdgeInsets.fromLTRB(22, 20, 22, 18),
              decoration: BoxDecoration(
                borderRadius: BorderRadius.circular(24),
                color: cs.surface,
                border: Border.all(color: cs.outlineVariant),
                boxShadow: [
                  BoxShadow(color: Brand.yellow.withValues(alpha: 0.12), blurRadius: 0, offset: const Offset(0, 3)),
                ],
              ),
              child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
                Text(
                  '${dayLabel(now, context)} · ${l10n.monthDay(now.month, now.day)}',
                  style: t.textTheme.labelLarge?.copyWith(color: cs.onSurfaceVariant),
                ),
                const SizedBox(height: 4),
                Text(
                  '${greeting(context)}，${me?.name.isNotEmpty == true ? me!.name : l10n.classmate}',
                  style: t.textTheme.headlineMedium?.copyWith(color: cs.onSurface),
                ),
                const SizedBox(height: 14),
                Wrap(spacing: 18, runSpacing: 8, children: [
                  _MiniStat('${feed.unread}', l10n.inboxUnread, onCard: true, onTap: () => context.go('/inbox?filter=unread')),
                  _MiniStat('$dueWeek', l10n.deskDueIn7Days, onCard: true, highlight: dueWeek > 0, onTap: () => context.go('/courses')),
                  if (troubled.isNotEmpty)
                    _MiniStat('${troubled.length}', l10n.deskSourceIssues, onCard: true, highlight: true, onTap: () => context.go('/sources')),
                ]),
              ]),
            ),
          ),
          if (troubled.isNotEmpty)
            SliverToBoxAdapter(
              child: Padding(
                padding: const EdgeInsets.fromLTRB(16, 16, 16, 0),
                child: _AlertBanner(troubled),
              ),
            ),
          SliverPadding(
            padding: const EdgeInsets.fromLTRB(16, 20, 16, 96),
            sliver: SliverToBoxAdapter(
              child: Column(children: [
                wide
                    ? Row(crossAxisAlignment: CrossAxisAlignment.start, children: [
                        Expanded(
                          flex: 2,
                          child: focusCard,
                        ),
                        const SizedBox(width: 14),
                        Expanded(
                          child: Column(children: [
                            _SideCard(
                              title: l10n.deskThisWeek,
                              trailing: TextButton(
                                onPressed: () => setState(() => showCalendar = !showCalendar),
                                child: Text(showCalendar ? l10n.deskHideCalendar : l10n.deskCalendar),
                              ),
                              child: const _WeekLoad(),
                            ),
                            if (troubled.isNotEmpty) ...[
                              const SizedBox(height: 14),
                              _SideCard(title: l10n.deskNeedsAttention, child: _TroubledSources(troubled)),
                            ],
                          ]),
                        ),
                      ])
                    : Column(children: [
                        focusCard,
                        const SizedBox(height: 14),
                        _SideCard(
                          title: l10n.deskThisWeek,
                          trailing: TextButton(
                            onPressed: () => setState(() => showCalendar = !showCalendar),
                            child: Text(showCalendar ? l10n.deskHideCalendar : l10n.deskCalendar),
                          ),
                          child: const _WeekLoad(),
                        ),
                        if (troubled.isNotEmpty) ...[
                          const SizedBox(height: 14),
                          _SideCard(title: l10n.deskNeedsAttention, child: _TroubledSources(troubled)),
                        ],
                      ]),
                if (showCalendar) ...[
                  const SizedBox(height: 14),
                  const DeadlineCalendarCard(),
                ],
              ]),
            ),
          ),
        ]),
      ),
    );
  }
}

/// 今日要事：24h 截止 > 重要变更 > 紧急未读 > 今日待办，按最终事项类型筛选后由视图分页。
List<Item> _todayFocus(List<Item> visible, List<Item> deadlines, _TypeFilter filter) {
  final now = DateTime.now();
  final seen = <int>{};
  final out = <Item>[];

  void add(Iterable<Item> src) {
    for (final i in src) {
      if (_typeMatches(i, filter) && seen.add(i.id)) out.add(i);
    }
  }

  add(deadlines.where((i) {
    if (i.isDone || i.deadline == null) return false;
    final h = i.deadline!.difference(now).inHours;
    return h >= -12 && h < 24;
  }));
  add(visible.where((i) => i.importantChange && !i.isDone));
  add(visible.where((i) => !i.state.read && (i.priority == 'urgent' || i.importantChange)));
  add(visible.where((i) => !i.isDone && (i.type == 'todo' || i.state.todo == 'todo' || i.state.todo == 'doing')));
  add(deadlines.where((i) => !i.isDone && i.deadline != null && i.deadline!.isAfter(now)).take(4));
  if (filter != _TypeFilter.all) add(visible);
  return out;
}

class _MiniStat extends StatelessWidget {
  final String value;
  final String label;
  final bool highlight;
  final bool onCard;
  final VoidCallback onTap;
  const _MiniStat(this.value, this.label, {required this.onTap, this.highlight = false, this.onCard = false});

  @override
  Widget build(BuildContext context) {
    final cs = Theme.of(context).colorScheme;
    final muted = onCard ? cs.onPrimaryContainer.withValues(alpha: 0.75) : cs.onSurfaceVariant;
    final color = highlight ? Brand.urgent : (onCard ? cs.onPrimaryContainer : cs.onSurface);
    return InkWell(
      borderRadius: BorderRadius.circular(8),
      onTap: onTap,
      child: Padding(
        padding: const EdgeInsets.symmetric(horizontal: 2, vertical: 2),
        child: Text.rich(TextSpan(children: [
          TextSpan(text: value, style: TextStyle(fontWeight: FontWeight.w800, fontSize: 18, color: color)),
          TextSpan(text: '  $label', style: TextStyle(color: muted, fontSize: 13)),
        ])),
      ),
    );
  }
}

class _AlertBanner extends StatelessWidget {
  final List<Source> troubled;
  const _AlertBanner(this.troubled);

  @override
  Widget build(BuildContext context) {
    final l10n = AppLocalizations.of(context);
    final cs = Theme.of(context).colorScheme;
    final first = troubled.first;
    final text = first.status == 'need_login'
        ? l10n.sourceNeedLoginNamed(first.name)
        : l10n.sourceCheckFailedNamed(first.name);
    return Material(
      color: Brand.urgent.withValues(alpha: 0.12),
      borderRadius: BorderRadius.circular(14),
      child: InkWell(
        borderRadius: BorderRadius.circular(14),
        onTap: () => context.go('/sources'),
        child: Padding(
          padding: const EdgeInsets.symmetric(horizontal: 14, vertical: 12),
          child: Row(children: [
            const Icon(Icons.report_gmailerrorred, color: Brand.urgent, size: 20),
            const SizedBox(width: 10),
            Expanded(child: Text(text, style: const TextStyle(fontWeight: FontWeight.w600))),
            if (troubled.length > 1) Text(l10n.andMoreItems(troubled.length), style: TextStyle(color: cs.onSurfaceVariant, fontSize: 12)),
            const Icon(Icons.chevron_right, size: 20),
          ]),
        ),
      ),
    );
  }
}

class _FocusCard extends StatelessWidget {
  final List<Item> items;
  final _TypeFilter filter;
  final ValueChanged<_TypeFilter> onFilter;
  final VoidCallback? onMore;
  const _FocusCard({required this.items, required this.filter, required this.onFilter, this.onMore});

  @override
  Widget build(BuildContext context) {
    final l10n = AppLocalizations.of(context);
    final t = Theme.of(context);
    final cs = t.colorScheme;
    return Card(
      child: Padding(
        padding: const EdgeInsets.fromLTRB(8, 14, 8, 10),
        child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
          Padding(
            padding: const EdgeInsets.fromLTRB(10, 0, 10, 8),
            child: Row(children: [
              Text(filter == _TypeFilter.all ? l10n.deskTodayFocus : _typeFilterLabel(filter, l10n), style: t.textTheme.titleSmall?.copyWith(fontWeight: FontWeight.w800)),
              const Spacer(),
              TextButton(onPressed: () => context.go('/inbox'), child: Text(l10n.deskInboxLink)),
            ]),
          ),
          SingleChildScrollView(
            scrollDirection: Axis.horizontal,
            padding: const EdgeInsets.fromLTRB(6, 0, 6, 8),
            child: Row(children: [
              for (final f in _TypeFilter.values) ...[
                FilterChip(
                  label: Text(_typeFilterLabel(f, l10n)),
                  selected: filter == f,
                  showCheckmark: false,
                  onSelected: (_) => onFilter(f),
                ),
                const SizedBox(width: 8),
              ],
            ]),
          ),
          if (items.isEmpty)
            Padding(
              padding: const EdgeInsets.fromLTRB(10, 20, 10, 28),
              child: Text(
                filter == _TypeFilter.all ? l10n.deskEmptyToday : l10n.deskEmptyFilter(_typeFilterLabel(filter, l10n)),
                style: TextStyle(color: cs.onSurfaceVariant),
              ),
            )
          else
            for (final i in items) _FocusRow(i),
          if (onMore != null) TextButton(onPressed: onMore, child: Text(l10n.deskShowMore)),
        ]),
      ),
    );
  }
}

class _FocusRow extends StatelessWidget {
  final Item item;
  const _FocusRow(this.item);

  @override
  Widget build(BuildContext context) {
    final l10n = AppLocalizations.of(context);
    final cs = Theme.of(context).colorScheme;
    final accent = dueRowAccent(done: item.isDone, priority: item.priority, deadline: item.deadline);
    final status = item.importantChange
        ? l10n.statusChanged
        : (item.priority == 'urgent' || accent == Brand.dueCritical
            ? l10n.statusUrgent
            : (!item.state.read ? l10n.unreadStatus : null));
    return InkWell(
      borderRadius: BorderRadius.circular(12),
      onTap: () => context.push('/item/${item.id}'),
      child: Container(
        margin: const EdgeInsets.symmetric(horizontal: 4, vertical: 3),
        padding: const EdgeInsets.fromLTRB(10, 10, 10, 10),
        decoration: BoxDecoration(
          color: cs.surface,
          borderRadius: BorderRadius.circular(12),
          border: Border.all(color: cs.outlineVariant),
        ),
        child: Row(children: [
          Container(
            width: 3,
            height: 36,
            decoration: BoxDecoration(color: accent ?? cs.outlineVariant, borderRadius: BorderRadius.circular(2)),
          ),
          const SizedBox(width: 10),
          Icon(typeIcon(item.type), size: 18, color: cs.onSurfaceVariant),
          const SizedBox(width: 8),
          Expanded(
            child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
              Text(item.title, maxLines: 1, overflow: TextOverflow.ellipsis, style: TextStyle(fontWeight: FontWeight.w700, color: cs.onSurface)),
              const SizedBox(height: 2),
              Text(
                [
                  typeLabel(item.type, context),
                  if (item.course.isNotEmpty) shortCourse(item.course),
                  ?status,
                ].join(' · '),
                maxLines: 1,
                overflow: TextOverflow.ellipsis,
                style: TextStyle(fontSize: 12, color: cs.onSurfaceVariant),
              ),
            ]),
          ),
          if (item.deadline != null) DeadlineBadge(item.deadline!, done: item.isDone),
        ]),
      ),
    );
  }
}

class _SideCard extends StatelessWidget {
  final String title;
  final Widget child;
  final Widget? trailing;
  const _SideCard({required this.title, required this.child, this.trailing});

  @override
  Widget build(BuildContext context) {
    return Card(
      child: Padding(
        padding: const EdgeInsets.fromLTRB(16, 14, 16, 14),
        child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
          Row(children: [
            Text(title, style: Theme.of(context).textTheme.titleSmall?.copyWith(fontWeight: FontWeight.w800)),
            const Spacer(),
            ?trailing,
          ]),
          const SizedBox(height: 12),
          child,
        ]),
      ),
    );
  }
}

class _WeekLoad extends ConsumerWidget {
  const _WeekLoad();
  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final cs = Theme.of(context).colorScheme;
    final now = DateTime.now();
    final start = DateTime(now.year, now.month, now.day);
    final list = ref.watch(deadlinesProvider).where((i) => !i.isDone && i.deadline != null).toList();
    final days = List.generate(7, (d) => start.add(Duration(days: d)));
    final counts = [for (final d in days) list.where((i) => sameDay(i.deadline!, d)).toList()];
    final maxN = counts.fold<int>(1, (m, l) => l.length > m ? l.length : m);
    return SizedBox(
      height: 150,
      child: Row(crossAxisAlignment: CrossAxisAlignment.end, children: [
        for (var d = 0; d < 7; d++)
          Expanded(
            child: Tooltip(
              message: counts[d].isEmpty ? AppLocalizations.of(context).noDeadlines : counts[d].map((i) => i.title).join('\n'),
              child: InkWell(
                borderRadius: BorderRadius.circular(8),
                onTap: () {
                  final course = counts[d].isNotEmpty && counts[d].first.course.isNotEmpty ? counts[d].first.course : null;
                  if (course != null) {
                    context.push('/courses/detail', extra: course);
                  } else {
                    context.go('/courses');
                  }
                },
                child: Padding(
                  padding: const EdgeInsets.symmetric(horizontal: 2),
                  child: Column(mainAxisAlignment: MainAxisAlignment.end, children: [
                    if (counts[d].isNotEmpty) Text('${counts[d].length}', style: const TextStyle(fontWeight: FontWeight.w800, fontSize: 12)),
                    const SizedBox(height: 4),
                    AnimatedContainer(
                      duration: const Duration(milliseconds: 400),
                      height: 8 + 80.0 * counts[d].length / maxN,
                      decoration: BoxDecoration(
                        borderRadius: BorderRadius.circular(8),
                        color: counts[d].length >= 2
                            ? Brand.wheat
                            : (counts[d].isEmpty ? cs.surfaceContainerHighest : cs.primary),
                      ),
                    ),
                    const SizedBox(height: 8),
                    Text(
                      d == 0 ? AppLocalizations.of(context).todayShort : weekday(days[d], context),
                      style: TextStyle(fontSize: 11, color: d == 0 ? cs.primary : cs.onSurfaceVariant, fontWeight: d == 0 ? FontWeight.w700 : null),
                    ),
                  ]),
                ),
              ),
            ),
          ),
      ]),
    );
  }
}

class _TroubledSources extends StatelessWidget {
  final List<Source> list;
  const _TroubledSources(this.list);

  @override
  Widget build(BuildContext context) {
    return Column(children: [
      for (final src in list.take(5))
        InkWell(
          borderRadius: BorderRadius.circular(10),
          onTap: () => context.go('/sources'),
          child: Padding(
            padding: const EdgeInsets.symmetric(vertical: 8),
            child: Row(children: [
              Icon(sourceIcon(src.type), size: 20),
              const SizedBox(width: 10),
              Expanded(
                child: Text(src.name, maxLines: 1, overflow: TextOverflow.ellipsis, style: const TextStyle(fontWeight: FontWeight.w600)),
              ),
              SourceStatusPill(src),
            ]),
          ),
        ),
    ]);
  }
}
