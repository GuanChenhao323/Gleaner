import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:gleaner/features/sources/reading_source.dart';
import 'package:gleaner/features/sources/reading_source_card.dart';

ReadingSource fixture({
  String result = 'not_executed',
  bool online = true,
  bool verified = false,
  bool paused = false,
}) => ReadingSource.fromJson({
  'id': 1,
  'revision': 1,
  'interval_s': 1800,
  'match_count': 2,
  'mode': 'periodic',
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
      expect(find.text('设置检查'), findsOneWidget);
      expect(find.text('立即检查'), findsNothing);
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
