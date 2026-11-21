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
        appBar: AppBar(title: const Text('Source & docs')),
        body: Center(child: Text('$e')),
      ),
      data: (rows) {
        final source = rows.where((s) => s.id == id).firstOrNull;
        if (source == null) {
          return const Scaffold(body: Center(child: Text('Source not found, or not owned by this account.')));
        }
        return DefaultTabController(
          length: 3,
          initialIndex: showChanges ? 1 : 0,
          child: Scaffold(
            appBar: AppBar(
              title: const Text('Source & docs'),
              leading: IconButton(
                tooltip: 'Back to sources',
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
                        source.title(context),
                        style: Theme.of(context).textTheme.titleLarge,
                      ),
                      const SizedBox(height: 5),
                      Text('${source.identity(context)} · ${source.statusLabel(context)}'),
                      const SizedBox(height: 7),
                      Text(source.scope(context)),
                      const SizedBox(height: 12),
                      Wrap(
                        spacing: 9,
                        runSpacing: 7,
                        children: [
                          OutlinedButton.icon(
                            onPressed: () => launchUrl(Uri.parse(source.url)),
                            icon: const Icon(Icons.open_in_new, size: 16),
                            label: const Text('Open original page'),
                          ),
                          OutlinedButton(
                            onPressed: () =>
                                context.push('/sources/$id/settings'),
                            child: const Text('Check settings'),
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
                                          toast(context, 'Check queued; waiting for the browser.');
                                        }
                                      } catch (e) {
                                        if (context.mounted) {
                                          toast(context, '$e', error: true);
                                        }
                                      }
                                    },
                              child: const Text('Check now'),
                            ),
                        ],
                      ),
                    ],
                  ),
                ),
                const TabBar(
                  tabs: [
                    Tab(text: 'Saved content'),
                    Tab(text: 'Change history'),
                    Tab(text: 'Check log'),
                  ],
                ),
                Expanded(
                  child: TabBarView(
                    children: [
                      ListView(
                        padding: const EdgeInsets.all(24),
                        children: [
                          Text('Original query: ${source.query}'),
                          const SizedBox(height: 6),
                          Text('Original page: ${source.url}'),
                          const SizedBox(height: 16),
                          for (final item in source.items)
                            _SavedItem(id: item['id'] as int),
                        ],
                      ),
                      ListView(
                        padding: const EdgeInsets.all(24),
                        children: [
                          const Text('Source versions and personal edits are kept separately. Unchanged or failed checks do not add content versions.'),
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
        error: (e, _) => Text('Could not read docs: $e'),
        data: (item) => Card(
          child: ExpansionTile(
            initiallyExpanded: true,
            title: Text(item.title),
            subtitle: Text('Source version v${item.version}'),
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
                        child: Text('My notes (kept): ${item.state.note}'),
                      ),
                    TextButton(
                      onPressed: () => context.push('/item/$id'),
                      child: const Text('Open item workspace'),
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
        error: (e, _) => Text('Could not read versions: $e'),
        data: (versions) => Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Text(title, style: Theme.of(context).textTheme.titleMedium),
            for (final version in versions)
              Card(
                child: ExpansionTile(
                  title: Text(
                    'v${version.version} · ${version.version == 1
                        ? 'First save'
                        : version.note.isEmpty
                        ? 'Source content updated'
                        : version.note}',
                  ),
                  children: [
                    if (version.changed.isEmpty)
                      const Padding(
                        padding: EdgeInsets.all(14),
                        child: Text('Initial content baseline.'),
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
