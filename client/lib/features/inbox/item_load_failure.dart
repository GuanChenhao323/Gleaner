import 'package:flutter/material.dart';

import '../../core/api.dart';
import '../../l10n/app_localizations.dart';
import '../../widgets/common.dart';

/// Keep transport/ownership failure feedback separate from item rendering.
class ItemLoadFailure extends StatelessWidget {
  final Object? error;
  final String email;
  final VoidCallback onRetry;
  final VoidCallback onSources;

  const ItemLoadFailure({
    super.key,
    required this.error,
    required this.email,
    required this.onRetry,
    required this.onSources,
  });

  @override
  Widget build(BuildContext context) {
    final l10n = AppLocalizations.of(context);
    final status = error is ApiException
        ? (error as ApiException).status
        : null;
    final message = switch (status) {
      404 => l10n.itemNotFound,
      401 => l10n.loginExpired,
      _ => l10n.detailLoadFailed,
    };
    return EmptyState(
      icon: Icons.info_outline,
      title: l10n.cannotOpenItem,
      message: '$message\n${l10n.currentDeskAccount(email.isEmpty ? l10n.notSignedIn : email)}',
      action: Wrap(
        spacing: 8,
        children: [
          OutlinedButton(onPressed: onRetry, child: Text(l10n.retry)),
          TextButton(onPressed: onSources, child: Text(l10n.backToSources)),
        ],
      ),
    );
  }
}
