import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:go_router/go_router.dart';
import 'package:url_launcher/url_launcher.dart';

import '../../core/format.dart';
import '../../core/models.dart';
import '../../widgets/common.dart';
import 'reading_source.dart';

class ReadingSettingsPage extends ConsumerStatefulWidget {
  final int id;
  const ReadingSettingsPage({super.key, required this.id});
  @override
  ConsumerState<ReadingSettingsPage> createState() => _ReadingSettingsState();
}

class _ReadingSettingsState extends ConsumerState<ReadingSettingsPage> {
  String? mode;
  int? interval;
  bool busy = false;
  Future<void> act(Future<void> Function() action, String message) async {
    setState(() => busy = true);
    try {
      await action();
      if (mounted) toast(context, message);
    } catch (e) {
      if (mounted) toast(context, '$e', error: true);
    } finally {
      if (mounted) setState(() => busy = false);
    }
  }

  @override
  Widget build(BuildContext context) {
    final data = ref.watch(readingSourcesProvider);
    return Scaffold(
      appBar: AppBar(
        title: const Text('Source check settings'),
        leading: IconButton(
          tooltip: 'Back to sources',
          icon: const Icon(Icons.arrow_back),
          onPressed: () => context.go('/sources'),
        ),
      ),
      body: data.when(
        loading: () => const Center(child: CircularProgressIndicator()),
        error: (e, _) => Center(child: Text('Could not read source: $e')),
        data: (rows) {
          final s = rows.where((s) => s.id == widget.id).firstOrNull;
          if (s == null) return const Center(child: Text('Source not found, or not owned by this desk account.'));
          final controller = ref.read(readingSourcesProvider.notifier),
              cs = Theme.of(context).colorScheme;
          final selected = mode ?? s.mode, period = interval ?? s.interval;
          Widget heading(String text) => Padding(
            padding: const EdgeInsets.only(top: 23, bottom: 12),
            child: Text(text, style: Theme.of(context).textTheme.titleMedium),
          );
          Widget fact(String name, String value) => Padding(
            padding: const EdgeInsets.symmetric(vertical: 5),
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Text(
                  name,
                  style: TextStyle(fontSize: 12, color: cs.onSurfaceVariant),
                ),
                SelectableText(value),
              ],
            ),
          );
          return ListView(
            padding: const EdgeInsets.all(24),
            children: [
              Text(s.title(context), style: Theme.of(context).textTheme.headlineSmall),
              const SizedBox(height: 5),
              const Text(
                'Keeps docs, keywords, and history. Sign in on the school site in local Chrome and keep one original page as the dedicated monitor tab. After re-login, refresh the page to confirm content, then rebind.',
              ),
              heading('01 · What is checked'),
              fact('Source page', s.url),
              fact('Original query', s.query),
              fact('Original-site login', s.loginRequirement(context)),
              fact('Visibility', 'Only me'),
              fact('Match scope', s.scope(context)),
              fact('Linked docs', '${s.matchCount}  matches · ${s.items.length}  docs'),
              heading('02 · Source session & background reread'),
              if (s.result == 'documents_purged')
                const Text('Some linked docs were permanently deleted. Recapture and save from the original page to confirm the new scope.'),
              Card(
                child: Padding(
                  padding: const EdgeInsets.all(16),
                  child: Column(
                    crossAxisAlignment: CrossAxisAlignment.start,
                    children: [
                      Text(
                        s.identity(context),
                        style: const TextStyle(fontWeight: FontWeight.w600),
                      ),
                      const SizedBox(height: 6),
                      Text(
                        s.isPublic
                            ? 'Public source per your declaration; the test verifies this page can be reread.'
                            : 'Reuses the dedicated tab’s Chrome session and reads after a real refresh; cookies are not copied to the desk.',
                      ),
                      const SizedBox(height: 9),
                      Text(s.statusLabel(context), style: TextStyle(color: cs.primary)),
                      if (s.capability == 'account_unknown')
                        const Padding(
                          padding: EdgeInsets.only(top: 8),
                          child: Text(
                            'You can bind the current page session for single-account monitoring; no need to stay manual just to detect email. Unknown account ≠ authenticated; known account switches still pause.',
                          ),
                        ),
                      const SizedBox(height: 12),
                      Wrap(
                        spacing: 8,
                        runSpacing: 8,
                        children: [
                          OutlinedButton.icon(
                            onPressed: () => launchUrl(Uri.parse(s.url)),
                            icon: const Icon(Icons.open_in_new),
                            label: Text(s.isPublic ? 'Open original page' : 'Sign in on school site'),
                          ),
                          FilledButton.icon(
                            onPressed:
                                busy ||
                                    s.active ||
                                    s.result == 'documents_purged'
                                ? null
                                : () => act(
                                    () => controller.activate(s, period),
                                    'Binding the original page and starting auto-monitor; success time appears after the first real refresh.',
                                  ),
                            icon: const Icon(Icons.play_arrow),
                            label: Text(
                              s.active
                                  ? 'Waiting to run'
                                  : s.resident
                                  ? 'Rebind monitor page and start'
                                  : 'Bind page and enable periodic monitoring',
                            ),
                          ),
                          if (!s.resident && s.capability != 'account_unknown')
                            FilledButton.tonal(
                              onPressed: busy || s.active
                                  ? null
                                  : () => act(
                                      () => controller.check(s, 'verify'),
                                      'Reread test queued; keep Chrome and the extension running.',
                                    ),
                              child: Text(
                                s.active
                                    ? 'Waiting for browser'
                                    : s.verified
                                    ? 'Retest reread'
                                    : 'Authorize and test reread',
                              ),
                            ),
                        ],
                      ),
                      if (s.result == 'permission_denied')
                        const Text('Open the extension on the school site, extract, allow access, then return here to test.'),
                    ],
                  ),
                ),
              ),
              if (!s.deviceOnline)
                const Padding(
                  padding: EdgeInsets.only(top: 10),
                  child: Text('No recent executor connection; queued ≠ executed.'),
                ),
              heading('03 · Check mode'),
              if (s.resident)
                const Padding(
                  padding: EdgeInsets.only(bottom: 12),
                  child: Text('Interval, pause, and check-now apply to all rules on this monitor page; delete only affects the selected rule.'),
                ),
              DropdownButtonFormField<String>(
                initialValue: selected,
                decoration: const InputDecoration(labelText: 'Check mode'),
                items: const [
                  DropdownMenuItem(value: 'manual', child: Text('Manual check only')),
                  DropdownMenuItem(value: 'periodic', child: Text('Periodic checks')),
                ],
                onChanged: !s.verified || busy
                    ? null
                    : (v) => setState(() => mode = v),
              ),
              if (selected == 'periodic')
                Padding(
                  padding: const EdgeInsets.only(top: 15),
                  child: DropdownButtonFormField<int>(
                    initialValue: period,
                    decoration: const InputDecoration(labelText: 'Check interval'),
                    items: const [
                      DropdownMenuItem(value: 1800, child: Text('Every 30 minutes')),
                      DropdownMenuItem(value: 3600, child: Text('Every 1 hour')),
                      DropdownMenuItem(value: 7200, child: Text('Every 2 hours')),
                    ],
                    onChanged: !s.verified || busy
                        ? null
                        : (v) => setState(() => interval = v),
                  ),
                ),
              const SizedBox(height: 13),
              const Text(
                'Keep the dedicated monitor page open; desk can close. Edits defer refresh; login expiry or closed tab pauses. Keep Chrome, extension, and local service running; failures do not overwrite successful docs.',
              ),
              const SizedBox(height: 24),
              Wrap(
                spacing: 10,
                runSpacing: 10,
                children: [
                  FilledButton(
                    onPressed: !s.verified || busy || s.active
                        ? null
                        : () => act(
                            () => controller.configure(
                              s,
                              s.settings(
                                mode: selected,
                                interval: period,
                                paused: false,
                              ),
                            ),
                            selected == 'periodic' ? 'Periodic checks enabled.' : 'Manual check settings saved.',
                          ),
                    child: Text(selected == 'periodic' ? 'Enable periodic checks' : 'Save check settings'),
                  ),
                  if (s.verified)
                    OutlinedButton(
                      onPressed: busy || s.active
                          ? null
                          : () => act(
                              () => controller.check(s, 'check'),
                              'Check queued; status updates after confirmation.',
                            ),
                      child: const Text('Check now'),
                    ),
                  TextButton(
                    onPressed: () => context.push('/sources/${s.id}/checks'),
                    child: const Text('Check log'),
                  ),
                ],
              ),
              heading('Saved docs'),
              for (final item in s.items)
                ListTile(
                  contentPadding: EdgeInsets.zero,
                  leading: const Icon(Icons.article_outlined),
                  title: Text('${item['title']}'),
                  subtitle: Text('v${item['version']} · view original & version diffs'),
                  trailing: const Icon(Icons.chevron_right),
                  onTap: () => context.push('/item/${item['id']}'),
                ),
            ],
          );
        },
      ),
    );
  }
}

