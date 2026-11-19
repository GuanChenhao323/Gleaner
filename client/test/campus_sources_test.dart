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
      expect(find.text('College notices / student system'), findsOneWidget);
      expect(find.text('Faculty directory'), findsOneWidget);
      expect(find.text('Moodle courses & assignments'), findsOneWidget);
      expect(find.text('Public page · no student sign-in'), findsOneWidget);
      expect(
        find.text('Requires original-site sign-in · this page does not check school session'),
        findsNWidgets(2),
      );
      expect(find.text('Connected'), findsNothing);
      expect(tester.takeException(), isNull);
    },
  );
}
