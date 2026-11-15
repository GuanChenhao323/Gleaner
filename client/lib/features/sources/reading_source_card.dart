import 'package:flutter/material.dart';

import '../../core/format.dart';
import '../../core/models.dart';
import 'reading_source.dart';

class ReadingSourceCard extends StatelessWidget {
  final ReadingSource source;
  final VoidCallback onCheck, onSettings, onDetails, onLogs, onPause, onOpen;
  const ReadingSourceCard({
    super.key,
    required this.source,
    required this.onCheck,
    required this.onSettings,
    required this.onDetails,
    required this.onLogs,
    required this.onPause,
    required this.onOpen,
  });
  @override
  Widget build(BuildContext context) {
    final s = source, cs = Theme.of(context).colorScheme;
    final warning =
        ![
          'not_executed',
          'verified',
          'changed',
          'unchanged',
        ].contains(s.result) ||
        s.capability == 'account_unknown';
    Widget meta(IconData icon, String text) => Row(
      mainAxisSize: MainAxisSize.min,
      children: [
        Icon(icon, size: 14, color: cs.onSurfaceVariant),
        const SizedBox(width: 4),
        Flexible(
          child: Text(
            text,
            style: TextStyle(fontSize: 12, color: cs.onSurfaceVariant),
          ),
        ),
      ],
    );
    return Card(
      margin: const EdgeInsets.only(bottom: 12),
      child: Padding(
        padding: const EdgeInsets.all(18),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Row(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Container(
                  padding: const EdgeInsets.all(11),
                  decoration: BoxDecoration(
                    color: cs.primaryContainer,
                    borderRadius: BorderRadius.circular(14),
                  ),
                  child: Icon(
                    s.platform == 'moodle'
                        ? Icons.school_outlined
                        : s.platform == 'student'
                        ? Icons.campaign_outlined
                        : s.platform == 'fie'
                        ? Icons.badge_outlined
                        : Icons.public,
                    color: cs.onPrimaryContainer,
                  ),
                ),
                const SizedBox(width: 13),
                Expanded(
                  child: Column(
                    crossAxisAlignment: CrossAxisAlignment.start,
                    children: [
                      Wrap(
                        spacing: 8,
                        runSpacing: 5,
                        crossAxisAlignment: WrapCrossAlignment.center,
                        children: [
                          Text(
                            s.title,
                            style: Theme.of(context).textTheme.titleSmall
                                ?.copyWith(fontWeight: FontWeight.w700),
                          ),
                          Text(
                            s.isPublic ? '公开' : '私人',
                            style: TextStyle(
                              fontSize: 12,
                              color: cs.onSurfaceVariant,
                            ),
                          ),
                        ],
                      ),
                      const SizedBox(height: 3),
                      Text(
                        s.url,
                        style: TextStyle(
                          fontSize: 12,
                          color: cs.onSurfaceVariant,
                        ),
                        maxLines: 2,
                        overflow: TextOverflow.ellipsis,
                      ),
                    ],
                  ),
                ),
              ],
            ),
            const SizedBox(height: 13),
            Wrap(
              spacing: 8,
              runSpacing: 7,
              crossAxisAlignment: WrapCrossAlignment.center,
              children: [
                const Text('提取条件', style: TextStyle(fontSize: 12)),
                Container(
                  padding: const EdgeInsets.symmetric(
                    horizontal: 9,
                    vertical: 4,
                  ),
                  decoration: BoxDecoration(
                    color: cs.surface,
                    borderRadius: BorderRadius.circular(7),
                  ),
                  child: Text(
                    s.query,
                    style: TextStyle(fontSize: 12, color: cs.primary),
                  ),
                ),
                Text(
                  s.scope,
                  style: TextStyle(fontSize: 12, color: cs.onSurfaceVariant),
                ),
              ],
            ),
            const SizedBox(height: 10),
            Wrap(
              spacing: 15,
              runSpacing: 9,
              children: [
                Text(
                  s.status,
                  style: TextStyle(
                    fontSize: 12,
                    fontWeight: FontWeight.w600,
                    color: warning ? cs.error : cs.primary,
                  ),
                ),
                meta(Icons.person_outline, s.identity),
                meta(
                  Icons.check_circle_outline,
                  '最后成功：${relative(tsToDate(s.lastSuccess?.toDouble()))}',
                ),
                meta(
                  Icons.history,
                  '最近尝试：${relative(tsToDate(s.lastAttempt?.toDouble()))}',
                ),
                meta(
                  Icons.inventory_2_outlined,
                  '${s.matchCount} ${s.isTimeline
                      ? '条活动摘要'
                      : s.platform == 'generic'
                      ? '个片段'
                      : '条匹配'} · ${s.items.length} 份资料',
                ),
              ],
            ),
            if (s.result == 'need_login' || s.result == 'account_mismatch')
              Padding(
                padding: const EdgeInsets.only(top: 12),
                child: Row(
                  children: [
                    Expanded(
                      child: Text(
                        s.result == 'need_login'
                            ? '请在原站重新登录；已有资料与成功记录保留。'
                            : '来源账号不符。回到原账号后重新测试，普通恢复不能解除绑定保护。',
                        style: TextStyle(fontSize: 12, color: cs.error),
                      ),
                    ),
                    TextButton(onPressed: onOpen, child: const Text('去原站登录')),
                  ],
                ),
              ),
            const SizedBox(height: 12),
            Divider(height: 1, color: cs.outlineVariant),
            const SizedBox(height: 9),
            Wrap(
              spacing: 12,
              runSpacing: 4,
              crossAxisAlignment: WrapCrossAlignment.center,
              children: [
                Text(
                  s.capability == 'account_unknown'
                      ? '仅当前页手动采集'
                      : !s.verified
                      ? '尚未验证后台重读'
                      : s.mode == 'manual'
                      ? '仅手动检查'
                      : s.paused
                      ? '定期检查已暂停'
                      : '每 ${s.interval ~/ 60} 分钟 · 下次约 ${relative(tsToDate(s.nextAt?.toDouble()))}',
                  style: TextStyle(fontSize: 11, color: cs.onSurfaceVariant),
                ),
                TextButton(
                  onPressed: onDetails,
                  child: Text(s.result == 'changed' ? '查看资料与变化' : '查看资料'),
                ),
                TextButton(onPressed: onLogs, child: const Text('检查日志')),
                TextButton(onPressed: onSettings, child: const Text('设置')),
                if (s.mode == 'periodic' && s.verified)
                  TextButton(
                    onPressed: s.active ? null : onPause,
                    child: Text(s.paused ? '恢复定期' : '暂停'),
                  ),
                if (s.verified)
                  OutlinedButton.icon(
                    onPressed: s.active ? null : onCheck,
                    icon: const Icon(Icons.refresh, size: 16),
                    label: Text(s.active ? '等待检查' : '立即检查'),
                  )
                else if (s.capability != 'account_unknown')
                  FilledButton.tonal(
                    onPressed: onSettings,
                    child: const Text('设置检查'),
                  ),
              ],
            ),
          ],
        ),
      ),
    );
  }
}