class ReadingChecksPage extends ConsumerWidget {
  final int id;
  const ReadingChecksPage({super.key, required this.id});
  @override
  Widget build(BuildContext context, WidgetRef ref) {
    return Scaffold(
      appBar: AppBar(
        title: const Text('Source check log'),
        actions: [
          IconButton(
            tooltip: 'Refresh log',
            icon: const Icon(Icons.refresh),
            onPressed: () => ref.invalidate(readingChecksProvider(id)),
          ),
        ],
      ),
      body: ReadingChecksBody(id: id),
    );
  }
}

class ReadingChecksBody extends ConsumerWidget {
  final int id;
  const ReadingChecksBody({super.key, required this.id});
  @override
  Widget build(BuildContext context, WidgetRef ref) => ref
      .watch(readingChecksProvider(id))
      .when(
        loading: () => const Center(child: CircularProgressIndicator()),
        error: (e, _) => Center(child: Text('Could not read log: $e')),
        data: (rows) => ListView(
          padding: const EdgeInsets.all(24),
          children: [
            const Text('Verification does not update last-success time; failures and non-matches do not overwrite saved content.'),
            const SizedBox(height: 15),
            if (rows.isEmpty) const Text('No source checks yet.'),
            for (final r in rows)
              Card(
                child: ListTile(
                  leading: Icon(
                    r['result'] == 'changed'
                        ? Icons.change_circle_outlined
                        : r['result'] == 'unchanged' ||
                              r['result'] == 'verified'
                        ? Icons.check_circle_outline
                        : Icons.error_outline,
                  ),
                  title: Text(readingResultLabel('${r['result']}', context)),
                  subtitle: Text(
                    '${r['purpose'] == 'verify'
                        ? 'Reread verification'
                        : r['purpose'] == 'activate'
                        ? 'First refresh / bind'
                        : 'Source check'} · ${relative(tsToDate((r['checked_at'] as num).toDouble()), context)}'
                    '${r['result'] == 'result_rejected' ? '\nRejected: ${(r['detail'] as Map?)?['error'] ?? 'unknown'}; saved docs kept—restart monitoring.' : ''}',
                  ),
                ),
              ),
          ],
        ),
      );
}

final readingChecksProvider = FutureProvider.autoDispose
    .family<List<Map<String, dynamic>>, int>((ref, id) {
      ref.watch(
        readingSourcesProvider.select(
          (v) => v.value
              ?.where((s) => s.id == id)
              .map((s) => '${s.lastAttempt}|${s.result}|${s.active}')
              .firstOrNull,
        ),
      );
      return ref.watch(readingRepositoryProvider).checks(id);
    });
