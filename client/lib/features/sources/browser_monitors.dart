import 'dart:async';

import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:go_router/go_router.dart';

import '../../core/format.dart';
import '../../core/models.dart';
import '../../core/providers.dart';
import '../../core/session.dart';
import '../../l10n/app_localizations.dart';

String browserCheckLabel(String result, BuildContext context) {
  final l10n = AppLocalizations.of(context);
  return switch (result) {
    'not_executed' => l10n.bcNotExecuted,
    'unchanged' => l10n.bcUnchanged,
    'changed' => l10n.bcChanged,
    'need_login' => l10n.bcNeedLogin,
    'account_mismatch' => l10n.bcAccountMismatch,
    'selection_missing' => l10n.bcSelectionMissing,
    'view_mismatch' => l10n.bcViewMismatch,
    'route_mismatch' => l10n.bcRouteMismatch,
    'render_timeout' => l10n.bcRenderTimeout,
    'permission_denied' => l10n.bcPermissionDenied,
    'unsupported' => l10n.bcUnsupported,
    _ => l10n.bcFailed,
  };
}

class BrowserMonitorsPanel extends ConsumerStatefulWidget {
  const BrowserMonitorsPanel({super.key});
  @override
  ConsumerState<BrowserMonitorsPanel> createState() =>
      _BrowserMonitorsPanelState();
}

class _BrowserMonitorsPanelState extends ConsumerState<BrowserMonitorsPanel> {
  List<Map<String, dynamic>> rows = [];
  String? error;
  Timer? timer;
  bool loading = false;
  @override
  void initState() {
    super.initState();
    Future.microtask(load);
    timer = Timer.periodic(const Duration(seconds: 15), (_) => load());
  }

  @override
  void dispose() {
    timer?.cancel();
    super.dispose();
  }

  Future<void> load() async {
    if (loading || !mounted) return;
    loading = true;
    final api = ref.read(apiProvider);
    try {
      final next = await api.browserMonitors();
      if (mounted && identical(api, ref.read(apiProvider))) {
        setState(() {
          rows = next;
          error = null;
        });
      }
    } catch (e) {
      if (mounted && identical(api, ref.read(apiProvider))) {
        setState(() => error = '$e');
      }
    } finally {
      loading = false;
      if (mounted && !identical(api, ref.read(apiProvider))) {
        Future.microtask(load);
      }
    }
  }

  Future<void> act(Future<void> Function() operation) async {
    try {
      await operation();
      await load();
      ref.invalidate(sourcesProvider);
    } catch (e) {
      if (mounted) setState(() => error = '$e');
    }
  }

  @override
  Widget build(BuildContext context) {
    ref.listen(apiProvider, (_, _) {
      rows = [];
      Future.microtask(load);
    });
    final api = ref.read(apiProvider);
    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        const Text(
          'Saved browser sources',
          style: TextStyle(fontWeight: FontWeight.bold, fontSize: 18),
        ),
        const Text('Reading ≠ saving. Only saved item sources are listed; snapshot save does not enable background checks.'),
        Wrap(
          spacing: 8,
          children: [
            TextButton(onPressed: load, child: const Text('Refresh capture sources')),
          ],
        ),
        if (error != null)
          Text(
            'Could not read capture sources: $error',
            style: TextStyle(color: Theme.of(context).colorScheme.error),
          ),
        for (final m in rows)
          Card(
            child: Padding(
              padding: const EdgeInsets.all(12),
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  Text(
                    '${m['title'] ?? 'Saved source'}',
                    style: const TextStyle(fontWeight: FontWeight.bold),
                  ),
                  SelectableText('${(m['recipe'] as Map)['url']}'),
                  Text(
                    m['supported'] != true
                        ? 'Saved only · monitoring not supported'
                        : '${m['enabled'] == true ? 'Enabled' : 'Paused'} · ${browserCheckLabel('${m['last_result']}', context)}',
                  ),
                  Text('Last successful check: ${relative(tsToDate(m['last_success_at']), context)}'),
                  if ('${m['error']}'.isNotEmpty)
                    Text(browserCheckLabel('${m['error']}', context)),
                  Wrap(
                    spacing: 8,
                    children: [
                      TextButton(
                        onPressed: () => context.push('/item/${m['item_id']}'),
                        child: const Text('View item & changes'),
                      ),
                      if (m['supported'] == true &&
                          m['last_result'] != 'account_mismatch') ...[
                        TextButton(
                          onPressed: () => act(
                            () => api.browserControl(
                              m['id'] as int,
                              m['revision'] as int,
                              m['enabled'] != true,
                            ),
                          ),
                          child: Text(m['enabled'] == true ? 'Pause' : 'Resume'),
                        ),
                        if (m['enabled'] == true)
                          TextButton(
                            onPressed: () =>
                                act(() => api.browserCheck(m['id'] as int)),
                            child: const Text('Check now'),
                          ),
                      ],
                      TextButton(
                        onPressed: () =>
                            act(() => api.browserRemove(m['id'] as int)),
                        child: const Text('Stop monitoring, keep items'),
                      ),
                    ],
                  ),
                ],
              ),
            ),
          ),
        const Divider(),
      ],
    );
  }
}
