import 'package:flutter/material.dart';
import 'package:url_launcher/url_launcher.dart';

import '../../l10n/app_localizations.dart';

/// Shows source scope and evidence, without presenting fragments as full articles.
class WebCaptureDetails extends StatelessWidget {
  final Map<String, dynamic> capture;
  final bool hasReadingSource;
  const WebCaptureDetails(
    this.capture, {
    super.key,
    this.hasReadingSource = false,
  });

  @override
  Widget build(BuildContext context) {
    final l10n = AppLocalizations.of(context);
    final binding = capture['source_binding'] as Map? ?? {};
    final fragments = capture['fragments'] as List? ?? [];
    final timeline = capture['collection_type'] == 'timeline_summary';
    final identity = binding['identity'] is Map
        ? (binding['identity'] as Map)['display']
        : l10n.wcAccountUnchecked;
    final meta = timeline
        ? [
            l10n.wcCond('${capture['query']}'),
            l10n.wcIdentitySchool,
            l10n.wcScopeTimeline,
          ].join('\n')
        : [
            l10n.wcCond('${capture['query']}'),
            capture['match_scope'] == 'title' ? l10n.wcMatchTitle : l10n.wcMatchBody,
            l10n.wcAlias('${binding['label'] ?? l10n.aliasMissing}'),
            binding['kind'] == 'public' ? l10n.wcLoginNone : l10n.wcLoginRequired,
            l10n.wcAccount('$identity'),
            l10n.wcPrivateOnly,
          ].join('\n');
    return Card(
      child: Padding(
        padding: const EdgeInsets.all(16),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Text(
              timeline
                  ? l10n.timelineMaterial(fragments.length)
                  : l10n.webSnapshot(fragments.length),
              style: Theme.of(context).textTheme.titleMedium,
            ),
            const SizedBox(height: 8),
            SelectableText(meta),
            Text(
              timeline
                  ? l10n.wcTimelineHint
                  : hasReadingSource
                  ? l10n.wcLinkedHint
                  : l10n.wcUnlinkedHint,
            ),
            Text(hasReadingSource ? l10n.wcUpdateOnChange : l10n.wcUpdateOnRecapture),
            for (final entry in fragments.indexed)
              ExpansionTile(
                title: Text(
                  timeline
                      ? l10n.activityN(entry.$1 + 1, '${(entry.$2 as Map)['title']}')
                      : l10n.fragmentN(entry.$1 + 1, '${(entry.$2 as Map)['title']}'),
                ),
                children: [
                  if (timeline)
                    Padding(
                      padding: const EdgeInsets.all(12),
                      child: SelectableText(
                        [
                          l10n.courseField('${((entry.$2 as Map)['fields'] as Map?)?['course'] ?? ''}'),
                          l10n.wcDateText('${((entry.$2 as Map)['fields'] as Map?)?['date_text'] ?? ''}'),
                          l10n.wcTimeText('${((entry.$2 as Map)['fields'] as Map?)?['datetime_text'] ?? ''}'),
                        ].join('\n'),
                      ),
                    ),
                  Padding(
                    padding: const EdgeInsets.all(12),
                    child: SelectableText(
                      '${(entry.$2 as Map)['text']}\n\n${l10n.wcDomEvidence('${((entry.$2 as Map)['evidence'] as Map?)?['locator'] ?? ''}')}',
                    ),
                  ),
                  if (timeline)
                    TextButton.icon(
                      onPressed: () =>
                          launchUrl(Uri.parse('${(entry.$2 as Map)['url']}')),
                      icon: const Icon(Icons.open_in_new),
                      label: Text(l10n.openActivity),
                    ),
                ],
              ),
          ],
        ),
      ),
    );
  }
}
