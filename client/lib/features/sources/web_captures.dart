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
        '网页资料快照',
        style: TextStyle(fontWeight: FontWeight.bold, fontSize: 18),
      ),
      const Text('每组匹配是一份资料；重新提取并明确保存后更新版本，不自动监测。'),
      TextButton(
        onPressed: () => ref.invalidate(webCapturesProvider),
        child: const Text('刷新网页资料'),
      ),
      ref
          .watch(webCapturesProvider)
          .when(
            loading: () => const LinearProgressIndicator(),
            error: (e, _) => Text('网页资料读取失败：$e'),
            data: (rows) => Column(
              children: [
                if (rows.isEmpty) const Text('还没有网页资料。在普通网页输入条件、预览并保存后显示在这里。'),
                for (final r in rows)
                  Card(
                    child: ListTile(
                      leading: const Icon(Icons.article_outlined),
                      title: Text('${r['title']}'),
                      subtitle: Text(
                        '${r['url']}\n来源标签：${(r['source_binding'] as Map?)?['label'] ?? '未提供'} · ${r['fragment_count']} 个片段 · v${r['version']}',
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
