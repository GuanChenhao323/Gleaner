import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:url_launcher/url_launcher.dart';

import '../../core/api.dart';
import '../../core/format.dart';
import '../../core/models.dart';
import '../../core/providers.dart';
import '../../core/session.dart';
import '../../core/store.dart';
import '../../l10n/app_localizations.dart';
import '../../widgets/common.dart';

import 'package:go_router/go_router.dart';

import 'reading_source.dart';
import 'source_purge.dart';
import 'reading_source_card.dart';
import 'resident_source_group.dart';
import 'campus_source_entries.dart';

class SourcesPage extends ConsumerWidget {
  const SourcesPage({super.key});
  Future<void> _act(
    BuildContext context,
    Future<void> Function() action,
    String message,
  ) async {
    try {
      await action();
      if (context.mounted && message.isNotEmpty) toast(context, message);
    } catch (e) {
      if (context.mounted) toast(context, '$e', error: true);
    }
  }

  Future<void> _remove(
    BuildContext context,
    WidgetRef ref,
    ReadingSource source,
  ) async {
    final l10n = AppLocalizations.of(context);
    bool trashItems = false;
    final confirmed = await showDialog<bool>(
      context: context,
      builder: (c) => StatefulBuilder(
        builder: (c, update) => AlertDialog(
          title: Text(l10n.deleteSourceTitle),
          content: Column(
            mainAxisSize: MainAxisSize.min,
            children: [
              Text(l10n.deleteSourceBody),
              CheckboxListTile(
                value: trashItems,
                onChanged: (v) => update(() => trashItems = v ?? false),
                title: Text(l10n.deleteSourceAlsoTrash),
                subtitle: Text(l10n.deleteSourceAlsoTrashHint),
              ),
            ],
          ),
          actions: [
            TextButton(
              onPressed: () => Navigator.pop(c, false),
              child: Text(l10n.actionCancel),
            ),
            FilledButton(
              onPressed: () => Navigator.pop(c, true),
              child: Text(l10n.deleteSourceAction),
            ),
          ],
        ),
      ),
    );
    if (confirmed != true || !context.mounted) return;
    await _act(context, () async {
      await ref
          .read(readingSourcesProvider.notifier)
          .remove(source, trashItems);
      await ref.read(feedProvider.notifier).refreshAll();
      ref.invalidate(sourcesProvider);
      ref.invalidate(legacyCapturesProvider);
      ref.invalidate(deletedReadingSourcesProvider);
    }, trashItems ? l10n.sourceDeletedTrash : l10n.sourceDeletedKeep);
  }

  Future<void> _purge(
    BuildContext context,
    WidgetRef ref,
    Map<String, dynamic> source,
  ) async {
    await _act(context, () async {
      final repo = ref.read(readingRepositoryProvider);
      final plan = await repo.purgePreview(source['id'] as int);
      if (!context.mounted) return;
      final confirmed = await showDialog<bool>(
        context: context,
        builder: (c) => SourcePurgeDialog(
          plan: plan,
          title: '${(source['recipe'] as Map)['query']}',
        ),
      );
      if (confirmed != true || !context.mounted) return;
      if (!identical(repo, ref.read(readingRepositoryProvider))) {
        throw StateError(AppLocalizations.of(context).accountChangedConfirm);
      }
      final result = await repo.purge(plan);
      if (!identical(repo, ref.read(readingRepositoryProvider))) return;
      String? cleanupError;
      try {
        await ref
            .read(feedProvider.notifier)
            .forgetPermanently(result.itemIds, result.generation);
      } catch (e) {
        cleanupError = '$e';
      }
      for (final id in result.itemIds) {
        ref.invalidate(versionsProvider(id));
      }
      ref.invalidate(deletedReadingSourcesProvider);
      ref.invalidate(sourcesProvider);
      ref.invalidate(legacyCapturesProvider);
      await ref.read(readingSourcesProvider.notifier).refresh();
      if (context.mounted) {
        final loc = AppLocalizations.of(context);
        toast(
          context,
          cleanupError == null
              ? loc.sourcePurgedOk
              : loc.sourcePurgedPartial(cleanupError),
          error: cleanupError != null,
        );
      }
    }, '');
  }

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final l10n = AppLocalizations.of(context);
    final deleted = ref.watch(deletedReadingSourcesProvider);
    final data = ref.watch(readingSourcesProvider),
        legacy = ref.watch(sourcesProvider),
        captures = ref.watch(legacyCapturesProvider);
    void refresh() {
      ref.read(readingSourcesProvider.notifier).refresh().catchError((
        Object e,
      ) {
        if (context.mounted) toast(context, l10n.statusRefreshFailed('$e'), error: true);
      });
      ref.invalidate(sourcesProvider);
      ref.invalidate(legacyCapturesProvider);
      ref.invalidate(deletedReadingSourcesProvider);
    }

