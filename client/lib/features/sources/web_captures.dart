import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:go_router/go_router.dart';

import '../../core/session.dart';

final webCapturesProvider = FutureProvider<List<Map<String, dynamic>>>(
  (ref) => ref.watch(apiProvider).webCaptures(),
);

class WebCapturesPanel extends ConsumerWidget {
  const WebCapturesPanel({super.key});
  @override
  Widget build(BuildContext context, WidgetRef ref) => Column(
    crossAxisAlignment: CrossAxisAlignment.start,
    children: [
      const SizedBox(height: 16),
      const Text(
        'Web clip snapshots',
        style: TextStyle(fontWeight: FontWeight.bold, fontSize: 18),
      ),
      const Text('Each match group is one doc; recapture and explicitly save to update versions. No auto-monitor.'),
      TextButton(
        onPressed: () => ref.invalidate(webCapturesProvider),
        child: const Text('Refresh web clips'),
      ),
      ref
          .watch(webCapturesProvider)
          .when(
            loading: () => const LinearProgressIndicator(),
            error: (e, _) => Text('Could not read web clips: $e'),
            data: (rows) => Column(
              children: [
                if (rows.isEmpty) const Text('No web clips yet. Enter a query on a normal page, preview, and save to see them here.'),
                for (final r in rows)
                  Card(
                    child: ListTile(
                      leading: const Icon(Icons.article_outlined),
                      title: Text('${r['title']}'),
                      subtitle: Text(
                        '${r['url']}\nSource label: ${(r['source_binding'] as Map?)?['label'] ?? 'not provided'} · ${r['fragment_count']}  fragments · v${r['version']}',
                      ),
                      isThreeLine: true,
                      trailing: const Icon(Icons.chevron_right),
                      onTap: () => context.push('/item/${r['id']}'),
                    ),
                  ),
              ],
            ),
          ),
    ],
  );
}
