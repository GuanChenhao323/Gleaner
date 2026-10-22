import 'dart:convert';

import 'package:drift/drift.dart';
import 'package:drift_flutter/drift_flutter.dart';

part 'db.g.dart';

/// 离线缓存的事项（整条 JSON），按 id 覆盖写入。
class CachedItems extends Table {
  IntColumn get id => integer()();
  TextColumn get json => text()();
  RealColumn get updatedAt => real().withDefault(const Constant(0))();

  @override
  Set<Column> get primaryKey => {id};
}

/// 键值：同步游标、用户资料等。
class KvEntries extends Table {
  TextColumn get key => text()();
  TextColumn get value => text()();

  @override
  Set<Column> get primaryKey => {key};
}

/// 离线操作队列：每个操作带唯一幂等键，联网后按顺序回放。
class PendingOps extends Table {
  TextColumn get opId => text()();
  IntColumn get itemId => integer()();
  TextColumn get json => text()();
  IntColumn get createdAt => integer()();

  @override
  Set<Column> get primaryKey => {opId};
}

@DriftDatabase(tables: [CachedItems, KvEntries, PendingOps])
class LocalDb extends _$LocalDb {
  LocalDb(super.e);

  LocalDb.open()
      : super(driftDatabase(
          name: 'gleaner',
          web: DriftWebOptions(sqlite3Wasm: Uri.parse('sqlite3.wasm'), driftWorker: Uri.parse('drift_worker.js')),
        ));

  @override
  int get schemaVersion => 1;

  Future<List<Map<String, dynamic>>> loadItems() async {
    final rows = await select(cachedItems).get();
    return rows.map((r) => Map<String, dynamic>.from(jsonDecode(r.json) as Map)).toList();
  }

  Future<void> saveItems(Iterable<Map<String, dynamic>> items) async {
    await batch((b) {
      b.insertAllOnConflictUpdate(
        cachedItems,
        items.map((j) => CachedItemsCompanion.insert(
              id: Value(j['id'] as int),
              json: jsonEncode(j),
              updatedAt: Value(((j['updated_at'] ?? 0) as num).toDouble()),
            )),
      );
    });
  }

  Future<String?> getKv(String key) async {
    final r = await (select(kvEntries)..where((t) => t.key.equals(key))).getSingleOrNull();
    return r?.value;
  }

  Future<void> setKv(String key, String value) => into(kvEntries).insertOnConflictUpdate(KvEntriesCompanion.insert(key: key, value: value));

  Future<List<PendingOp>> pending() => (select(pendingOps)..orderBy([(t) => OrderingTerm.asc(t.createdAt)])).get();

  Future<void> enqueue(String opId, int itemId, Map<String, dynamic> op) => into(pendingOps).insertOnConflictUpdate(
        PendingOpsCompanion.insert(opId: opId, itemId: itemId, json: jsonEncode(op), createdAt: DateTime.now().millisecondsSinceEpoch),
      );

  Future<void> dequeue(Iterable<String> opIds) => (delete(pendingOps)..where((t) => t.opId.isIn(opIds))).go();

  Future<void> wipe() async {
    await delete(cachedItems).go();
    await delete(kvEntries).go();
    await delete(pendingOps).go();
  }
}
