import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:shared_preferences/shared_preferences.dart';

import 'package:gleaner/core/session.dart';
import 'package:gleaner/main.dart';
import 'package:gleaner/router.dart';

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
      expect(find.text('Sign in to see today’s tasks and deadlines this week.'), findsOneWidget);
      final router = ProviderScope.containerOf(tester.element(find.byType(GleanerApp))).read(routerProvider);
      for (final entry in ['/login', '/item/42']) {
        router.go(entry);
        await tester.pumpAndSettle();
        expect(router.routeInformationProvider.value.uri.path, '/');
        expect(find.byType(Dialog), findsNothing);
      }
      await tester.tap(find.widgetWithText(ListTile, 'Courses'));
      await tester.pumpAndSettle();
      expect(find.text('Sign in to browse assignments and deadlines by course.'), findsOneWidget);
      await tester.tap(find.byTooltip('Sign in or register'));
      await tester.pumpAndSettle();
      await tester.tap(find.text('No account yet? Register'));
      await tester.pumpAndSettle();
      expect(find.text('Email code'), findsOneWidget);
      await tester.tap(find.byTooltip('Close'));
      await tester.pumpAndSettle();
      expect(find.text('Sign in to browse assignments and deadlines by course.'), findsOneWidget);
    });
  }
}
