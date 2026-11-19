import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:shared_preferences/shared_preferences.dart';

import '../lib/core/session.dart';
import '../lib/main.dart';
import '../lib/router.dart';

void main() {
  for (final width in [390.0, 1100.0]) {
    testWidgets('Guest can browse, open registration and return at width $width', (tester) async {
      tester.view.physicalSize = Size(width, 850);
      tester.view.devicePixelRatio = 1;
      addTearDown(tester.view.resetPhysicalSize);
      addTearDown(tester.view.resetDevicePixelRatio);
      SharedPreferences.setMockInitialValues({});
      final prefs = await SharedPreferences.getInstance();
      await tester.pumpWidget(ProviderScope(
        overrides: [prefsProvider.overrideWithValue(prefs)],
        child: const GleanerApp(),
      ));
      await tester.pumpAndSettle();
      expect(find.text('登录后，在这里查看今日待办和本周截止事项。'), findsOneWidget);
      final router = ProviderScope.containerOf(tester.element(find.byType(GleanerApp))).read(routerProvider);
      for (final entry in ['/login', '/item/42']) {
        router.go(entry);
        await tester.pumpAndSettle();
        expect(router.routeInformationProvider.value.uri.path, '/');
        expect(find.byType(Dialog), findsNothing);
      }
      await tester.tap(find.widgetWithText(ListTile, '课程'));
      await tester.pumpAndSettle();
      expect(find.text('登录后，在这里按课程查看作业和截止日期。'), findsOneWidget);
      await tester.tap(find.byTooltip('登录或注册'));
      await tester.pumpAndSettle();
      await tester.tap(find.text('还没有账号？注册'));
      await tester.pumpAndSettle();
      expect(find.text('邮箱验证码'), findsOneWidget);
      await tester.tap(find.byTooltip('关闭'));
      await tester.pumpAndSettle();
      expect(find.text('登录后，在这里按课程查看作业和截止日期。'), findsOneWidget);
    });
  }
}
