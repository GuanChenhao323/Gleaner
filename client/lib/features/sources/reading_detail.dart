import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:go_router/go_router.dart';
import 'package:url_launcher/url_launcher.dart';

import '../../core/models.dart';
import '../../core/session.dart';
import '../../widgets/common.dart';
import '../inbox/source_changes.dart';
import '../inbox/web_capture_details.dart';
import 'reading_source.dart';
import 'reading_settings.dart';

final _versionProvider = Provider.family<int?, int>(
  (ref, id) => ref
      .watch(readingSourcesProvider)
      .value
      ?.expand((s) => s.items)
      .where((i) => i['id'] == id)
      .map((i) => i['version'] as int)
      .firstOrNull,
);
final _itemProvider = FutureProvider.autoDispose.family<Item, int>((ref, id) {
  ref.watch(_versionProvider(id));
  return ref.watch(apiProvider).item(id);
});
final _versionsProvider = FutureProvider.autoDispose
    .family<List<ItemVersion>, int>((ref, id) {
      ref.watch(_versionProvider(id));
      return ref.watch(apiProvider).versions(id);
    });

/// Reading context and source versions; personal management stays in ItemDetail.
class ReadingDetailPage extends ConsumerWidget {
  final int id;
  final bool showChanges;
  const ReadingDetailPage({
    super.key,
    required this.id,
    this.showChanges = false,
  });
  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final data = ref.watch(readingSourcesProvider);
    return data.when(
      loading: () =>
          const Scaffold(body: Center(child: CircularProgressIndicator())),
      error: (e, _) => Scaffold(
        appBar: AppBar(title: const Text('来源与资料')),
        body: Center(child: Text('$e')),
      ),
      data: (rows) {
        final source = rows.where((s) => s.id == id).firstOrNull;
        if (source == null) {
          return const Scaffold(body: Center(child: Text('来源不存在，或不属于当前账号。')));
        }
        return DefaultTabController(
          length: 3,
          initialIndex: showChanges ? 1 : 0,
          child: Scaffold(
            appBar: AppBar(
              title: const Text('来源与资料'),
              leading: IconButton(
                tooltip: '返回信息源',
                icon: const Icon(Icons.arrow_back),
                onPressed: () => context.go('/sources'),
              ),
            ),
            body: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Padding(
                  padding: const EdgeInsets.fromLTRB(24, 12, 24, 15),
                  child: Column(
                    crossAxisAlignment: CrossAxisAlignment.start,
                    children: [
                      Text(
                        source.title,
                        style: Theme.of(context).textTheme.titleLarge,
                      ),
                      const SizedBox(height: 5),
                      Text('${source.identity} · ${source.status}'),
                      const SizedBox(height: 7),
                      Text(source.scope),
                      const SizedBox(height: 12),
                      Wrap(
                        spacing: 9,
                        runSpacing: 7,
                        children: [
                          OutlinedButton.icon(
                            onPressed: () => launchUrl(Uri.parse(source.url)),
                            icon: const Icon(Icons.open_in_new, size: 16),
                            label: const Text('打开原网页'),
                          ),
                          OutlinedButton(
                            onPressed: () =>
                                context.push('/sources/$id/settings'),
                            child: const Text('检查设置'),
                          ),
                          if (source.verified)
                            FilledButton(
                              onPressed: source.active
                                  ? null
                                  : () async {
                                      try {
                                        await ref
                                            .read(
                                              readingSourcesProvider.notifier,
                                            )
                                            .check(source, 'check');
                                        if (context.mounted) {
                                          toast(context, '检查已排队，等待浏览器执行。');
                                        }
                                      } catch (e) {
                                        if (context.mounted) {
                                          toast(context, '$e', error: true);
                                        }
                                      }
                                    },
                              child: const Text('立即检查'),
                            ),
                        ],
                      ),
                    ],
                  ),
                ),
                const TabBar(
                  tabs: [
                    Tab(text: '已保存内容'),
                    Tab(text: '变化记录'),
                    Tab(text: '检查日志'),
                  ],
                ),
                Expanded(
                  child: TabBarView(
                    children: [
                      ListView(
                        padding: const EdgeInsets.all(24),
                        children: [
                          Text('原关键词：${source.query}'),
                          const SizedBox(height: 6),
                          Text('原始网页：${source.url}'),
                          const SizedBox(height: 16),
                          for (final item in source.items)
                            _SavedItem(id: item['id'] as int),
                        ],
                      ),
                      ListView(
                        padding: const EdgeInsets.all(24),
                        children: [
                          const Text('来源版本与个人修改分开保留。检查无变化或失败不会新增内容版本。'),
                          const SizedBox(height: 15),
                          for (final item in source.items)
                            _ItemVersions(
                              id: item['id'] as int,
                              title: '${item['title']}',
                            ),
                        ],
                      ),
                      ReadingChecksBody(id: id),
                    ],
                  ),
                ),
              ],
            ),
          ),
        );
      },
    );
  }
}

class _SavedItem extends ConsumerWidget {
  final int id;
  const _SavedItem({required this.id});
  @override
  Widget build(BuildContext context, WidgetRef ref) => ref
      .watch(_itemProvider(id))
      .when(
        loading: () => const LinearProgressIndicator(),
        error: (e, _) => Text('资料读取失败：$e'),
        data: (item) => Card(
          child: ExpansionTile(
            initiallyExpanded: true,
            title: Text(item.title),
            subtitle: Text('来源版本 v${item.version}'),
            children: [
              Padding(
                padding: const EdgeInsets.all(16),
                child: Column(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    SelectableText(item.body),
                    if ((item.raw['web_capture'] as Map?)?['collection_type'] ==
                        'timeline_summary')
                      WebCaptureDetails(
                        Map<String, dynamic>.from(
                          item.raw['web_capture'] as Map,
                        ),
                        hasReadingSource: true,
                      ),
                    if (item.state.note.isNotEmpty)
                      Padding(
                        padding: const EdgeInsets.only(top: 15),
                        child: Text('我的备注（已保留）：${item.state.note}'),
                      ),
                    TextButton(
                      onPressed: () => context.push('/item/$id'),
                      child: const Text('打开事项管理'),
                    ),
                  ],
                ),
              ),
            ],
          ),
        ),
      );
}

class _ItemVersions extends ConsumerWidget {
  final int id;
  final String title;
  const _ItemVersions({required this.id, required this.title});
  @override
  Widget build(BuildContext context, WidgetRef ref) => ref
      .watch(_versionsProvider(id))
      .when(
        loading: () => const LinearProgressIndicator(),
        error: (e, _) => Text('版本读取失败：$e'),
        data: (versions) => Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Text(title, style: Theme.of(context).textTheme.titleMedium),
            for (final version in versions)
              Card(
                child: ExpansionTile(
                  title: Text(
                    'v${version.version} · ${version.version == 1
                        ? '首次保存'
                        : version.note.isEmpty
                        ? '来源内容更新'
                        : version.note}',
                  ),
                  children: [
                    if (version.changed.isEmpty)
                      const Padding(
                        padding: EdgeInsets.all(14),
                        child: Text('初始内容基线。'),
                      )
                    else
                      SourceChanges(version.changed),
                  ],
                ),
              ),
            const SizedBox(height: 18),
          ],
        ),
      );
}
