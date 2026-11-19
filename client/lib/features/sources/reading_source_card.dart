import 'package:flutter/material.dart';

import '../../core/format.dart';
import '../../core/models.dart';
import 'reading_source.dart';

class ReadingSourceCard extends StatelessWidget {
  final ReadingSource source;
  final VoidCallback onCheck, onSettings, onDetails, onLogs, onPause, onOpen;
  final VoidCallback? onDelete;
  const ReadingSourceCard({
    super.key,
    required this.source,
    required this.onCheck,
    required this.onSettings,
    required this.onDetails,
    required this.onLogs,
    required this.onPause,
    required this.onOpen,
    this.onDelete,
  });
  @override
  Widget build(BuildContext context) {
    final s = source, cs = Theme.of(context).colorScheme;
    final warning =
        ![
          'not_executed',
          'starting',
          'user_busy',
          'restored',
          'documents_restored',
          'verified',
          'changed',
          'unchanged',
        ].contains(s.result) ||
        s.capability == 'account_unknown' || s.executionState == 'expired';
    Widget meta(IconData icon, String text) => Row(
      mainAxisSize: MainAxisSize.min,
      children: [
        Icon(icon, size: 14, color: cs.onSurfaceVariant),
        const SizedBox(width: 4),
        Flexible(
          child: Text(
            text,
            style: TextStyle(fontSize: 12, color: cs.onSurfaceVariant),
          ),
        ),
      ],
    );
    return Card(
      margin: const EdgeInsets.only(bottom: 12),
      child: Padding(
        padding: const EdgeInsets.all(18),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Row(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Container(
                  padding: const EdgeInsets.all(11),
                  decoration: BoxDecoration(
                    color: cs.primaryContainer,
                    borderRadius: BorderRadius.circular(14),
                  ),
                  child: Icon(
                    s.platform == 'moodle'
                        ? Icons.school_outlined
                        : s.platform == 'student'
                        ? Icons.campaign_outlined
                        : s.platform == 'fie'
                        ? Icons.badge_outlined
                        : Icons.public,
                    color: cs.onPrimaryContainer,
                  ),
                ),
                const SizedBox(width: 13),
                Expanded(
                  child: Column(
                    crossAxisAlignment: CrossAxisAlignment.start,
                    children: [
                      Wrap(
                        spacing: 8,
                        runSpacing: 5,
                        crossAxisAlignment: WrapCrossAlignment.center,
                        children: [
                          Text(
                            s.title(context),
                            style: Theme.of(context).textTheme.titleSmall
                                ?.copyWith(fontWeight: FontWeight.w700),
                          ),
                          Text(
                            s.loginRequirement(context),
                            style: TextStyle(
                              fontSize: 12,
                              color: cs.onSurfaceVariant,
                            ),
                          ),
                        ],
                      ),
                      const SizedBox(height: 3),
                      Text(
                        s.url,
                        style: TextStyle(
                          fontSize: 12,
                          color: cs.onSurfaceVariant,
                        ),
                        maxLines: 2,
                        overflow: TextOverflow.ellipsis,
                      ),
                    ],
                  ),
                ),
              ],
            ),
            const SizedBox(height: 13),
            Wrap(
              spacing: 8,
              runSpacing: 7,
              crossAxisAlignment: WrapCrossAlignment.center,
              children: [
                const Text('Extract conditions', style: TextStyle(fontSize: 12)),
                Container(
                  padding: const EdgeInsets.symmetric(
                    horizontal: 9,
                    vertical: 4,
                  ),
                  decoration: BoxDecoration(
                    color: cs.surface,
                    borderRadius: BorderRadius.circular(7),
                  ),
                  child: Text(
                    s.query,
                    style: TextStyle(fontSize: 12, color: cs.primary),
                  ),
                ),
                Text(
                  s.scope(context),
                  style: TextStyle(fontSize: 12, color: cs.onSurfaceVariant),
                ),
              ],
            ),
            const SizedBox(height: 10),
            Wrap(
              spacing: 15,
              runSpacing: 9,
              children: [
                Text(
                  s.statusLabel(context),
                  style: TextStyle(
                    fontSize: 12,
                    fontWeight: FontWeight.w600,
                    color: warning ? cs.error : cs.primary,
                  ),
                ),
                if (s.items.isNotEmpty)
                  meta(Icons.task_alt, 'Docs saved'),
                meta(Icons.person_outline, s.identity(context)),
                meta(Icons.lock_outline, 'Docs private to you'),
                meta(
                  Icons.check_circle_outline,
                  'Last success: ${relative(tsToDate(s.lastSuccess?.toDouble()), context)}',
                ),
                meta(
                  Icons.history,
                  'Last attempt: ${relative(tsToDate(s.lastAttempt?.toDouble()), context)}',
                ),
                meta(
                  Icons.inventory_2_outlined,
                  '${s.matchCount} ${s.isTimeline
                      ? ' activity summaries'
                      : s.platform == 'generic'
                      ? ' fragments'
                      : ' matches'} · ${s.items.length}  docs',
                ),
              ],
            ),
            if (s.result == 'need_login' || s.result == 'account_mismatch')
              Padding(
                padding: const EdgeInsets.only(top: 12),
                child: Row(
                  children: [
                    Expanded(
                      child: Text(
                        s.result == 'need_login'
                            ? 'Sign in again on the school site; saved docs and successful checks are kept.'
                            : 'Source account mismatch. Return to the original account and retest; normal restore cannot lift binding protection.',
                        style: TextStyle(fontSize: 12, color: cs.error),
                      ),
                    ),
                    TextButton(onPressed: onOpen, child: const Text('Sign in on school site')),
                  ],
                ),
              ),
            const SizedBox(height: 12),
            Divider(height: 1, color: cs.outlineVariant),
            const SizedBox(height: 9),
            Wrap(
              spacing: 12,
              runSpacing: 4,
              crossAxisAlignment: WrapCrossAlignment.center,
              children: [
                Text(
                  s.capability == 'account_unknown'
                      ? 'Manual capture on this page only'
                      : !s.verified
                      ? 'Background reread not verified yet'
                      : s.mode == 'manual'
                      ? 'Manual check only'
                      : s.paused
                      ? 'Periodic checks paused'
                      : 'Every ${s.interval ~/ 60} min · next ~ ${relative(tsToDate(s.nextAt?.toDouble()), context)}',
                  style: TextStyle(fontSize: 11, color: cs.onSurfaceVariant),
                ),
                TextButton(
                  onPressed: onDetails,
                  child: Text(s.result == 'changed' ? 'View docs & changes' : 'View docs'),
                ),
                TextButton(onPressed: onLogs, child: const Text('Check log')),
                TextButton(onPressed: onSettings, child: const Text('Settings')),
                if (onDelete != null)
                  TextButton.icon(
                    onPressed: onDelete,
                    icon: const Icon(Icons.delete_outline, size: 16),
                    label: Text(s.resident ? 'Delete this rule' : 'Delete source'),
                  ),
                if (s.mode == 'periodic' && s.verified)
                  TextButton(
                    onPressed: s.active ? null : onPause,
                    child: Text(s.paused ? 'Resume periodic' : 'Pause'),
                  ),
                if (s.verified)
                  OutlinedButton.icon(
                    onPressed: s.active ? null : onCheck,
                    icon: const Icon(Icons.refresh, size: 16),
                    label: Text(s.active ? 'Waiting for check' : 'Check now'),
                  )
                else if (s.capability != 'account_unknown')
                  FilledButton.tonal(
                    onPressed: onSettings,
                    child: const Text('Enable auto-monitor'),
                  ),
              ],
            ),
          ],
        ),
      ),
    );
  }
}
