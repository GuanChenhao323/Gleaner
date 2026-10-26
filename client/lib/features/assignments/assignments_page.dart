import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:go_router/go_router.dart';
import 'package:table_calendar/table_calendar.dart';

import '../../core/format.dart';
import '../../core/models.dart';
import '../../core/providers.dart';
import '../../core/store.dart';
import '../../theme.dart';
import '../../widgets/common.dart';

enum _AssignView { list, calendar }

class AssignmentsPage extends ConsumerStatefulWidget {
  final bool initialCalendar;
  const AssignmentsPage({super.key, this.initialCalendar = false});
  @override
  ConsumerState<AssignmentsPage> createState() => _AssignmentsPageState();
}

class _AssignmentsPageState extends ConsumerState<AssignmentsPage> {
  String? course;
  bool showDone = false;
  late _AssignView view = widget.initialCalendar ? _AssignView.calendar : _AssignView.list;
  DateTime focused = DateTime.now();
  DateTime selected = DateTime.now();
  CalendarFormat format = CalendarFormat.month;

  @override
  Widget build(BuildContext context) {
    final all = ref.watch(assignmentsProvider);
    final courses = {for (final a in all) if (a.course.isNotEmpty) a.course}.toList()..sort();
    final list = all.where((a) => course == null || a.course == course).toList();
    final deadlines = list.where((a) => a.deadline != null && (showDone || !a.isDone)).toList();
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
    final wide = MediaQuery.sizeOf(context).width >= 1000;

    return Scaffold(
      body: CustomScrollView(slivers: [
        SliverAppBar(
          pinned: true,
          title: const Text('作业'),
          actions: [
            Padding(
              padding: const EdgeInsets.symmetric(vertical: 10),
              child: SegmentedButton<_AssignView>(
                style: const ButtonStyle(visualDensity: VisualDensity.compact, tapTargetSize: MaterialTapTargetSize.shrinkWrap),
                segments: const [
                  ButtonSegment(value: _AssignView.list, icon: Icon(Icons.view_agenda_outlined, size: 18), label: Text('列表')),
                  ButtonSegment(value: _AssignView.calendar, icon: Icon(Icons.calendar_month_outlined, size: 18), label: Text('日历')),
                ],
                selected: {view},
                onSelectionChanged: (s) => setState(() => view = s.first),
              ),
            ),
            const SizedBox(width: 8),
            if (view == _AssignView.list)
              FilterChip(label: const Text('已完成'), selected: showDone, onSelected: (v) => setState(() => showDone = v)),
            if (view == _AssignView.calendar)
              TextButton(
                onPressed: () => setState(() {
                  focused = DateTime.now();
                  selected = DateTime.now();
                }),
                child: const Text('今天'),
              ),
            const SizedBox(width: 8),
          ],
          bottom: courses.isEmpty
              ? null
              : PreferredSize(
                  preferredSize: const Size.fromHeight(52),
                  child: SizedBox(
                    height: 52,
                    child: SingleChildScrollView(
                      scrollDirection: Axis.horizontal,
                      padding: const EdgeInsets.fromLTRB(16, 8, 24, 8),
                      child: Row(children: [
                        for (final c in courses) ...[
                          FilterChip(
                            avatar: CircleAvatar(backgroundColor: Brand.course(c), radius: 5),
                            label: Text(shortCourse(c)),
                            selected: course == c,
                            showCheckmark: false,
                            onSelected: (_) => setState(() => course = course == c ? null : c),
                          ),
                          const SizedBox(width: 8),
                        ],
                      ]),
                    ),
                  ),
                ),
        ),
        if (list.isEmpty)
          const SliverFillRemaining(
            hasScrollBody: false,
            child: EmptyState(icon: Icons.assignment_outlined, title: '还没有作业'),
          )
        else if (view == _AssignView.list)
          SliverPadding(
            padding: const EdgeInsets.fromLTRB(16, 0, 16, 96),
            sliver: SliverList.list(children: [
              for (final k in order)
                if (groups[k] != null) ...[
                  SectionHeader(k, trailing: '${groups[k]!.length}'),
                  for (final a in groups[k]!) _AssignmentTile(a),
                ],
              if (showDone && done.isNotEmpty) ...[
                SectionHeader('已完成', trailing: '${done.length}'),
                for (final a in done) _AssignmentTile(a),
              ],
              if (!showDone && done.isNotEmpty)
                Padding(
                  padding: const EdgeInsets.only(top: 16),
                  child: Center(child: Text('${done.length} 项已完成', style: TextStyle(color: cs.onSurfaceVariant))),
                ),
            ]),
          )
        else
          SliverPadding(
            padding: const EdgeInsets.fromLTRB(16, 0, 16, 96),
            sliver: SliverToBoxAdapter(child: _calendarBody(deadlines, wide, cs)),
          ),
      ]),
    );
  }

