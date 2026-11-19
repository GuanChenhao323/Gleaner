import 'package:flutter/material.dart';

import '../../l10n/app_localizations.dart';

/// A server-signed impact snapshot. UI cannot choose arbitrary item IDs to erase.
class SourcePurgePlan {
  final Map<String, dynamic> plan;
  final String token;
  SourcePurgePlan.fromJson(Map<String, dynamic> value)
    : plan = Map<String, dynamic>.from(
        value['plan'] is Map ? value['plan'] as Map : {},
      ),
      token = value['token'] is String ? value['token'] as String : '' {
    if (plan['source_id'] is! int ||
        plan['revision'] is! int ||
        plan['generation'] is! int ||
        plan['version_count'] is! int ||
        plan['check_count'] is! int ||
        plan['expires_at'] is! num ||
        plan['items'] is! List ||
        plan['affected'] is! List ||
        !RegExp(r'^[0-9a-f]{64}$').hasMatch(token)) {
      throw const FormatException('Permanent delete scope response invalid');
    }
    for (final item in plan['items'] as List) {
      if (item is! Map ||
          item['id'] is! int ||
          item['id'] <= 0 ||
          item['version'] is! int ||
          item['version'] <= 0) {
        throw const FormatException('Delete item list invalid');
      }
    }
    if (sourceId <= 0 ||
        generation < 0 ||
        versions < 0 ||
        checks < 0 ||
        itemIds.toSet().length != itemIds.length) {
      throw const FormatException('Permanent delete scope response invalid');
    }
    for (final rule in plan['affected'] as List) {
      if (rule is! Map ||
          rule['id'] is! int ||
          rule['id'] <= 0 ||
          rule['revision'] is! int ||
          rule['revision'] <= 0 ||
          rule['remaining'] is! int ||
          rule['remaining'] < 0) {
        throw const FormatException('Affected rules list invalid');
      }
    }
  }
  int get sourceId => plan['source_id'] as int;
  int get generation => plan['generation'] as int;
  int get versions => plan['version_count'] as int;
  int get checks => plan['check_count'] as int;
  List<int> get itemIds =>
      (plan['items'] as List).map((v) => (v as Map)['id'] as int).toList();
  int get removedRules =>
      (plan['affected'] as List).where((v) => v['remaining'] == 0).length;
  int get pausedRules =>
      (plan['affected'] as List).where((v) => v['remaining'] != 0).length;
  Map<String, dynamic> get body => {
    'plan': plan,
    'token': token,
    'confirm': true,
  };
}

class SourcePurgeResult {
  final List<int> itemIds;
  final int generation;
  SourcePurgeResult.fromJson(Map<String, dynamic> value)
    : itemIds = (value['item_ids'] as List).cast<int>(),
      generation = value['generation'] as int;
}

/// The irreversible action requires a separate confirmation with actual impact counts.
class SourcePurgeDialog extends StatefulWidget {
  final SourcePurgePlan plan;
  final String title;
  const SourcePurgeDialog({super.key, required this.plan, required this.title});
  @override
  State<SourcePurgeDialog> createState() => _SourcePurgeDialogState();
}

class _SourcePurgeDialogState extends State<SourcePurgeDialog> {
  bool accepted = false;
  @override
  Widget build(BuildContext context) {
    final p = widget.plan;
    final l10n = AppLocalizations.of(context);
    return AlertDialog(
      title: Text(l10n.purgeTitle(widget.title)),
      content: SizedBox(
        width: 460,
        child: SingleChildScrollView(
          child: Column(
            mainAxisSize: MainAxisSize.min,
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              Text(l10n.purgeBody(p.itemIds.length, p.versions, p.checks)),
              const SizedBox(height: 12),
              if (p.removedRules > 0) Text(l10n.purgeRemovedRules(p.removedRules)),
              if (p.pausedRules > 0) Text(l10n.purgePausedRules(p.pausedRules)),
              Text(l10n.purgePreviewInvalidate),
              const SizedBox(height: 12),
              Text(l10n.purgeIrreversible),
              CheckboxListTile(
                contentPadding: EdgeInsets.zero,
                value: accepted,
                onChanged: (v) => setState(() => accepted = v ?? false),
                title: Text(l10n.purgeConfirmCheck),
              ),
            ],
          ),
        ),
      ),
      actions: [
        TextButton(
          onPressed: () => Navigator.pop(context, false),
          child: Text(l10n.actionCancel),
        ),
        FilledButton(
          style: FilledButton.styleFrom(
            backgroundColor: Theme.of(context).colorScheme.error,
          ),
          onPressed: accepted ? () => Navigator.pop(context, true) : null,
          child: Text(l10n.purgeForever),
        ),
      ],
    );
  }
}