    return Scaffold(
      appBar: AppBar(
        actions: [
          IconButton(
            tooltip: l10n.refreshSourceListTooltip,
            icon: const Icon(Icons.refresh),
            onPressed: refresh,
          ),
          Padding(
            padding: const EdgeInsets.only(right: 16),
            child: FilledButton.tonalIcon(
              onPressed: () => showModalBottomSheet<void>(
                context: context,
                isScrollControlled: true,
                builder: (c) => const FractionallySizedBox(
                  heightFactor: .88,
                  child: SingleChildScrollView(
                    padding: EdgeInsets.all(24),
                    child: CampusSourceEntries(),
                  ),
                ),
              ),
              icon: const Icon(Icons.add),
              label: Text(l10n.captureFromWeb),
            ),
          ),
        ],
      ),
      body: data.when(
        skipLoadingOnReload: true,
        skipLoadingOnRefresh: true,
        loading: () => const Center(child: CircularProgressIndicator()),
        error: (e, _) => EmptyState(
          icon: Icons.cloud_off,
          title: l10n.cannotReadSources,
          message: '$e',
          action: OutlinedButton(onPressed: refresh, child: Text(l10n.retry)),
        ),
        data: (rows) {
          final linked = rows
              .expand((s) => s.items)
              .map((i) => i['id'])
              .toSet();
          final controller = ref.read(readingSourcesProvider.notifier),
              cs = Theme.of(context).colorScheme;
          Widget metric(String value, String label) => Column(
            children: [
              Text(
                value,
                style: Theme.of(context).textTheme.headlineSmall
                    ?.copyWith(color: cs.primary),
              ),
              Text(
                label,
                style: TextStyle(fontSize: 12, color: cs.onSurfaceVariant),
              ),
            ],
          );
          final oldCaptures = (captures.value ?? <Map<String, dynamic>>[])
              .where((r) => !linked.contains(r['item_id']))
              .toList();
          final oldSources = (legacy.value ?? <Source>[])
              .where((s) => s.type != 'browser')
              .toList();
          final groups = <String, List<ReadingSource>>{};
          for (final s in rows) {
            groups.putIfAbsent(s.pageId ?? 'legacy-${s.id}', () => []).add(s);
          }
          Widget ruleCard(ReadingSource s) =>
                ReadingSourceCard(
                  source: s,
                  onCheck: () => _act(
                    context,
                    () => controller.check(s, 'check'),
                    l10n.checkQueued,
                  ),
                  onSettings: () => context.push('/sources/${s.id}/settings'),
                  onDetails: () => context.push('/sources/${s.id}${s.result=='changed'?'?tab=changes':''}'),
                  onLogs: () => context.push('/sources/${s.id}/checks'),
                  onPause: () => _act(
                    context,
                    () =>
                        controller.configure(s, s.settings(paused: !s.paused)),
                    s.paused ? l10n.periodicResumed : l10n.periodicPaused,
                  ),
                  onOpen: () => launchUrl(Uri.parse(s.url)),
                  onDelete: () => _remove(context, ref, s),
                );
          return ListView(
            padding: const EdgeInsets.fromLTRB(28, 20, 28, 56),
            children: [
              if (rows.isNotEmpty) ...[
                Text(
                  rows.any((s) => s.deviceOnline)
                      ? l10n.chromeConnectedHint
                      : l10n.chromeDisconnectedHint,
                  style: TextStyle(fontSize: 12, color: cs.onSurfaceVariant, height: 1.5),
                ),
                const SizedBox(height: 20),
              ],
              Card(
                child: Padding(
                  padding: const EdgeInsets.symmetric(
                    vertical: 22,
                    horizontal: 12,
                  ),
                  child: LayoutBuilder(
                    builder: (context, c) => Wrap(
                      alignment: WrapAlignment.spaceAround,
                      spacing: 20,
                      runSpacing: 18,
                      children: [
                        metric('${groups.length}', l10n.savedPages),
                        metric(
                          '${rows.where((s) => s.periodic).length}',
                          l10n.periodicRules,
                        ),
                        metric(
                          '${rows.where((s) => !['not_executed', 'verified', 'unchanged', 'changed', 'starting', 'user_busy'].contains(s.result) || s.capability == 'account_unknown').length}',
                          l10n.needsAttention,
                        ),
                        metric(
                          '${rows.where((s) => s.result == 'changed').length}',
                          l10n.changesFound,
                        ),
                      ],
                    ),
                  ),
                ),
              ),
              const SizedBox(height: 32),
              Text(l10n.mySources, style: Theme.of(context).textTheme.titleMedium),
              const SizedBox(height: 16),
              if (rows.isEmpty)
                Padding(
                  padding: const EdgeInsets.symmetric(vertical: 36),
                  child: Text(
                    l10n.noReadingSources,
                    style: TextStyle(color: cs.onSurfaceVariant, height: 1.55),
                  ),
                ),
              for (final group in groups.values) ...[
                if (group.first.resident)
                  ResidentSourceGroup(
                    rules: group,
                    ruleCard: ruleCard,
                    onSettings: () =>
                        context.push('/sources/${group.first.id}/settings'),
                    onCheck: () => _act(
                      context,
                      () => controller.check(group.first, 'check'),
                      l10n.pageCheckQueued,
                    ),
                    onPause: () => _act(
                      context,
                      () => controller.configure(
                        group.first,
                        group.first.settings(
                          paused: !group.any((s) => s.paused),
                        ),
                      ),
                      l10n.pagePlanUpdated,
                    ),
                  )
                else
                  ruleCard(group.first),
                const SizedBox(height: 12),
              ],
              Padding(
                padding: const EdgeInsets.fromLTRB(0, 20, 0, 28),
                child: Text(
                  l10n.monitorTabHint,
                  style: TextStyle(fontSize: 12, color: cs.onSurfaceVariant, height: 1.55),
                ),
              ),
              deleted.when(
                loading: () => const LinearProgressIndicator(),
                error: (e, _) => Text(l10n.deletedSourcesUnavailable('$e')),
                data: (values) => ExpansionTile(
                  tilePadding: EdgeInsets.zero,
                  childrenPadding: const EdgeInsets.only(bottom: 8),
                  title: Text(l10n.deletedSourcesTitle(values.length)),
                  subtitle: Text(l10n.deletedSourcesSubtitle),
                  children: [
                    for (final value in values)
                      ListTile(
                        title: Text('${(value['recipe'] as Map)['query']}'),
                        subtitle: Column(
                          crossAxisAlignment: CrossAxisAlignment.start,
                          children: [
                            Text(l10n.checkStoppedKept),
                            Wrap(
                              spacing: 12,
                              children: [
                                TextButton.icon(
                                  icon: const Icon(Icons.restore),
                                  label: Text(l10n.restoreSourceAction),
                                  onPressed: () => _act(
                                    context,
                                    () => controller.restore(
                                      value['id'] as int,
                                      value['revision'] as int,
                                    ),
                                    l10n.sourceRestoredPaused,
                                  ),
                                ),
                                TextButton.icon(
                                  style: TextButton.styleFrom(
                                    foregroundColor: cs.error,
                                  ),
                                  icon: const Icon(Icons.delete_forever),
                                  label: Text(l10n.purgeForever),
                                  onPressed: () => _purge(context, ref, value),
                                ),
                              ],
                            ),
                          ],
                        ),
                      ),
                  ],
                ),
              ),
              const SizedBox(height: 8),
              if (oldCaptures.isNotEmpty ||
                  oldSources.isNotEmpty ||
                  captures.hasError)
                ExpansionTile(
                  tilePadding: EdgeInsets.zero,
                  childrenPadding: const EdgeInsets.only(bottom: 8),
                  title: Text(l10n.legacyDemoTitle),
                  subtitle: Text(l10n.legacyDemoSubtitle),
                  children: [
                    if (captures.hasError) Text(l10n.legacyCapturesFailed('${captures.error}')),
                    for (final r in oldCaptures)
                      Card(
                        child: ListTile(
                          leading: const Icon(Icons.inventory_2_outlined),
                          title: Text('${r['title']}'),
                          subtitle: Text('${r['url']}\n${l10n.legacyCaptureSubtitle}'),
                          onTap: () => context.push('/item/${r['item_id']}'),
                        ),
                      ),
                    for (final s in oldSources) _SourceCard(s),
                    TextButton(
                      onPressed: () => showAddSource(context, ref),
                      child: Text(l10n.manageLegacySources),
                    ),
                  ],
                ),
            ],
          );
        },
      ),
    );
  }
}

