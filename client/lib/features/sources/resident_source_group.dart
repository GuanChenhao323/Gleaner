import 'package:flutter/material.dart';

import '../../core/format.dart';
import '../../core/models.dart';
import 'reading_source.dart';

/// A page owns one refresh plan; rules keep their own content and histories.
class ResidentSourceGroup extends StatelessWidget {
  final List<ReadingSource> rules;
  final Widget Function(ReadingSource) ruleCard;
  final VoidCallback onSettings, onCheck, onPause;
  const ResidentSourceGroup({
    super.key,
    required this.rules,
    required this.ruleCard,
    required this.onSettings,
    required this.onCheck,
    required this.onPause,
  });
  @override
  Widget build(BuildContext context) {
    final first = rules.first, cs = Theme.of(context).colorScheme;
    final active = rules.any((s) => s.active),
        verified = rules.every((s) => s.verified),
        paused = rules.any((s) => s.paused),
        online = rules.every((s) => s.deviceOnline);
    final scheduled = rules.any((s) => s.periodic);
    final next = rules.map((s) => s.nextAt).whereType<num>().toList()..sort();
    final successes = rules.map((s) => s.lastSuccess).whereType<num>().toList()
      ..sort();
    final issue = rules
        .where(
          (s) => ![
            'unchanged',
            'changed',
            'verified',
            'starting',
          ].contains(s.result),
        )
        .firstOrNull;
    final status = !online
        ? '等待本机Chrome执行'
        : active
        ? '正在启动／检查'
        : issue != null
        ? issue.status
        : paused
        ? (rules.every((s) => s.paused) ? '定期监测已暂停' : '部分规则已暂停')
        : verified
        ? (scheduled ? '定期监测中' : '仅手动检查')
        : '等待首次刷新';
    return Card(
      margin: const EdgeInsets.only(bottom: 16),
      child: Padding(
        padding: const EdgeInsets.all(18),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Row(
              children: [
                Icon(Icons.web, color: cs.primary),
                const SizedBox(width: 12),
                Expanded(
                  child: Column(
                    crossAxisAlignment: CrossAxisAlignment.start,
                    children: [
                      Text(
                        '${Uri.parse(first.url).host} · 专用监测页',
                        style: Theme.of(context).textTheme.titleMedium,
                      ),
                      const SizedBox(height: 4),
                      Text(
                        first.url,
                        maxLines: 2,
                        overflow: TextOverflow.ellipsis,
                        style: TextStyle(
                          fontSize: 12,
                          color: cs.onSurfaceVariant,
                        ),
                      ),
                    ],
                  ),
                ),
              ],
            ),
            const SizedBox(height: 12),
            Wrap(
              spacing: 12,
              runSpacing: 8,
              children: [
                Text(
                  status,
                  style: TextStyle(
                    fontWeight: FontWeight.w600,
                    color: issue != null ? cs.error : cs.primary,
                  ),
                ),
                Text(
                  '${rules.length} 条规则 · ${rules.every((s) => s.mode == 'manual') ? '仅手动检查' : '每${first.interval ~/ 60}分钟刷新一次'}',
                ),
                if (first.effectiveInterval != first.interval)
                  Text(
                    '本地夹具测试：每${first.effectiveInterval}秒',
                    style: TextStyle(color: cs.error),
                  ),
                const Text('同站点单会话 · 资料仅自己可见'),
                if (rules.any((s) => s.result == 'changed'))
                  const Text('发现来源变化 · 展开规则查看差异'),
              ],
            ),
            const SizedBox(height: 9),
            Wrap(
              spacing: 16,
              runSpacing: 6,
              children: [
                Text(
                  '最后成功：${successes.length == rules.length ? relative(tsToDate(successes.first.toDouble())) : '等待全部规则首次成功'}',
                  style: const TextStyle(fontSize: 12),
                ),
                Text(
                  '下次计划：${scheduled && next.isNotEmpty && next.first > 0 ? relative(tsToDate(next.first.toDouble())) : '待启动或恢复'}',
                  style: const TextStyle(fontSize: 12),
                ),
              ],
            ),
            const SizedBox(height: 8),
            Wrap(
              spacing: 6,
              runSpacing: 4,
              children: [
                for (final s in rules)
                  Chip(
                    label: Text(s.query, style: const TextStyle(fontSize: 12)),
                  ),
              ],
            ),
            Wrap(
              spacing: 8,
              children: [
                FilledButton.tonal(
                  onPressed: onSettings,
                  child: Text(verified ? '监测设置' : '启动／重新绑定'),
                ),
                if (verified)
                  TextButton.icon(
                    onPressed: active ? null : onCheck,
                    icon: const Icon(Icons.refresh, size: 17),
                    label: const Text('立即检查全部规则'),
                  ),
                if (rules.any((s) => s.mode == 'periodic') &&
                    (verified || !paused))
                  TextButton(
                    onPressed: onPause,
                    child: Text(paused ? '恢复定期' : '暂停定期'),
                  ),
              ],
            ),
            ExpansionTile(
              tilePadding: EdgeInsets.zero,
              title: Text('规则、资料与执行日志（${rules.length}）'),
              children: [for (final s in rules) ruleCard(s)],
            ),
            Text(
              '请保留专用监测标签页；检测到编辑会延后刷新。工作台网页可以关闭，本地服务需保持运行。',
              style: TextStyle(fontSize: 11, color: cs.onSurfaceVariant),
            ),
          ],
        ),
      ),
    );
  }
}
