import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:go_router/go_router.dart';
import 'package:table_calendar/table_calendar.dart';

import '../../core/format.dart';
import '../../core/models.dart';
import '../../core/providers.dart';
import '../../l10n/app_localizations.dart';
import '../../theme.dart';
import '../../widgets/common.dart';
import '../courses/assignment_list.dart';

class DeadlineCalendarCard extends ConsumerStatefulWidget {
  const DeadlineCalendarCard({super.key});

  @override
  ConsumerState<DeadlineCalendarCard> createState() => _DeadlineCalendarCardState();
}

class _DeadlineCalendarCardState extends ConsumerState<DeadlineCalendarCard> {
  DateTime focused = DateTime.now();
  DateTime selected = DateTime.now();
  CalendarFormat format = CalendarFormat.week;

  @override
  Widget build(BuildContext context) {
    final cs = Theme.of(context).colorScheme;
    final items = ref.watch(deadlinesProvider).where((i) => !i.isDone && i.deadline != null).toList();
    List<Item> on(DateTime d) => items.where((i) => sameDay(i.deadline!, d)).toList();
    final day = on(selected);
    final wide = MediaQuery.sizeOf(context).width >= 1000;

    final calendar = TableCalendar<Item>(
      locale: Localizations.localeOf(context).toString(),
      firstDay: DateTime.now().subtract(const Duration(days: 365)),
      lastDay: DateTime.now().add(const Duration(days: 365)),
      focusedDay: focused,
      calendarFormat: format,
      startingDayOfWeek: StartingDayOfWeek.monday,
      availableCalendarFormats: {
        CalendarFormat.month: AppLocalizations.of(context).calMonth,
        CalendarFormat.twoWeeks: AppLocalizations.of(context).calTwoWeeks,
        CalendarFormat.week: AppLocalizations.of(context).calWeek,
      },
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
    );

    final dayList = Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
      SectionHeader(dayLabel(selected, context), trailing: day.isEmpty ? null : '${day.length}'),
      if (day.isEmpty)
        Padding(
          padding: const EdgeInsets.fromLTRB(0, 8, 0, 8),
          child: Text(AppLocalizations.of(context).noDeadlines, style: TextStyle(color: cs.onSurfaceVariant)),
        )
      else
        for (final i in day) AssignmentTile(i),
    ]);

    return Card(
      child: Padding(
        padding: const EdgeInsets.fromLTRB(12, 12, 12, 12),
        child: Column(crossAxisAlignment: CrossAxisAlignment.stretch, children: [
          Row(children: [
            Text(AppLocalizations.of(context).deadlineCalendar, style: Theme.of(context).textTheme.titleSmall?.copyWith(fontWeight: FontWeight.w800)),
            const Spacer(),
            TextButton(
              onPressed: () => setState(() {
                focused = DateTime.now();
                selected = DateTime.now();
              }),
              child: Text(AppLocalizations.of(context).today),
            ),
            TextButton(onPressed: () => context.go('/courses'), child: Text(AppLocalizations.of(context).navCourses)),
          ]),
          if (wide)
            Row(crossAxisAlignment: CrossAxisAlignment.start, children: [
              Expanded(flex: 3, child: calendar),
              const SizedBox(width: 16),
              Expanded(flex: 2, child: dayList),
            ])
          else ...[
            calendar,
            const SizedBox(height: 8),
            dayList,
          ],
        ]),
      ),
    );
  }
}