final legacyCapturesProvider = FutureProvider<List<Map<String, dynamic>>>((
  ref,
) async {
  final api = ref.watch(apiProvider);
  final results = await Future.wait([api.browserMonitors(), api.webCaptures()]);
  return [
    ...results[0],
    ...results[1].map((r) => {...r, 'item_id': r['id']}),
  ];
});

class _SourceCard extends ConsumerWidget {
  final Source s;
  const _SourceCard(this.s);

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final t = Theme.of(context);
    final cs = t.colorScheme;
    final api = ref.read(apiProvider);
    return Card(
      child: Padding(
        padding: const EdgeInsets.fromLTRB(16, 14, 8, 10),
        child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
          Row(children: [
            Container(
              padding: const EdgeInsets.all(10),
              decoration: BoxDecoration(color: cs.primaryContainer, borderRadius: BorderRadius.circular(14)),
              child: Icon(sourceIcon(s.type), color: cs.onPrimaryContainer),
            ),
            const SizedBox(width: 14),
            Expanded(
              child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
                Row(children: [
                  Flexible(child: Text(s.name, style: t.textTheme.titleSmall?.copyWith(fontWeight: FontWeight.w700), overflow: TextOverflow.ellipsis)),
                  const SizedBox(width: 8),
                  if (s.shared) Pill('Shared', color: cs.outline),
                  if (s.viaAgent) Pill('Local agent', color: cs.tertiary, icon: Icons.computer),
                  if (s.muted) Pill('Muted', color: cs.outline, icon: Icons.notifications_off),
                ]),
                const SizedBox(height: 2),
                Text(s.endpoint, maxLines: 1, overflow: TextOverflow.ellipsis, style: t.textTheme.bodySmall?.copyWith(color: cs.onSurfaceVariant)),
              ]),
            ),
            PopupMenuButton<String>(
              onSelected: (v) async {
                try {
                  if (v == 'refresh') {
                    final r = await api.refreshSource(s.id);
                    if (context.mounted) toast(context, r['checking'] == false ? (r['message'] ?? 'Queued; will check shortly').toString() : 'Added to check queue');
                  } else if (v == 'login') {
                    if (context.mounted) await showLogin(context, ref, s);
                  } else if (v == 'mute') {
                    await api.updateSource(s.id, {'muted': !s.muted});
                  } else if (v == 'weight') {
                    if (context.mounted) await _weight(context, ref, s);
                  } else if (v == 'delete') {
                    final ok = await showDialog<bool>(
                      context: context,
                      builder: (c) => AlertDialog(
                        title: Text('Unsubscribe “${s.name}”?'),
                        content: Text(s.shared ? 'Shared sources remain for other students.' : 'This source and its login session will be deleted.'),
                        actions: [TextButton(onPressed: () => Navigator.pop(c, false), child: const Text('Cancel')), FilledButton(onPressed: () => Navigator.pop(c, true), child: const Text('Delete'))],
                      ),
                    );
                    if (ok == true) await api.removeSource(s.id);
                  }
                } on ApiException catch (e) {
                  if (context.mounted) toast(context, e.message, error: true);
                }
                ref.invalidate(sourcesProvider);
              },
              itemBuilder: (_) => [
                const PopupMenuItem(value: 'refresh', child: ListTile(leading: Icon(Icons.sync), title: Text('Check now'))),
                if (s.type == 'moodle' || s.isMail) PopupMenuItem(value: 'login', child: ListTile(leading: const Icon(Icons.login), title: Text(s.hasLogin ? 'Sign in again' : 'Sign in'))),
                PopupMenuItem(value: 'mute', child: ListTile(leading: Icon(s.muted ? Icons.notifications : Icons.notifications_off_outlined), title: Text(s.muted ? 'Unmute' : 'Mute'))),
                const PopupMenuItem(value: 'weight', child: ListTile(leading: Icon(Icons.tune), title: Text('Adjust importance'))),
                const PopupMenuItem(value: 'delete', child: ListTile(leading: Icon(Icons.delete_outline), title: Text('Unsubscribe'))),
              ],
            ),
          ]),
          const SizedBox(height: 12),
          Wrap(spacing: 10, runSpacing: 8, crossAxisAlignment: WrapCrossAlignment.center, children: [
            SourceStatusPill(s),
            _meta(context, Icons.check_circle_outline, 'Last success: ${relative(tsToDate(s.lastSuccessAt), context)}'),
            _meta(context, Icons.update, 'Last check: ${relative(tsToDate(s.lastCheckedAt), context)}'),
            _meta(context, Icons.inventory_2_outlined, '${s.itemCount} items'),
            if (s.savedRatio != null) _meta(context, Icons.savings_outlined, '304 hits ${(s.savedRatio! * 100).round()}%'),
          ]),
          if (s.needsLogin) ...[
            const SizedBox(height: 12),
            Container(
              padding: const EdgeInsets.all(12),
              decoration: BoxDecoration(color: cs.tertiaryContainer, borderRadius: BorderRadius.circular(14)),
              child: Row(children: [
                Icon(Icons.lock_clock, color: cs.onTertiaryContainer),
                const SizedBox(width: 10),
                Expanded(child: Text(s.hasLogin ? 'Session expired; checks paused to avoid repeated requests.' : 'Sign in once to start checks; only the session is stored, not the SSO password.', style: TextStyle(color: cs.onTertiaryContainer))),
                FilledButton.tonal(onPressed: () => showLogin(context, ref, s), child: Text(s.hasLogin ? 'Sign in again' : 'Sign in')),
              ]),
            ),
          ] else if (s.status == 'failed' && (s.lastError ?? '').isNotEmpty) ...[
            const SizedBox(height: 10),
            Text('Latest error: ${s.lastError}', style: TextStyle(color: cs.error, fontSize: 12)),
          ],
        ]),
      ),
    );
  }

  Widget _meta(BuildContext context, IconData i, String text) {
    final cs = Theme.of(context).colorScheme;
    return Row(mainAxisSize: MainAxisSize.min, children: [
      Icon(i, size: 14, color: cs.onSurfaceVariant),
      const SizedBox(width: 4),
      Text(text, style: TextStyle(fontSize: 12, color: cs.onSurfaceVariant)),
    ]);
  }

  Future<void> _weight(BuildContext context, WidgetRef ref, Source s) async {
    var v = s.weight;
    final ok = await showDialog<bool>(
      context: context,
      builder: (c) => StatefulBuilder(
        builder: (c, set) => AlertDialog(
          title: const Text('Importance'),
          content: Column(mainAxisSize: MainAxisSize.min, crossAxisAlignment: CrossAxisAlignment.start, children: [
            const Text('Higher weight makes items from this source more likely to be urgent and pushed.'),
            Slider(value: v, divisions: 10, label: v.toStringAsFixed(1), onChanged: (x) => set(() => v = x)),
          ]),
          actions: [TextButton(onPressed: () => Navigator.pop(c, false), child: const Text('Cancel')), FilledButton(onPressed: () => Navigator.pop(c, true), child: const Text('Save'))],
        ),
      ),
    );
    if (ok == true) await ref.read(apiProvider).updateSource(s.id, {'weight': v});
  }
}

