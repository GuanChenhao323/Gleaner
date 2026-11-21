import 'package:flutter/material.dart';
import 'package:dio/dio.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:gleaner/core/api.dart';
import 'package:gleaner/features/sources/source_purge.dart';

SourcePurgePlan plan() => SourcePurgePlan.fromJson({
  'token': 'a' * 64,
  'plan': {
    'source_id': 12,
    'revision': 2,
    'generation': 0,
    'version_count': 3,
    'check_count': 2,
    'expires_at': 9999999999,
    'items': [
      {'id': 57, 'version': 3},
    ],
    'affected': [
      {'id': 13, 'revision': 1, 'remaining': 1},
    ],
  },
});
void main() {
  testWidgets(
    'permanent delete shows actual impact and requires separate irreversible confirmation',
    (tester) async {
      await tester.binding.setSurfaceSize(const Size(400, 900));
      addTearDown(() => tester.binding.setSurfaceSize(null));
      await tester.pumpWidget(
        MaterialApp(
          home: Scaffold(
            body: SourcePurgeDialog(plan: plan(), title: 'Timeline'),
          ),
        ),
      );
      expect(find.textContaining('1 份关联资料'), findsOneWidget);
      expect(find.textContaining('不可恢复'), findsOneWidget);
      final before = tester.widget<FilledButton>(
        find.widgetWithText(FilledButton, '确认彻底删除'),
      );
      expect(before.onPressed, isNull);
      await tester.tap(find.byType(CheckboxListTile));
      await tester.pump();
      expect(
        tester
            .widget<FilledButton>(find.widgetWithText(FilledButton, '确认彻底删除'))
            .onPressed,
        isNotNull,
      );
      expect(tester.takeException(), isNull);
    },
  );
  test('empty or unsigned deletion plan cannot be presented as a valid confirmation', () {
    expect(
      () => SourcePurgePlan.fromJson({'plan': {}, 'token': 'bad'}),
      throwsA(isA<FormatException>()),
    );
  });
  test(
    'HTTP200 is insufficient to confirm deletion or authorize cache erasure',
    () async {
      final api = Api('http://localhost');
      Map<String, dynamic> response = {};
      api.dio.interceptors.add(
        InterceptorsWrapper(
          onRequest: (request, handler) {
            handler.resolve(
              Response(
                requestOptions: request,
                statusCode: 200,
                data: response,
              ),
            );
          },
        ),
      );
      for (final bad in [
        <String, dynamic>{},
        {'schema_version': 1, 'ok': true},
        {
          'schema_version': 1,
          'ok': true,
          'source_id': 99,
          'purged': true,
          'generation': 1,
          'item_ids': [57],
        },
      ]) {
        response = bad;
        await expectLater(
          api.purgeReading(12, plan().body),
          throwsA(isA<ApiException>()),
        );
      }
      response = {
        'schema_version': 1,
        'ok': true,
        'generation': 1,
        'item_ids': ['bad'],
      };
      await expectLater(api.captureContext(), throwsA(isA<ApiException>()));
      response = {
        'schema_version': 1,
        'ok': true,
        'generation': 1,
        'item_ids': [],
      };
      expect((await api.captureContext())['item_ids'], isEmpty);
    },
  );
}
