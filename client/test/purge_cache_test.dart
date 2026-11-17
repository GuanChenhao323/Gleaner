import 'package:drift/native.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:gleaner/core/db.dart';

void main() {
  test('permanent erasure removes cached body and pending notes while retaining unrelated edits', () async {
    final db = LocalDb(NativeDatabase.memory());
    addTearDown(db.close);
    await db.saveItems([
      {'id': 1, 'body': 'deleted private body'},
      {'id': 2, 'body': 'retained body'},
    ]);
    await db.enqueue('old-note', 1, {'note': 'deleted private note'});
    await db.enqueue('keep-note', 2, {'note': 'retained edit'});
    await db.retainItems({2});
    expect((await db.loadItems()).map((v) => v['id']), [2]);
    expect((await db.pending()).map((v) => v.opId), ['keep-note']);
    await db.forgetItems([2]);
    expect(await db.loadItems(), isEmpty);
    expect(await db.pending(), isEmpty);
  });
}
