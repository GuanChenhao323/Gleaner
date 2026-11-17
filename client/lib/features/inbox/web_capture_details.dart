import 'package:flutter/material.dart';
import 'package:url_launcher/url_launcher.dart';

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
    final binding = capture['source_binding'] as Map? ?? {};
    final fragments = capture['fragments'] as List? ?? [];
    final timeline = capture['collection_type'] == 'timeline_summary';
    return Card(
      child: Padding(
        padding: const EdgeInsets.all(16),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Text(
              timeline
                  ? '活动摘要资料 · ${fragments.length} 条活动'
                  : '网页资料快照 · ${fragments.length} 个片段',
              style: Theme.of(context).textTheme.titleMedium,
            ),
            const SizedBox(height: 8),
            SelectableText(
              timeline
                  ? '条件：${capture['query']}\n来源身份：原学校账号 · 本机 Chrome\n范围：当前已加载 Timeline 活动'
                  : '条件：${capture['query']}\n匹配位置：${capture['match_scope'] == 'title' ? '标题与链接标题' : '正文与列表'}\n来源别名：${binding['label'] ?? '未提供'}\n原站登录要求：${binding['kind'] == 'public' ? '无需登录（用户声明）' : '需要登录'}\n来源账号：${binding['identity'] is Map ? (binding['identity'] as Map)['display'] : '未核对'}\n资料可见：仅自己',
            ),
            Text(
              timeline
                  ? '这是活动提醒摘要，未读取详情正文，不代表完整作业或已确认的日历事件。日期和时间均保留原文，缺失时不推测。'
                  : hasReadingSource
                  ? '仅约定视图中的匹配片段，不代表完整文章或邮件。原条件已关联信息源，检查方式与状态请在来源中查看。'
                  : '仅当前已加载内容，不代表完整文章或邮件。来源别名由用户声明；来源检查未启用，账号证明与后台能力须分别核对。',
            ),
            Text(
              hasReadingSource
                  ? '检查成功且内容变化时更新同一资料的来源版本，个人备注与状态保留。'
                  : '同来源标签、URL、条件及范围，重新提取并明确保存后更新本资料版本。',
            ),
            for (final entry in fragments.indexed)
              ExpansionTile(
                title: Text(
                  '${timeline ? '活动' : '片段'} ${entry.$1 + 1}：${(entry.$2 as Map)['title']}',
                ),
                children: [
                  if (timeline)
                    Padding(
                      padding: const EdgeInsets.all(12),
                      child: SelectableText(
                        '课程：${((entry.$2 as Map)['fields'] as Map?)?['course'] ?? ''}\n日期原文：${((entry.$2 as Map)['fields'] as Map?)?['date_text'] ?? ''}\n时间原文：${((entry.$2 as Map)['fields'] as Map?)?['datetime_text'] ?? ''}',
                      ),
                    ),
                  Padding(
                    padding: const EdgeInsets.all(12),
                    child: SelectableText(
                      '${(entry.$2 as Map)['text']}\n\nDOM 依据：${((entry.$2 as Map)['evidence'] as Map?)?['locator'] ?? ''}',
                    ),
                  ),
                  if (timeline)
                    TextButton.icon(
                      onPressed: () =>
                          launchUrl(Uri.parse('${(entry.$2 as Map)['url']}')),
                      icon: const Icon(Icons.open_in_new),
                      label: const Text('打开活动详情'),
                    ),
                ],
              ),
          ],
        ),
      ),
    );
  }
}
