import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:uuid/uuid.dart';

import 'api.dart';
import 'session.dart';

/// A personal trash state, independent of source content and source deletion.
abstract interface class DocumentLifecycleRepository {
  Future<Map<String, dynamic>> setTrashed(int id, bool trashed);
}

class ApiDocumentLifecycleRepository implements DocumentLifecycleRepository {
  final Api api;
  ApiDocumentLifecycleRepository(this.api);
  @override
  Future<Map<String, dynamic>> setTrashed(int id, bool trashed) async {
    final result = await api.putState(id, {
      'hidden': trashed,
    }, const Uuid().v4());
    final state = result['state'];
    if (result['ok'] != true ||
        result['item_id'] != id ||
        result['stale'] == true ||
        state is! Map ||
        state['hidden'] != trashed) {
      throw ApiException(502, 'invalid_response', '资料操作未获确认，请刷新核对后重试。');
    }
    return Map<String, dynamic>.from(state);
  }
}

final documentLifecycleRepositoryProvider =
    Provider<DocumentLifecycleRepository>(
      (ref) => ApiDocumentLifecycleRepository(ref.watch(apiProvider)),
    );
