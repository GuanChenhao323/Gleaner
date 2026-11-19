import 'package:flutter/material.dart';

import '../../core/format.dart';
import '../../core/models.dart';
import '../../l10n/app_localizations.dart';
import 'reading_source.dart';

/// A page owns one refresh plan; rules keep their own content and histories.
class ResidentSourceGroup extends StatelessWidget {
  final List<ReadingSource> rules;
  final Widget Function(ReadingSource) ruleCard;
  final VoidCallback onSettings, onCheck, onPause;
  const ResidentSourceGroup({
    super.key,
    required this.rules,
    required this.ruleCard,
    required this.onSettings,
    required this.onCheck,
    required this.onPause,
  });
  @override
  Widget build(BuildContext context) {
    final first = rules.first, cs = Theme.of(context).colorScheme;
    final active = rules.any((s) => s.active),
        verified = rules.every((s) => s.verified),
        paused = rules.any((s) => s.paused),
        online = rules.every((s) => s.deviceOnline);
    final scheduled = rules.any((s) => s.periodic);
    final next = rules.map((s) => s.nextAt).whereType<num>().toList()..sort();
    final successes = rules.map((s) => s.lastSuccess).whereType<num>().toList()
      ..sort();
    final issue = rules
        .where(
          (s) => ![
            'unchanged',
            'changed',
            'verified',
            'starting',
          ].contains(s.result) || s.executionState == 'expired',
        )
        .firstOrNull;
    final l10n = AppLocalizations.of(context);
    final status = !online
        ? l10n.rsWaitLocalChrome
        : active
        ? l10n.rsStartingCheck
        : issue != null
        ? issue.statusLabel(context)
        : paused
        ? (rules.every((s) => s.paused) ? l10n.rsPeriodicPaused : l10n.rsPartialPaused)
        : verified
        ? (scheduled ? l10n.rsPeriodicOn : l10n.rsManualOnly)
        : l10n.rsAwaitFirstRefresh;
    return Card(
      margin: const EdgeInsets.only(bottom: 16),
      child: Padding(
        padding: const EdgeInsets.all(18),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Row(
              children: [
                Icon(Icons.web, color: cs.primary),
                const SizedBox(width: 12),
                Expanded(
                  child: Column(
                    crossAxisAlignment: CrossAxisAlignment.start,
                    children: [
                      Text(
                        '${Uri.parse(first.url).host} · ${l10n.rsDedicatedMonitor}',
                        style: Theme.of(context).textTheme.titleMedium,
                      ),
                      const SizedBox(height: 4),
                      Text(
                        first.url,
                        maxLines: 2,
                        overflow: TextOverflow.ellipsis,
                        style: TextStyle(
                          fontSize: 12,
                          color: cs.onSurfaceVariant,
                        ),
                      ),
                    ],
                  ),
                ),
              ],
            ),
            const SizedBox(height: 12),
            Wrap(
              spacing: 12,
              runSpacing: 8,
              children: [
                Text(
                  status,
                  style: TextStyle(
                    fontWeight: FontWeight.w600,
                    color: issue != null ? cs.error : cs.primary,
                  ),
                ),
                if (rules.any((s) => s.items.isNotEmpty))
                  const Text('Docs saved'),
                Text(
                  '${rules.length} rules · ${rules.every((s) => s.mode == 'manual') ? 'Manual check only' : 'every ${first.interval ~/ 60} min'}',
                ),
                if (first.effectiveInterval != first.interval)
                  Text(
                    'Local fixture test: every ${first.effectiveInterval}s',
                    style: TextStyle(color: cs.error),
                  ),
                const Text('Single-site session · docs private to you'),
                if (rules.any((s) => s.result == 'changed'))
                  const Text('Source changed · expand rules to see diffs'),
              ],
            ),
            const SizedBox(height: 9),
            Wrap(
              spacing: 16,
              runSpacing: 6,
              children: [
                Text(
                  'Last success: ${successes.length == rules.length ? relative(tsToDate(successes.first.toDouble()), context) : 'Waiting for first success on all rules'}',
                  style: const TextStyle(fontSize: 12),
                ),
                Text(
                  'Next scheduled: ${scheduled && next.isNotEmpty && next.first > 0 ? relative(tsToDate(next.first.toDouble()), context) : 'Waiting to start or resume'}',
                  style: const TextStyle(fontSize: 12),
                ),
              ],
            ),
            const SizedBox(height: 8),
            Wrap(
              spacing: 6,
              runSpacing: 4,
              children: [
                for (final s in rules)
                  Chip(
                    label: Text(s.query, style: const TextStyle(fontSize: 12)),
                  ),
              ],
            ),
            Wrap(
              spacing: 8,
              children: [
                FilledButton.tonal(
                  onPressed: onSettings,
                  child: Text(verified ? 'Monitor settings' : 'Start / rebind'),
                ),
                if (verified)
                  TextButton.icon(
                    onPressed: active ? null : onCheck,
                    icon: const Icon(Icons.refresh, size: 17),
                    label: const Text('Check all rules now'),
                  ),
                if (rules.any((s) => s.mode == 'periodic') &&
                    (verified || !paused))
                  TextButton(
                    onPressed: onPause,
                    child: Text(paused ? 'Resume periodic' : 'Pause periodic'),
                  ),
              ],
            ),
            ExpansionTile(
              tilePadding: EdgeInsets.zero,
              title: Text('Rules, docs & logs (${rules.length})'),
              children: [for (final s in rules) ruleCard(s)],
            ),
            Text(
              'Keep the dedicated monitor tab open; edits defer refresh. Desk page can close; local service must stay running.',
              style: TextStyle(fontSize: 11, color: cs.onSurfaceVariant),
            ),
          ],
        ),
      ),
    );
  }
}
