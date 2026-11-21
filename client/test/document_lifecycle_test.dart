import 'package:dio/dio.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:gleaner/core/api.dart';
import 'package:gleaner/core/document_lifecycle.dart';
import 'package:gleaner/core/models.dart';
import 'package:gleaner/core/store.dart';

class StateApi extends Api {
  Map<String, dynamic> response = {};
  StateApi() : super('http://localhost');
  @override
  Future<Map<String, dynamic>> putState(
    int id,
    Map<String, dynamic> body,
    String opId,
  ) async => response;
}

void main() {
  test(
    'trash confirmation rejects HTTP200 empty, wrong item and stale state',
    () async {
      final api = StateApi(), repo = ApiDocumentLifecycleRepository(StateApi());
      await expectLater(repo.setTrashed(1, true), throwsA(isA<ApiException>()));
      final realRepo = ApiDocumentLifecycleRepository(api);
      for (final response in [
        {
          'ok': true,
          'item_id': 2,
          'state': {'hidden': true},
        },
        {
          'ok': true,
          'item_id': 1,
          'state': {'hidden': false},
        },
        {
          'ok': true,
          'item_id': 1,
          'stale': true,
          'state': {'hidden': true},
        },
      ]) {
        api.response = response;
        await expectLater(
          realRepo.setTrashed(1, true),
          throwsA(isA<ApiException>()),
        );
      }
      api.response = {
        'ok': true,
        'item_id': 1,
        'state': {'hidden': true, 'note': '保留备注', 'starred': true},
      };
      final result = await realRepo.setTrashed(1, true);
      expect(result['note'], '保留备注');
      expect(result['hidden'], isTrue);
    },
  );
  test('inbox and trash are disjoint, unread ignores trashed documents', () {
    Item item(int id, bool hidden) => Item.fromJson({
      'id': id,
      'title': '资料$id',
      'kind': 'clip',
      'state': {'hidden': hidden, 'starred': true, 'note': '备注'},
    });
    final st = FeedState(items: {1: item(1, false), 2: item(2, true)});
    expect(st.visible.map((i) => i.id), [1]);
    expect(st.trashed.map((i) => i.id), [2]);
    expect(st.unread, 1);
    expect(st.trashed.single.state.note, '备注');
  });
  test('source deletion validates acknowledgement and sends explicit retained-documents choice', () async {
    final api = Api('http://localhost');
    Map<String, dynamic> response = {};
    RequestOptions? sent;
    api.dio.interceptors.add(
      InterceptorsWrapper(
        onRequest: (o, h) {
          sent = o;
          h.resolve(
            Response(requestOptions: o, statusCode: 200, data: response),
          );
        },
      ),
    );
    await expectLater(
      api.removeReading(4, 3, false),
      throwsA(isA<ApiException>()),
    );
    response = {
      'schema_version': 1,
      'ok': true,
      'source_id': 4,
      'deleted': true,
      'trash_items': false,
      'trashed_item_ids': [],
    };
    await api.removeReading(4, 3, false);
    expect(sent!.method, 'DELETE');
    expect(sent!.data, {'revision': 3, 'trash_items': false});
  });
}
