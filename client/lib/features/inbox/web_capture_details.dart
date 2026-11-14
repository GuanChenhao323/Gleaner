import 'package:flutter/material.dart';

/// Shows source scope and evidence, without presenting fragments as full articles.
class WebCaptureDetails extends StatelessWidget {
  final Map<String, dynamic> capture;
  const WebCaptureDetails(this.capture, {super.key});

  @override
  Widget build(BuildContext context) {
    final binding = capture['source_binding'] as Map? ?? {};
    final fragments = capture['fragments'] as List? ?? [];
    return Card(
      child: Padding(
        padding: const EdgeInsets.all(16),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Text(
              '网页资料快照 · ${fragments.length} 个片段',
              style: Theme.of(context).textTheme.titleMedium,
            ),
            const SizedBox(height: 8),
            SelectableText(
              '条件：${capture['query']}\n匹配位置：${capture['match_scope'] == 'title' ? '标题与链接标题' : '正文与列表'}\n来源标签：${binding['label'] ?? '未提供'}',
            ),
            const Text('仅当前已加载内容，不代表完整文章或邮件。网站账号未经自动确认，来源标签由用户声明；未启用后台监测。'),
            const Text('同来源标签、URL、条件及范围，重新提取并明确保存后更新本资料版本。'),
            for (final entry in fragments.indexed)
              ExpansionTile(
                title: Text('片段 ${entry.$1 + 1}：${(entry.$2 as Map)['title']}'),
                children: [
                  Padding(
                    padding: const EdgeInsets.all(12),
                    child: SelectableText(
                      '${(entry.$2 as Map)['text']}\n\nDOM 依据：${((entry.$2 as Map)['evidence'] as Map?)?['locator'] ?? ''}',
                    ),
                  ),
                ],
              ),
          ],
        ),
      ),
    );
  }
}
