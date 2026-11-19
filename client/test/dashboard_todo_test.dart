import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:shared_preferences/shared_preferences.dart';

import '../lib/core/models.dart';
import '../lib/core/providers.dart';
import '../lib/core/session.dart';
import '../lib/core/store.dart';
import '../lib/features/dashboard/dashboard_page.dart';

class _Feed extends FeedStore {
  @override
  FeedState build() {
    final items = [
      for (var id = 1; id <= 8; id++)
        Item.fromJson({'id': id, 'title': '紧急通知 $id', 'priority': 'urgent'}),
      Item.fromJson({'id': 9, 'kind': 'mail', 'type': 'notice', 'title': '提交材料', 'state': {'read': true}}),
      Item.fromJson({'id': 10, 'type': 'todo', 'title': '已办事项', 'state': {'todo': 'done'}}),
    ];
    return FeedState(items: {for (final item in items) item.id: item});
  }

  void applySavedItem(Map<String, dynamic> fields) {
    final item = state.items[9]!.merge(fields);
    state = state.copyWith(items: {...state.items, item.id: item});
  }
}

void main() {
  testWidgets('A read notice without a deadline enters the dashboard when converted to a todo', (tester) async {
    SharedPreferences.setMockInitialValues({});
    final prefs = await SharedPreferences.getInstance();
    final feed = _Feed();
    await tester.pumpWidget(ProviderScope(
      overrides: [
        prefsProvider.overrideWithValue(prefs),
        feedProvider.overrideWith(() => feed),
        sourcesProvider.overrideWith((_) async => []),
      ],
      child: const MaterialApp(home: DashboardPage()),
    ));
    await tester.pumpAndSettle();
    await tester.tap(find.widgetWithText(FilterChip, '待办任务'));
    await tester.pumpAndSettle();
    expect(find.text('提交材料'), findsNothing);
    feed.applySavedItem({'type': 'todo'});
    await tester.pumpAndSettle();
    expect(find.text('提交材料'), findsOneWidget);
    expect(find.text('已办事项'), findsNothing);
    feed.applySavedItem({'type': 'event'});
    await tester.pumpAndSettle();
    expect(find.text('提交材料'), findsNothing);
    await tester.tap(find.widgetWithText(FilterChip, '日程活动'));
    await tester.pumpAndSettle();
    expect(find.text('提交材料'), findsOneWidget);
    feed.applySavedItem({'type': 'notice'});
    await tester.pumpAndSettle();
    await tester.tap(find.widgetWithText(FilterChip, '通知'));
    await tester.pumpAndSettle();
    final more = find.widgetWithText(TextButton, '显示更多');
    await tester.drag(find.byType(CustomScrollView), const Offset(0, -500));
    await tester.pumpAndSettle();
    await tester.tap(more);
    await tester.pumpAndSettle();
    expect(find.text('提交材料'), findsOneWidget);
  });
}