Future<void> showLogin(BuildContext context, WidgetRef ref, Source s) async {
  final user = TextEditingController();
  final pw = TextEditingController();
  final smtpHost = TextEditingController();
  final smtpPort = TextEditingController(text: '587');
  final key = TextEditingController();
  // Moodle 默认用Security key：学校多为统一认证（CAS / SSO），Username & password换不到 token
  final isMoodle = s.type == 'moodle';
  var useKey = isMoodle;
  var busy = false;
  String? err;
  await showDialog<void>(
    context: context,
    builder: (c) => StatefulBuilder(
      builder: (c, set) => AlertDialog(
        title: Text('Sign in to “${s.name}」'),
        content: SizedBox(
          width: 380,
          child: Column(mainAxisSize: MainAxisSize.min, crossAxisAlignment: CrossAxisAlignment.stretch, children: [
            if (isMoodle) ...[
              SegmentedButton<bool>(
                segments: const [
                  ButtonSegment(value: true, label: Text('Paste security key'), icon: Icon(Icons.key_outlined)),
                  ButtonSegment(value: false, label: Text('Username & password'), icon: Icon(Icons.password)),
                ],
                selected: {useKey},
                onSelectionChanged: busy
                    ? null
                    : (v) => set(() {
                          useKey = v.first;
                          err = null;
                        }),
              ),
              const SizedBox(height: 12),
            ],
            Text(
              useKey
                  ? 'Use this when the school uses SSO—Gleaner never sees your SSO password:\n'
                      '1. Sign in to Moodle in the browser, open Preferences → Security keys;\n'
                      '2. Copy the Moodle mobile web service key and paste it below.\n'
                      'The key is stored with AES-GCM; reset it in Moodle to revoke anytime.'
                  : s.isMail
                      ? 'Use an email app password. It is stored with AES-GCM for IMAP/SMTP.'
                      : 'Username/password are used only for this login; only the resulting session is encrypted and stored.',
              style: TextStyle(color: Theme.of(c).colorScheme.onSurfaceVariant),
            ),
            const SizedBox(height: 16),
            if (useKey) ...[
              OutlinedButton.icon(
                onPressed: () => launchUrl(Uri.parse(s.endpoint).resolve('/user/managetoken.php')),
                icon: const Icon(Icons.open_in_new),
                label: const Text('Open Moodle security-key page'),
              ),
              const SizedBox(height: 12),
              TextField(
                controller: key,
                autocorrect: false,
                enableSuggestions: false,
                decoration: const InputDecoration(labelText: 'Security key', hintText: '32-character alphanumeric', prefixIcon: Icon(Icons.key_outlined)),
              ),
            ] else ...[
              TextField(controller: user, decoration: InputDecoration(labelText: s.isMail ? 'Email address' : 'Student ID / username', prefixIcon: const Icon(Icons.person_outline))),
              const SizedBox(height: 12),
              TextField(
                controller: pw,
                obscureText: true,
                decoration: InputDecoration(
                  labelText: s.isMail ? 'App password (not the mailbox login password)' : 'Password',
                  helperText: s.isMail ? 'Create it under Settings → Account security on the webmail site' : null,
                  prefixIcon: const Icon(Icons.lock_outline),
                ),
              ),
            ],
            if (s.isMail) ...[
              const SizedBox(height: 12),
              Row(children: [
                Expanded(flex: 3, child: TextField(controller: smtpHost, decoration: const InputDecoration(labelText: 'SMTP server (for sending, optional)'))),
                const SizedBox(width: 8),
                Expanded(child: TextField(controller: smtpPort, decoration: const InputDecoration(labelText: 'Port'))),
              ]),
            ],
            if (err != null) Padding(padding: const EdgeInsets.only(top: 12), child: Text(err!, style: TextStyle(color: Theme.of(c).colorScheme.error))),
          ]),
        ),
        actions: [
          TextButton(onPressed: busy ? null : () => Navigator.pop(c), child: const Text('Cancel')),
          FilledButton(
            onPressed: busy
                ? null
                : () async {
                    set(() {
                      busy = true;
                      err = null;
                    });
                    try {
                      final api = ref.read(apiProvider);
                      final r = useKey
                          ? await api.sourceLoginToken(s.id, key.text)
                          : await api.sourceLogin(
                              s.id,
                              user.text.trim(),
                              pw.text,
                              smtp: s.isMail && smtpHost.text.isNotEmpty ? {'host': smtpHost.text.trim(), 'port': int.tryParse(smtpPort.text) ?? 587} : null,
                            );
                      if (r['ok'] == true) {
                        ref.invalidate(sourcesProvider);
                        if (c.mounted) Navigator.pop(c);
                        if (context.mounted) toast(context, 'Signed in; running first check…');
                        return;
                      }
                      set(() => err = (r['error'] ?? 'Sign-in failed').toString());
                    } on ApiException catch (e) {
                      set(() => err = e.message);
                    } finally {
                      set(() => busy = false);
                    }
                  },
            child: busy ? const SizedBox(width: 18, height: 18, child: CircularProgressIndicator(strokeWidth: 2)) : Text(useKey ? 'Save key' : 'Sign in'),
          ),
        ],
      ),
    ),
  );
}