  Widget _calendarBody(List<Item> items, bool wide, ColorScheme cs) {
    List<Item> on(DateTime d) => items.where((i) => sameDay(i.deadline!, d)).toList();
    final day = on(selected);

    final calendar = Card(
      child: Padding(
        padding: const EdgeInsets.fromLTRB(8, 8, 8, 12),
        child: TableCalendar<Item>(
          locale: 'zh_CN',
          firstDay: DateTime.now().subtract(const Duration(days: 365)),
          lastDay: DateTime.now().add(const Duration(days: 365)),
          focusedDay: focused,
          calendarFormat: format,
          startingDayOfWeek: StartingDayOfWeek.monday,
          availableCalendarFormats: const {CalendarFormat.month: '月', CalendarFormat.twoWeeks: '两周', CalendarFormat.week: '周'},
          selectedDayPredicate: (d) => sameDay(d, selected),
          eventLoader: on,
          onDaySelected: (s, f) => setState(() {
            selected = s;
            focused = f;
          }),
          onFormatChanged: (f) => setState(() => format = f),
          onPageChanged: (f) => focused = f,
          headerStyle: HeaderStyle(
            titleCentered: true,
            formatButtonShowsNext: false,
            formatButtonDecoration: BoxDecoration(border: Border.all(color: cs.outlineVariant), borderRadius: BorderRadius.circular(10)),
            titleTextStyle: Theme.of(context).textTheme.titleMedium!,
          ),
          daysOfWeekStyle: DaysOfWeekStyle(
            weekdayStyle: TextStyle(color: cs.onSurfaceVariant, fontSize: 12),
            weekendStyle: TextStyle(color: cs.onSurfaceVariant, fontSize: 12),
          ),
          calendarStyle: CalendarStyle(
            outsideDaysVisible: false,
            todayDecoration: BoxDecoration(color: cs.primaryContainer, shape: BoxShape.circle),
            todayTextStyle: TextStyle(color: cs.onPrimaryContainer, fontWeight: FontWeight.w700),
            selectedDecoration: BoxDecoration(color: cs.primary, shape: BoxShape.circle),
            weekendTextStyle: TextStyle(color: cs.onSurface),
          ),
          calendarBuilders: CalendarBuilders(
            markerBuilder: (context, d, evs) {
              if (evs.isEmpty) return null;
              final heavy = evs.length >= 3;
              return Positioned(
                bottom: 4,
                child: Row(mainAxisSize: MainAxisSize.min, children: [
                  for (final e in evs.take(3))
                    Container(
                      width: 6,
                      height: 6,
                      margin: const EdgeInsets.symmetric(horizontal: 1),
                      decoration: BoxDecoration(color: e.isDone ? cs.outline : Brand.course(e.course), shape: BoxShape.circle),
                    ),
                  if (heavy) Text('+', style: TextStyle(fontSize: 10, color: Brand.wheat, fontWeight: FontWeight.w900)),
                ]),
              );
            },
          ),
        ),
      ),
    );

    final dayList = Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
      SectionHeader(dayLabel(selected), trailing: day.isEmpty ? null : '${day.length}'),
      if (day.isEmpty)
        Padding(
          padding: const EdgeInsets.fromLTRB(8, 8, 8, 16),
          child: Text('没有截止', style: TextStyle(color: cs.onSurfaceVariant)),
        )
      else
        for (final i in day) _AssignmentTile(i),
    ]);

    if (wide) {
      return Row(crossAxisAlignment: CrossAxisAlignment.start, children: [
        Expanded(flex: 3, child: calendar),
        const SizedBox(width: 16),
        Expanded(flex: 2, child: dayList),
      ]);
    }
    return Column(crossAxisAlignment: CrossAxisAlignment.stretch, children: [calendar, const SizedBox(height: 8), dayList]);
  }
}

class _AssignmentTile extends ConsumerWidget {
  final Item a;
  const _AssignmentTile(this.a);

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final cs = Theme.of(context).colorScheme;
    final c = Brand.course(a.course);
    final accent = dueRowAccent(done: a.isDone, priority: a.priority, deadline: a.deadline);
    final bg = accent != null ? Color.alphaBlend(accent.withValues(alpha: 0.14), cs.surfaceContainerLow) : cs.surfaceContainerLow;
    return Padding(
      padding: const EdgeInsets.only(bottom: 8),
      child: Material(
        color: bg,
        shape: RoundedRectangleBorder(
          borderRadius: BorderRadius.circular(16),
          side: accent != null ? BorderSide(color: accent.withValues(alpha: 0.35)) : BorderSide.none,
        ),
        clipBehavior: Clip.antiAlias,
        child: InkWell(
          onTap: () => context.push('/item/${a.id}'),
          child: IntrinsicHeight(
            child: Row(crossAxisAlignment: CrossAxisAlignment.stretch, children: [
              Container(width: 5, color: accent ?? c),
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
                          color: a.isDone ? cs.onSurfaceVariant : accent,
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
