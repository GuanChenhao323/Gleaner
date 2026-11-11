import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:gleaner/features/sources/campus_source_entries.dart';

void main() {
  testWidgets(
    'three real entries exist without items; public teacher page and original-site login stay distinct',
    (tester) async {
      await tester.pumpWidget(
        const MaterialApp(
          home: Scaffold(
            body: SingleChildScrollView(child: CampusSourceEntries()),
          ),
        ),
      );
      expect(find.text('学院公告／学生系统'), findsOneWidget);
      expect(find.text('教师信息'), findsOneWidget);
      expect(find.text('Moodle 课程与作业'), findsOneWidget);
      expect(find.text('公开网页 · 无需学生登录'), findsOneWidget);
      expect(find.text('需在原站登录 · 本页不判断学校会话是否有效'), findsNWidgets(2));
      expect(find.text('已连接'), findsNothing);
      expect(tester.takeException(), isNull);
    },
  );
}
