import 'dart:async';

import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';

import '../lib/core/api.dart';
import '../lib/core/models.dart';
import '../lib/core/session.dart';
import '../lib/core/store.dart';
import '../lib/features/inbox/label_editor.dart';

class _LabelApi extends Fake implements Api {
  final firstLoad = Completer<List<UserLabel>>();
  final created = <UserLabel>[];
  int reads = 0;
  @override
  Future<List<UserLabel>> labels() async => ++reads == 1 ? firstLoad.future : created;
  @override
  Future<UserLabel> createLabel(String name, {String color = ''}) async {
    final label = UserLabel(id: 7, name: name, color: color);
    created.add(label);
    return label;
  }
}

class _Feed extends FeedStore {
  List<int>? saved;
  @override
  FeedState build() => const FeedState();
  @override
  Future<void> setItemLabels(Item item, List<int> labelIds) async => saved = labelIds;
}

void main() {
  testWidgets('Label picker opens while loading and recovers from an error through first-label save', (tester) async {
    final api = _LabelApi();
    final feed = _Feed();
    await tester.pumpWidget(ProviderScope(
      retry: (_, _) => null,
      overrides: [apiProvider.overrideWithValue(api), feedProvider.overrideWith(() => feed)],
      child: MaterialApp(home: Scaffold(body: Builder(builder: (context) => TextButton(
        onPressed: () => showModalBottomSheet<void>(
          context: context,
          builder: (_) => ItemLabelEditor(item: Item.fromJson({'id': 42})),
        ),
        child: const Text('标签'),
      )))),
    ));
    await tester.tap(find.text('标签'));
    await tester.pump();
    expect(find.byType(LinearProgressIndicator), findsOneWidget);
    api.firstLoad.completeError(ApiException(404, 'missing', 'no route'));
    await tester.pumpAndSettle();
    await tester.tap(find.text('重试'));
    await tester.pumpAndSettle();
    expect(find.text('还没有标签，可以先创建一个。'), findsOneWidget);
    await tester.tap(find.text('新建标签'));
    await tester.pumpAndSettle();
    await tester.enterText(find.byType(TextField), '作业');
    await tester.tap(find.text('创建'));
    await tester.pumpAndSettle();
    expect(tester.widget<CheckboxListTile>(find.byType(CheckboxListTile)).value, isTrue);
    await tester.tap(find.text('保存'));
    await tester.pumpAndSettle();
    expect(feed.saved, [7]);
    expect(find.byType(ItemLabelEditor), findsNothing);
  });
}
