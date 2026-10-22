import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:go_router/go_router.dart';
import 'package:table_calendar/table_calendar.dart';

import '../../core/format.dart';
import '../../core/models.dart';
import '../../core/providers.dart';
import '../../theme.dart';
import '../../widgets/common.dart';

class CalendarPage extends ConsumerStatefulWidget {
  const CalendarPage({super.key});
  @override
  ConsumerState<CalendarPage> createState() => _CalendarPageState();
}

class _CalendarPageState extends ConsumerState<CalendarPage> {
  DateTime focused = DateTime.now();
  DateTime selected = DateTime.now();
  CalendarFormat format = CalendarFormat.month;

  @override
  Widget build(BuildContext context) {
    final items = ref.watch(deadlinesProvider);
    List<Item> on(DateTime d) => items.where((i) => sameDay(i.deadline!, d)).toList();
    final cs = Theme.of(context).colorScheme;
    final wide = MediaQuery.sizeOf(context).width >= 1000;
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
          daysOfWeekStyle: DaysOfWeekStyle(weekdayStyle: TextStyle(color: cs.onSurfaceVariant, fontSize: 12), weekendStyle: TextStyle(color: cs.onSurfaceVariant, fontSize: 12)),
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
      SectionHeader(dayLabel(selected), trailing: day.isEmpty ? '没有截止事项' : '${day.length} 项截止'),
      if (day.isEmpty)
        Padding(
          padding: const EdgeInsets.all(24),
          child: Text('这一天很清闲。', style: TextStyle(color: cs.onSurfaceVariant)),
        ),
      for (final i in day)
        Card(
          margin: const EdgeInsets.only(bottom: 8),
          child: ListTile(
            onTap: () => context.push('/item/${i.id}'),
            leading: Container(width: 6, height: 40, decoration: BoxDecoration(color: Brand.course(i.course), borderRadius: BorderRadius.circular(3))),
            title: Text(i.title, style: TextStyle(fontWeight: FontWeight.w600, decoration: i.isDone ? TextDecoration.lineThrough : null)),
            subtitle: Text('${i.deadline!.hour.toString().padLeft(2, '0')}:${i.deadline!.minute.toString().padLeft(2, '0')} 截止 · ${i.course.isNotEmpty ? shortCourse(i.course) : kindLabel(i.kind)}'),
            trailing: i.importantChange ? const Icon(Icons.auto_awesome, color: Brand.wheat) : null,
          ),
        ),
    ]);

    final now = DateTime.now();
    final next = items.where((i) => !i.isDone && i.deadline!.isAfter(now) && !sameDay(i.deadline!, selected)).take(6).toList();
    final upcoming = next.isEmpty
        ? const SizedBox.shrink()
        : Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
            const SectionHeader('接下来的截止'),
            for (final i in next)
              ListTile(
                contentPadding: const EdgeInsets.symmetric(horizontal: 4),
                onTap: () => setState(() {
                  selected = i.deadline!;
                  focused = i.deadline!;
                }),
                leading: CircleAvatar(radius: 6, backgroundColor: Brand.course(i.course)),
                title: Text(i.title, maxLines: 1, overflow: TextOverflow.ellipsis),
                subtitle: Text(dayLabel(i.deadline!)),
                trailing: DeadlineBadge(i.deadline!),
              ),
          ]);

    return Scaffold(
      appBar: AppBar(title: const Text('日历'), actions: [
        TextButton(
          onPressed: () => setState(() {
            focused = DateTime.now();
            selected = DateTime.now();
          }),
          child: const Text('今天'),
        ),
        const SizedBox(width: 8),
      ]),
      body: wide
          ? Padding(
              padding: const EdgeInsets.all(16),
              child: Row(crossAxisAlignment: CrossAxisAlignment.start, children: [
                Expanded(flex: 3, child: SingleChildScrollView(child: calendar)),
                const SizedBox(width: 16),
                Expanded(flex: 2, child: SingleChildScrollView(child: Column(children: [dayList, upcoming]))),
              ]),
            )
          : ListView(padding: const EdgeInsets.fromLTRB(16, 8, 16, 96), children: [calendar, dayList, upcoming]),
    );
  }
}
