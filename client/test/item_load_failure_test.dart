import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:flutter_localizations/flutter_localizations.dart';
import 'package:gleaner/core/api.dart';
import 'package:gleaner/features/inbox/item_load_failure.dart';
import 'package:gleaner/l10n/app_localizations.dart';

void main() {
  testWidgets(
    'unowned record gives account guidance and actionable recovery instead of a spinner',
    (tester) async {
      var retry = 0;
      var sources = 0;
      await tester.pumpWidget(
        MaterialApp(
          locale: const Locale('en'),
          localizationsDelegates: const [
            AppLocalizations.delegate,
            GlobalMaterialLocalizations.delegate,
            GlobalWidgetsLocalizations.delegate,
          ],
          supportedLocales: AppLocalizations.supportedLocales,
          home: Scaffold(
            body: ItemLoadFailure(
              error: ApiException(404, 'not_found', 'not_found'),
              email: 'sample@example.test',
              onRetry: () => retry++,
              onSources: () => sources++,
            ),
          ),
        ),
      );
      expect(find.textContaining('same Gleaner account'), findsOneWidget);
      expect(find.textContaining('sample@example.test'), findsOneWidget);
      expect(find.byType(CircularProgressIndicator), findsNothing);
      await tester.tap(find.text('Retry'));
      await tester.tap(find.text('Back to sources'));
      expect(retry, 1);
      expect(sources, 1);
    },
  );
}