Future<void> showAddSource(BuildContext context, WidgetRef ref) async {
  await showModalBottomSheet<void>(
    context: context,
    isScrollControlled: true,
    builder: (c) => DraggableScrollableSheet(
      expand: false,
      initialChildSize: 0.85,
      maxChildSize: 0.95,
      builder: (c, scroll) => _AddSourceSheet(scroll: scroll),
    ),
  );
  ref.invalidate(sourcesProvider);
}

class _AddSourceSheet extends ConsumerStatefulWidget {
  final ScrollController scroll;
  const _AddSourceSheet({required this.scroll});
  @override
  ConsumerState<_AddSourceSheet> createState() => _AddSourceSheetState();
}

class _AddSourceSheetState extends ConsumerState<_AddSourceSheet> {
  final url = TextEditingController();
  final name = TextEditingController();
  final region = TextEditingController();
  String type = 'web';
  bool viaAgent = false;
  bool busy = false;
  Map<String, dynamic>? preview;

  @override
  Widget build(BuildContext context) {
    final tpl = ref.watch(templatesProvider);
    final t = Theme.of(context);
    final cs = t.colorScheme;
    return ListView(controller: widget.scroll, padding: const EdgeInsets.fromLTRB(20, 0, 20, 32), children: [
      Text('Add source', style: t.textTheme.titleLarge),
      const SizedBox(height: 4),
      Text('Campus templates already include page rules—tap to add.', style: TextStyle(color: cs.onSurfaceVariant)),
      const SizedBox(height: 16),
      tpl.when(
        loading: () => const LinearProgressIndicator(),
        error: (e, _) => Text('$e'),
        data: (list) => LayoutBuilder(
          builder: (context, c) {
            final cols = c.maxWidth > 640 ? 3 : 2;
            return GridView.count(
              shrinkWrap: true,
              physics: const NeverScrollableScrollPhysics(),
              crossAxisCount: cols,
              mainAxisSpacing: 10,
              crossAxisSpacing: 10,
              childAspectRatio: cols == 3 ? 1.5 : 1.25,
              children: [for (final x in list) _TemplateTile(x, onTap: () => _addTemplate(x))],
            );
          },
        ),
      ),
      const SizedBox(height: 24),
      Text('Custom URL', style: t.textTheme.titleMedium),
      const SizedBox(height: 4),
      Text('Any notice list page or RSS. Optionally limit the watch region with a CSS selector.', style: TextStyle(color: cs.onSurfaceVariant)),
      const SizedBox(height: 12),
      SegmentedButton<String>(
        segments: const [ButtonSegment(value: 'web', label: Text('Web'), icon: Icon(Icons.public)), ButtonSegment(value: 'rss', label: Text('RSS'), icon: Icon(Icons.rss_feed))],
        selected: {type},
        onSelectionChanged: (v) => setState(() => type = v.first),
      ),
      const SizedBox(height: 12),
      TextField(controller: url, decoration: const InputDecoration(labelText: 'URL', hintText: 'https://cs.example.edu/news/', prefixIcon: Icon(Icons.link))),
      const SizedBox(height: 10),
      TextField(controller: name, decoration: const InputDecoration(labelText: 'Name (optional)', prefixIcon: Icon(Icons.label_outline))),
      if (type == 'web') ...[
        const SizedBox(height: 10),
        TextField(controller: region, decoration: const InputDecoration(labelText: 'Watch region (CSS selector, optional)', hintText: '#main .news-list', prefixIcon: Icon(Icons.crop_free))),
      ],
      SwitchListTile(
        contentPadding: EdgeInsets.zero,
        value: viaAgent,
        onChanged: (v) => setState(() => viaAgent = v),
        title: const Text('Campus network only'),
        subtitle: const Text('Collected by the local agent on your computer, then uploaded'),
      ),
      const SizedBox(height: 8),
      Row(children: [
        OutlinedButton.icon(onPressed: busy ? null : _preview, icon: const Icon(Icons.preview_outlined), label: const Text('Preview')),
        const SizedBox(width: 12),
        FilledButton.icon(onPressed: busy ? null : _addCustom, icon: const Icon(Icons.add), label: const Text('Add')),
        if (busy) const Padding(padding: EdgeInsets.only(left: 16), child: SizedBox(width: 20, height: 20, child: CircularProgressIndicator(strokeWidth: 2))),
      ]),
      if (preview != null) ...[
        const SizedBox(height: 16),
        Card(
          child: Padding(
            padding: const EdgeInsets.all(14),
            child: preview!['ok'] == true
                ? Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
                    Text('Found ${preview!['count']} items; first few:', style: const TextStyle(fontWeight: FontWeight.w700)),
                    const SizedBox(height: 8),
                    for (final it in (preview!['items'] as List).take(5))
                      Padding(
                        padding: const EdgeInsets.symmetric(vertical: 4),
                        child: Row(children: [
                          const Icon(Icons.subdirectory_arrow_right, size: 16),
                          const SizedBox(width: 6),
                          Expanded(child: Text((it as Map)['title'].toString(), maxLines: 1, overflow: TextOverflow.ellipsis)),
                          if (it['deadline_at'] != null) Pill('Has deadline', color: cs.tertiary),
                        ]),
                      ),
                  ])
                : Text('Preview failed: ${preview!['error']}', style: TextStyle(color: cs.error)),
          ),
        ),
      ],
    ]);
  }

  Map<String, dynamic> _customBody() => {
        'type': type,
        'endpoint': url.text.trim(),
        if (name.text.trim().isNotEmpty) 'name': name.text.trim(),
        'via_agent': viaAgent,
        'private': viaAgent,
        if (type == 'web') 'config': {if (region.text.trim().isNotEmpty) 'region': region.text.trim(), 'item_selector': 'li', 'link_selector': 'a[href]'},
      };

  Future<void> _preview() async {
    setState(() => busy = true);
    try {
      final r = await ref.read(apiProvider).previewSource(_customBody());
      setState(() => preview = r);
    } on ApiException catch (e) {
      setState(() => preview = {'ok': false, 'error': e.message});
    } finally {
      setState(() => busy = false);
    }
  }

  Future<void> _addCustom() async {
    if (url.text.trim().isEmpty) return;
    setState(() => busy = true);
    try {
      await ref.read(apiProvider).addSource(_customBody());
      if (mounted) {
        Navigator.pop(context);
        toast(context, 'Added; first check will run shortly');
      }
    } on ApiException catch (e) {
      if (mounted) toast(context, e.message, error: true);
    } finally {
      if (mounted) setState(() => busy = false);
    }
  }

  Future<void> _addTemplate(SourceTemplate x) async {
    setState(() => busy = true);
    try {
      final r = await ref.read(apiProvider).addSource({'template': x.id});
      ref.invalidate(sourcesProvider);
      if (!mounted) return;
      Navigator.pop(context);
      if (r['needs_login'] == true) {
        final list = await ref.read(apiProvider).sources();
        final s = list.firstWhere((s) => s.id == (r['source'] as Map)['id']);
        if (mounted) await showLogin(context, ref, s);
      } else {
        toast(context, 'Added “${x.name}」');
        ref.read(feedProvider.notifier).refreshAll();
      }
    } on ApiException catch (e) {
      if (mounted) toast(context, e.message, error: true);
    } finally {
      if (mounted) setState(() => busy = false);
    }
  }
}

class _TemplateTile extends StatelessWidget {
  final SourceTemplate t;
  final VoidCallback onTap;
  const _TemplateTile(this.t, {required this.onTap});
  @override
  Widget build(BuildContext context) {
    final cs = Theme.of(context).colorScheme;
    return Material(
      color: cs.surfaceContainer,
      borderRadius: BorderRadius.circular(18),
      child: InkWell(
        borderRadius: BorderRadius.circular(18),
        onTap: onTap,
        child: Padding(
          padding: const EdgeInsets.all(14),
          child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
            Row(children: [
              Icon(templateIcon(t.icon), color: cs.primary),
              const Spacer(),
              if (t.needsLogin) Icon(Icons.lock_outline, size: 16, color: cs.onSurfaceVariant),
            ]),
            const SizedBox(height: 10),
            Text(t.name, style: const TextStyle(fontWeight: FontWeight.w700)),
            const SizedBox(height: 4),
            Expanded(child: Text(t.description, maxLines: 3, overflow: TextOverflow.ellipsis, style: TextStyle(fontSize: 12, color: cs.onSurfaceVariant, height: 1.35))),
          ]),
        ),
      ),
    );
  }
}
