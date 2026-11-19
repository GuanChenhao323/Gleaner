import 'dart:convert';

import 'package:flutter/material.dart';

import '../../l10n/app_localizations.dart';

/// Source changes remain separate from personal notes and deadline overrides.
class SourceChanges extends StatelessWidget {
  final Map<String, dynamic> changed;
  const SourceChanges(this.changed, {super.key});

  String value(Object? v, AppLocalizations l10n) => v == null
      ? l10n.notProvided
      : v is Map || v is List
      ? const JsonEncoder.withIndent('  ').convert(v)
      : '$v';

  @override
  Widget build(BuildContext context) {
    final l10n = AppLocalizations.of(context);
    final labels = {
      'body': l10n.originalContent,
      'title': l10n.fieldTitle,
      'deadline_at': l10n.sourceDeadline,
      'requirements': l10n.submitRequirements,
      'source_fields': l10n.sourceFields,
    };
    return Column(
      children: [
        for (final entry in changed.entries)
          if (entry.value is List && (entry.value as List).length == 2)
            ExpansionTile(
              title: Text(labels[entry.key] ?? entry.key),
              children: [
                Padding(
                  padding: const EdgeInsets.all(8),
                  child: Align(
                    alignment: Alignment.centerLeft,
                    child: SelectableText(
                      l10n.beforeChange(value((entry.value as List)[0], l10n)),
                      style: TextStyle(
                        color: Theme.of(context).colorScheme.error,
                      ),
                    ),
                  ),
                ),
                Padding(
                  padding: const EdgeInsets.all(8),
                  child: Align(
                    alignment: Alignment.centerLeft,
                    child: SelectableText(
                      l10n.afterChange(value((entry.value as List)[1], l10n)),
                      style: TextStyle(
                        color: Theme.of(context).colorScheme.primary,
                      ),
                    ),
                  ),
                ),
              ],
            ),
      ],
    );
  }
}
