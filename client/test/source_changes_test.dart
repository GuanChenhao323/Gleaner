import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:gleaner/features/inbox/source_changes.dart';
import 'package:gleaner/features/sources/browser_monitors.dart';

void main() {
  testWidgets('source changes show both snapshots after expansion', (
    tester,
  ) async {
    await tester.pumpWidget(
      const MaterialApp(
        home: Scaffold(
          body: SourceChanges({
            'body': ['原始要求：一份', '变更要求：两份'],
            'source_fields': [
              null,
              {'week': '2', 'period': '3-4'},
            ],
          }),
        ),
      ),
    );
    await tester.tap(find.text('原文内容'));
    await tester.pumpAndSettle();
    expect(find.text('变更前：\n原始要求：一份'), findsOneWidget);
    expect(find.text('变更后：\n变更要求：两份'), findsOneWidget);
    expect(tester.takeException(), isNull);
  });
  test('not executed, unchanged and failures have different labels', () {
    expect(browserCheckLabel('not_executed'), '待首次检查');
    expect(browserCheckLabel('unchanged'), '检查成功 · 无变化');
    expect(browserCheckLabel('need_login'), '请在学校原站重新登录');
    expect(browserCheckLabel('render_timeout'), '页面加载超时');
  });
}
