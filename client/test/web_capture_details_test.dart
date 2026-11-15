import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:gleaner/features/inbox/web_capture_details.dart';

void main() {
  testWidgets(
    'Timeline reference retains summary label, original time and detail link',
    (tester) async {
      await tester.pumpWidget(
        const MaterialApp(
          home: Scaffold(
            body: SingleChildScrollView(
              child: WebCaptureDetails({
                'collection_type': 'timeline_summary',
                'query': 'Timeline',
                'source_binding': {'adapter': 'moodle', 'account_key': 'hash'},
                'fragments': [
                  {
                    'title': '合成活动',
                    'text': '当前提醒摘要',
                    'url': 'https://example.test/activity',
                    'fields': {
                      'course': '合成课程',
                      'date_text': 'November 16',
                      'datetime_text': '00:00',
                    },
                    'evidence': {'locator': 'div'},
                  },
                ],
              }, hasReadingSource: true),
            ),
          ),
        ),
      );
      expect(find.text('活动摘要资料 · 1 条活动'), findsOneWidget);
      expect(find.textContaining('不代表完整作业'), findsOneWidget);
      expect(find.textContaining('网站账号未经自动确认'), findsNothing);
      await tester.tap(find.text('活动 1：合成活动'));
      await tester.pumpAndSettle();
      expect(find.textContaining('时间原文：00:00'), findsOneWidget);
      expect(find.text('打开活动详情'), findsOneWidget);
      expect(tester.takeException(), isNull);
    },
  );
  testWidgets(
    'generic reference shows fragment boundaries and unverified source label',
    (tester) async {
      await tester.pumpWidget(
        const MaterialApp(
          home: Scaffold(
            body: WebCaptureDetails({
              'query': '会议',
              'match_scope': 'content',
              'source_binding': {'kind': 'labeled', 'label': '学校邮箱'},
              'fragments': [
                {
                  'title': '会议安排',
                  'text': '合成列表摘要。',
                  'evidence': {'locator': 'div:nth-child(1)'},
                },
              ],
            }),
          ),
        ),
      );
      expect(find.text('网页资料快照 · 1 个片段'), findsOneWidget);
      expect(find.textContaining('来源标签：学校邮箱'), findsOneWidget);
      expect(find.textContaining('网站账号未经自动确认'), findsOneWidget);
      await tester.tap(find.text('片段 1：会议安排'));
      await tester.pumpAndSettle();
      expect(find.textContaining('合成列表摘要。'), findsOneWidget);
      expect(tester.takeException(), isNull);
    },
  );
}
