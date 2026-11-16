import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:gleaner/features/sources/reading_source.dart';
import 'package:gleaner/features/sources/reading_source_card.dart';
import 'package:gleaner/features/sources/resident_source_group.dart';

ReadingSource fixture({
  String result = 'not_executed',
  bool online = true,
  bool verified = false,
  bool paused = false,
  String mode = 'periodic',
}) => ReadingSource.fromJson({
  'id': 1,
  'revision': 1,
  'interval_s': 1800,
  'match_count': 2,
  'mode': mode,
  'last_result': result,
  'capability': verified ? 'ready' : 'unverified',
  'pending': '',
  'paused': paused,
  'verified': verified,
  'device_online': online,
  'last_success_at': null,
  'last_attempt_at': null,
  'next_at': null,
  'recipe': {
    'source': 'moodle',
    'url': 'https://moodle.example.test/my/',
    'query': '网络编程的作业',
    'match_scope': 'content',
    'binding': {'account_key': 'salted-account'},
  },
  'items': <Map<String, dynamic>>[],
});
void main() {
  test(
    'save, verification, no-match and login have distinct honest states',
    () {
      expect(fixture().status, '待首次检查');
      expect(
        fixture(result: 'verified', verified: true).status,
        contains('待检查'),
      );
      expect(fixture(result: 'no_match').status, contains('保留旧资料'));
      expect(fixture(result: 'need_login').status, contains('重新登录'));
      expect(fixture(verified: true, paused: true).periodic, isFalse);
    },
  );
  testWidgets(
    'unverified card gates background checking and preserves query at narrow width',
    (tester) async {
      await tester.binding.setSurfaceSize(const Size(320, 900));
      addTearDown(() => tester.binding.setSurfaceSize(null));
      await tester.pumpWidget(
        MaterialApp(
          home: Scaffold(
            body: SingleChildScrollView(
              child: ReadingSourceCard(
                source: fixture(),
                onCheck: () {},
                onSettings: () {},
                onDetails: () {},
                onLogs: () {},
                onPause: () {},
                onOpen: () {},
              ),
            ),
          ),
        ),
      );
      expect(find.text('网络编程的作业'), findsOneWidget);
      expect(find.text('启用自动监测'), findsOneWidget);
      expect(find.text('立即检查'), findsNothing);
      expect(tester.takeException(), isNull);
    },
  );
  testWidgets(
    'resident page groups rules, shows real cadence and binds before checking',
    (tester) async {
      await tester.binding.setSurfaceSize(const Size(360, 900));
      addTearDown(() => tester.binding.setSurfaceSize(null));
      final a = fixture(result: 'starting'), b = fixture(result: 'starting');
      for (final s in [a, b]) {
        s.recipe['resident'] = {'page_id': 'same-page'};
      }
      int settings = 0;
      await tester.pumpWidget(
        MaterialApp(
          home: Scaffold(
            body: SingleChildScrollView(
              child: ResidentSourceGroup(
                rules: [a, b],
                ruleCard: (s) => Text(s.query),
                onSettings: () => settings++,
                onCheck: () {},
                onPause: () {},
              ),
            ),
          ),
        ),
      );
      expect(find.textContaining('2 条规则'), findsOneWidget);
      expect(find.text('立即检查全部规则'), findsNothing);
      await tester.tap(find.text('启动／重新绑定'));
      expect(settings, 1);
      expect(tester.takeException(), isNull);
    },
  );
  testWidgets(
    'manual resident page never claims periodic monitoring is running',
    (tester) async {
      final s = fixture(result: 'unchanged', verified: true, mode: 'manual');
      s.recipe['resident'] = {'page_id': 'same-page'};
      await tester.pumpWidget(
        MaterialApp(
          home: Scaffold(
            body: SingleChildScrollView(
              child: ResidentSourceGroup(
                rules: [s],
                ruleCard: (s) => Text(s.query),
                onSettings: () {},
                onCheck: () {},
                onPause: () {},
              ),
            ),
          ),
        ),
      );
      expect(find.text('定期监测中'), findsNothing);
      expect(find.text('仅手动检查'), findsOneWidget);
      expect(find.text('暂停定期'), findsNothing);
      expect(tester.takeException(), isNull);
    },
  );
  testWidgets('paused periodic source keeps manual check and explicit resume', (
    tester,
  ) async {
    await tester.pumpWidget(
      MaterialApp(
        home: Scaffold(
          body: ReadingSourceCard(
            source: fixture(verified: true, paused: true, result: 'unchanged'),
            onCheck: () {},
            onSettings: () {},
            onDetails: () {},
            onLogs: () {},
            onPause: () {},
            onOpen: () {},
          ),
        ),
      ),
    );
    expect(find.text('立即检查'), findsOneWidget);
    expect(find.text('恢复定期'), findsOneWidget);
    expect(tester.takeException(), isNull);
  });
}
