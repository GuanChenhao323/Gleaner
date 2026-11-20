import 'package:flutter/gestures.dart';
import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:shared_preferences/shared_preferences.dart';

import 'package:gleaner/core/session.dart';
import 'package:gleaner/main.dart';
import 'package:gleaner/router.dart';
import 'package:gleaner/widgets/common.dart';

void main() {
  testWidgets('Sidebar keeps its logo in place and reveals leaner on expansion', (tester) async {
    tester.view.physicalSize = const Size(1100, 850);
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
    final logo = find.byType(GleanerLogo);
    final suffix = find.text('leaner');
    final position = tester.getCenter(logo);
    expect(suffix, findsNothing);

    final mouse = await tester.createGesture(kind: PointerDeviceKind.mouse);
    await mouse.addPointer(location: const Offset(500, 50));
    addTearDown(mouse.removePointer);
    await mouse.moveTo(position);
    await tester.pumpAndSettle();
    expect(tester.getCenter(logo), position);
    expect(suffix, findsOneWidget);
    await tester.tap(logo);
    await mouse.moveTo(const Offset(500, 50));
    await tester.pumpAndSettle();
    expect(suffix, findsOneWidget);
    await tester.tap(logo);
    await tester.pumpAndSettle();
    expect(suffix, findsNothing);
    expect(tester.getCenter(logo), position);
  });

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
