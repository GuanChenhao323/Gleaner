import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:gleaner/features/inbox/web_capture_details.dart';

void main() {
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
