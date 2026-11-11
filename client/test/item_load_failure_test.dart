import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:gleaner/core/api.dart';
import 'package:gleaner/features/inbox/item_load_failure.dart';

void main() {
  testWidgets(
    'unowned record gives account guidance and actionable recovery instead of a spinner',
    (tester) async {
      var retry = 0;
      var sources = 0;
      await tester.pumpWidget(
        MaterialApp(
          home: Scaffold(
            body: ItemLoadFailure(
              error: ApiException(404, 'not_found', '事项不存在'),
              email: 'sample@example.test',
              onRetry: () => retry++,
              onSources: () => sources++,
            ),
          ),
        ),
      );
      expect(find.textContaining('工作台与插件使用同一 Campus Radar 邮箱'), findsOneWidget);
      expect(find.textContaining('sample@example.test'), findsOneWidget);
      expect(find.byType(CircularProgressIndicator), findsNothing);
      await tester.tap(find.text('重试'));
      await tester.tap(find.text('返回信息源'));
      expect(retry, 1);
      expect(sources, 1);
    },
  );
}
