import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:url_launcher/url_launcher.dart';

import '../../core/api.dart';
import '../../core/format.dart';
import '../../core/models.dart';
import '../../core/providers.dart';
import '../../core/session.dart';
import '../../core/store.dart';
import '../../widgets/common.dart';

import 'package:go_router/go_router.dart';

import 'reading_source.dart';
import 'source_purge.dart';
import 'reading_source_card.dart';
import 'resident_source_group.dart';
import 'campus_source_entries.dart';

class SourcesPage extends ConsumerWidget {
  const SourcesPage({super.key});
  Future<void> _act(
    BuildContext context,
    Future<void> Function() action,
    String message,
  ) async {
    try {
      await action();
      if (context.mounted && message.isNotEmpty) toast(context, message);
    } catch (e) {
      if (context.mounted) toast(context, '$e', error: true);
    }
  }

  Future<void> _remove(
    BuildContext context,
    WidgetRef ref,
    ReadingSource source,
  ) async {
    bool trashItems = false;
    final confirmed = await showDialog<bool>(
      context: context,
      builder: (c) => StatefulBuilder(
        builder: (c, update) => AlertDialog(
          title: const Text('删除信息源？'),
          content: Column(
            mainAxisSize: MainAxisSize.min,
            children: [
              const Text('停止此来源的手动和定期检查。默认保留已保存资料、备注及历史版本。可从“已删除来源”手动恢复；旧任务不会自动恢复。'),
              CheckboxListTile(
                value: trashItems,
                onChanged: (v) => update(() => trashItems = v ?? false),
                title: const Text('同时将关联资料移入个人回收站'),
                subtitle: const Text('也会在引用这些资料的其他来源中隐藏；可从收件箱回收站恢复。'),
              ),
            ],
          ),
          actions: [
            TextButton(
              onPressed: () => Navigator.pop(c, false),
              child: const Text('取消'),
            ),
            FilledButton(
              onPressed: () => Navigator.pop(c, true),
              child: const Text('删除来源'),
            ),
          ],
        ),
      ),
    );
    if (confirmed != true || !context.mounted) return;
    await _act(context, () async {
      await ref
          .read(readingSourcesProvider.notifier)
          .remove(source, trashItems);
      await ref.read(feedProvider.notifier).refreshAll();
      ref.invalidate(sourcesProvider);
      ref.invalidate(legacyCapturesProvider);
      ref.invalidate(deletedReadingSourcesProvider);
    }, trashItems ? '来源已删除，关联资料已移入回收站。' : '来源已删除，资料与历史保留。');
  }

  Future<void> _purge(
    BuildContext context,
    WidgetRef ref,
    Map<String, dynamic> source,
  ) async {
    await _act(context, () async {
      final repo = ref.read(readingRepositoryProvider);
      final plan = await repo.purgePreview(source['id'] as int);
      if (!context.mounted) return;
      final confirmed = await showDialog<bool>(
        context: context,
        builder: (c) => SourcePurgeDialog(
          plan: plan,
          title: '${(source['recipe'] as Map)['query']}',
        ),
      );
      if (confirmed != true || !context.mounted) return;
      if (!identical(repo, ref.read(readingRepositoryProvider))) {
        throw StateError("工作台账号已变化，请重新确认。");
      }
      final result = await repo.purge(plan);
      if (!identical(repo, ref.read(readingRepositoryProvider))) return;
      String? cleanupError;
      try {
        await ref
            .read(feedProvider.notifier)
            .forgetPermanently(result.itemIds, result.generation);
      } catch (e) {
        cleanupError = '$e';
      }
      for (final id in result.itemIds) {
        ref.invalidate(versionsProvider(id));
      }
      ref.invalidate(deletedReadingSourcesProvider);
      ref.invalidate(sourcesProvider);
      ref.invalidate(legacyCapturesProvider);
      await ref.read(readingSourcesProvider.notifier).refresh();
      if (context.mounted) {
        toast(
          context,
          cleanupError == null
              ? '来源、关联资料与历史已彻底删除。请重新提取后保存。'
              : '服务器已彻底删除；本机缓存清理待重试：$cleanupError',
          error: cleanupError != null,
        );
      }
    }, '');
  }

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final deleted = ref.watch(deletedReadingSourcesProvider);
    final data = ref.watch(readingSourcesProvider),
        legacy = ref.watch(sourcesProvider),
        captures = ref.watch(legacyCapturesProvider);
    void refresh() {
      ref.read(readingSourcesProvider.notifier).refresh().catchError((
        Object e,
      ) {
        if (context.mounted) toast(context, '状态刷新失败：$e', error: true);
      });
      ref.invalidate(sourcesProvider);
      ref.invalidate(legacyCapturesProvider);
      ref.invalidate(deletedReadingSourcesProvider);
    }

    return Scaffold(
      appBar: AppBar(
        actions: [
          IconButton(
            tooltip: '刷新列表状态（不访问来源网页）',
            icon: const Icon(Icons.refresh),
            onPressed: refresh,
          ),
          Padding(
            padding: const EdgeInsets.only(right: 16),
            child: FilledButton.tonalIcon(
              onPressed: () => showModalBottomSheet<void>(
                context: context,
                isScrollControlled: true,
                builder: (c) => const FractionallySizedBox(
                  heightFactor: .88,
                  child: SingleChildScrollView(
                    padding: EdgeInsets.all(24),
                    child: CampusSourceEntries(),
                  ),
                ),
              ),
              icon: const Icon(Icons.add),
              label: const Text('从网页采集'),
            ),
          ),
        ],
      ),
      body: data.when(
        loading: () => const Center(child: CircularProgressIndicator()),
        error: (e, _) => EmptyState(
          icon: Icons.cloud_off,
          title: '无法读取信息源',
          message: '$e',
          action: OutlinedButton(onPressed: refresh, child: const Text('重试')),
        ),
        data: (rows) {
          final linked = rows
              .expand((s) => s.items)
              .map((i) => i['id'])
              .toSet();
          final controller = ref.read(readingSourcesProvider.notifier),
              cs = Theme.of(context).colorScheme;
          Widget metric(String value, String label) => Column(
            children: [
              Text(
                value,
                style: Theme.of(context).textTheme.headlineSmall
                    ?.copyWith(color: cs.primary),
              ),
              Text(
                label,
                style: TextStyle(fontSize: 12, color: cs.onSurfaceVariant),
              ),
            ],
          );
          final oldCaptures = (captures.value ?? <Map<String, dynamic>>[])
              .where((r) => !linked.contains(r['item_id']))
              .toList();
          final oldSources = (legacy.value ?? <Source>[])
              .where((s) => s.type != 'browser')
              .toList();
          final groups = <String, List<ReadingSource>>{};
          for (final s in rows) {
            groups.putIfAbsent(s.pageId ?? 'legacy-${s.id}', () => []).add(s);
          }
          Widget ruleCard(ReadingSource s) =>
                ReadingSourceCard(
                  source: s,
                  onCheck: () => _act(
                    context,
                    () => controller.check(s, 'check'),
                    '检查已排队；结果确认后更新状态。',
                  ),
                  onSettings: () => context.push('/sources/${s.id}/settings'),
                  onDetails: () => context.push('/sources/${s.id}${s.result=='changed'?'?tab=changes':''}'),
                  onLogs: () => context.push('/sources/${s.id}/checks'),
                  onPause: () => _act(
                    context,
                    () =>
                        controller.configure(s, s.settings(paused: !s.paused)),
                    s.paused ? '定期检查已恢复。' : '定期检查已暂停，仍可手动检查。',
                  ),
                  onOpen: () => launchUrl(Uri.parse(s.url)),
                  onDelete: () => _remove(context, ref, s),
                );
          return ListView(
            padding: const EdgeInsets.fromLTRB(24, 8, 24, 40),
            children: [
              if (rows.isNotEmpty) ...[
                Text(
                  rows.any((s) => s.deviceOnline)
                      ? '本机 Chrome 近期已连接 · 原站登录状态逐来源检查'
                      : '尚未检测到执行设备近期连接 · 保留上次成功结果',
                  style: TextStyle(fontSize: 12, color: cs.onSurfaceVariant),
                ),
                const SizedBox(height: 17),
              ],
              Card(
                child: Padding(
                  padding: const EdgeInsets.symmetric(
                    vertical: 18,
                    horizontal: 8,
                  ),
                  child: LayoutBuilder(
                    builder: (context, c) => Wrap(
                      alignment: WrapAlignment.spaceAround,
                      spacing: 16,
                      runSpacing: 14,
                      children: [
                        metric('${groups.length}', '已保存页面'),
                        metric(
                          '${rows.where((s) => s.periodic).length}',
                          '定期规则',
                        ),
                        metric(
                          '${rows.where((s) => !['not_executed', 'verified', 'unchanged', 'changed', 'starting', 'user_busy'].contains(s.result) || s.capability == 'account_unknown').length}',
                          '需要处理',
                        ),
                        metric(
                          '${rows.where((s) => s.result == 'changed').length}',
                          '本次发现变化',
                        ),
                      ],
                    ),
                  ),
                ),
              ),
              const SizedBox(height: 16),
              Text('我的信息源', style: Theme.of(context).textTheme.titleMedium),
              const SizedBox(height: 10),
              if (rows.isEmpty)
                const Padding(
                  padding: EdgeInsets.symmetric(vertical: 24),
                  child: Text('还没有保留原条件的信息源。请在原网页通过插件提取、预览并保存。'),
                ),
              for (final group in groups.values)
                if (group.first.resident)
                  ResidentSourceGroup(
                    rules: group,
                    ruleCard: ruleCard,
                    onSettings: () =>
                        context.push('/sources/${group.first.id}/settings'),
                    onCheck: () => _act(
                      context,
                      () => controller.check(group.first, 'check'),
                      '整页检查已排队；同页规则共享刷新。',
                    ),
                    onPause: () => _act(
                      context,
                      () => controller.configure(
                        group.first,
                        group.first.settings(
                          paused: !group.any((s) => s.paused),
                        ),
                      ),
                      '整页监测计划已更新。',
                    ),
                  )
                else
                  ruleCard(group.first),
              const Padding(
                padding: EdgeInsets.symmetric(vertical: 12),
                child: Text(
                  '专用监测标签页需要保持打开；可以关闭工作台页面。请保持Chrome、扩展和本地服务运行，检查可能延后。',
                  style: TextStyle(fontSize: 12),
                ),
              ),
              deleted.when(
                loading: () => const LinearProgressIndicator(),
                error: (e, _) => Text('已删除来源暂不可用：$e'),
                data: (values) => ExpansionTile(
                  title: Text('已删除来源（${values.length}）'),
                  subtitle: const Text('恢复后保持暂停；彻底删除会永久清除关联资料与历史。'),
                  children: [
                    for (final value in values)
                      ListTile(
                        title: Text('${(value['recipe'] as Map)['query']}'),
                        subtitle: Column(
                          crossAxisAlignment: CrossAxisAlignment.start,
                          children: [
                            const Text('检查已停止 · 资料与历史按原选择保留'),
                            Wrap(
                              spacing: 12,
                              children: [
                                TextButton.icon(
                                  icon: const Icon(Icons.restore),
                                  label: const Text('恢复来源'),
                                  onPressed: () => _act(
                                    context,
                                    () => controller.restore(
                                      value['id'] as int,
                                      value['revision'] as int,
                                    ),
                                    '来源已恢复并暂停；请重新测试重读。',
                                  ),
                                ),
                                TextButton.icon(
                                  style: TextButton.styleFrom(
                                    foregroundColor: cs.error,
                                  ),
                                  icon: const Icon(Icons.delete_forever),
                                  label: const Text('彻底删除'),
                                  onPressed: () => _purge(context, ref, value),
                                ),
                              ],
                            ),
                          ],
                        ),
                      ),
                  ],
                ),
              ),
              if (oldCaptures.isNotEmpty ||
                  oldSources.isNotEmpty ||
                  captures.hasError)
                ExpansionTile(
                  tilePadding: EdgeInsets.zero,
                  title: const Text('旧资料与演示订阅'),
                  subtitle: const Text('保留已有数据；缺少原条件时请打开原网页重新采集。'),
                  children: [
                    if (captures.hasError) Text('旧资料读取失败：${captures.error}'),
                    for (final r in oldCaptures)
                      Card(
                        child: ListTile(
                          leading: const Icon(Icons.inventory_2_outlined),
                          title: Text('${r['title']}'),
                          subtitle: Text('${r['url']}\n旧采集资料 · 未自动迁入条件监测'),
                          onTap: () => context.push('/item/${r['item_id']}'),
                        ),
                      ),
                    for (final s in oldSources) _SourceCard(s),
                    TextButton(
                      onPressed: () => showAddSource(context, ref),
                      child: const Text('管理旧模板／演示来源'),
                    ),
                  ],
                ),
            ],
          );
        },
      ),
    );
  }
}

final legacyCapturesProvider = FutureProvider<List<Map<String, dynamic>>>((
  ref,
) async {
  final api = ref.watch(apiProvider);
  final results = await Future.wait([api.browserMonitors(), api.webCaptures()]);
  return [
    ...results[0],
    ...results[1].map((r) => {...r, 'item_id': r['id']}),
  ];
});

class _SourceCard extends ConsumerWidget {
  final Source s;
  const _SourceCard(this.s);

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final t = Theme.of(context);
    final cs = t.colorScheme;
    final api = ref.read(apiProvider);
    return Card(
      child: Padding(
        padding: const EdgeInsets.fromLTRB(16, 14, 8, 10),
        child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
          Row(children: [
            Container(
              padding: const EdgeInsets.all(10),
              decoration: BoxDecoration(color: cs.primaryContainer, borderRadius: BorderRadius.circular(14)),
              child: Icon(sourceIcon(s.type), color: cs.onPrimaryContainer),
            ),
            const SizedBox(width: 14),
            Expanded(
              child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
                Row(children: [
                  Flexible(child: Text(s.name, style: t.textTheme.titleSmall?.copyWith(fontWeight: FontWeight.w700), overflow: TextOverflow.ellipsis)),
                  const SizedBox(width: 8),
                  if (s.shared) Pill('公共', color: cs.outline),
                  if (s.viaAgent) Pill('本地代理', color: cs.tertiary, icon: Icons.computer),
                  if (s.muted) Pill('已静音', color: cs.outline, icon: Icons.notifications_off),
                ]),
                const SizedBox(height: 2),
                Text(s.endpoint, maxLines: 1, overflow: TextOverflow.ellipsis, style: t.textTheme.bodySmall?.copyWith(color: cs.onSurfaceVariant)),
              ]),
            ),
            PopupMenuButton<String>(
              onSelected: (v) async {
                try {
                  if (v == 'refresh') {
                    final r = await api.refreshSource(s.id);
                    if (context.mounted) toast(context, r['checking'] == false ? (r['message'] ?? '已排队，稍后检查').toString() : '已加入检查队列');
                  } else if (v == 'login') {
                    if (context.mounted) await showLogin(context, ref, s);
                  } else if (v == 'mute') {
                    await api.updateSource(s.id, {'muted': !s.muted});
                  } else if (v == 'weight') {
                    if (context.mounted) await _weight(context, ref, s);
                  } else if (v == 'delete') {
                    final ok = await showDialog<bool>(
                      context: context,
                      builder: (c) => AlertDialog(
                        title: Text('取消订阅「${s.name}」？'),
                        content: Text(s.shared ? '公共来源仍会为其他同学保留。' : '该来源及其登录会话会被删除。'),
                        actions: [TextButton(onPressed: () => Navigator.pop(c, false), child: const Text('取消')), FilledButton(onPressed: () => Navigator.pop(c, true), child: const Text('删除'))],
                      ),
                    );
                    if (ok == true) await api.removeSource(s.id);
                  }
                } on ApiException catch (e) {
                  if (context.mounted) toast(context, e.message, error: true);
                }
                ref.invalidate(sourcesProvider);
              },
              itemBuilder: (_) => [
                const PopupMenuItem(value: 'refresh', child: ListTile(leading: Icon(Icons.sync), title: Text('立即检查'))),
                if (s.type == 'moodle' || s.isMail) PopupMenuItem(value: 'login', child: ListTile(leading: const Icon(Icons.login), title: Text(s.hasLogin ? '重新登录' : '登录'))),
                PopupMenuItem(value: 'mute', child: ListTile(leading: Icon(s.muted ? Icons.notifications : Icons.notifications_off_outlined), title: Text(s.muted ? '取消静音' : '静音'))),
                const PopupMenuItem(value: 'weight', child: ListTile(leading: Icon(Icons.tune), title: Text('调整重要程度'))),
                const PopupMenuItem(value: 'delete', child: ListTile(leading: Icon(Icons.delete_outline), title: Text('取消订阅'))),
              ],
            ),
          ]),
          const SizedBox(height: 12),
          Wrap(spacing: 10, runSpacing: 8, crossAxisAlignment: WrapCrossAlignment.center, children: [
            SourceStatusPill(s),
            _meta(context, Icons.check_circle_outline, '最后成功：${relative(tsToDate(s.lastSuccessAt))}'),
            _meta(context, Icons.update, '最后检查：${relative(tsToDate(s.lastCheckedAt))}'),
            _meta(context, Icons.inventory_2_outlined, '${s.itemCount} 条事项'),
            if (s.savedRatio != null) _meta(context, Icons.savings_outlined, '304 命中 ${(s.savedRatio! * 100).round()}%'),
          ]),
          if (s.needsLogin) ...[
            const SizedBox(height: 12),
            Container(
              padding: const EdgeInsets.all(12),
              decoration: BoxDecoration(color: cs.tertiaryContainer, borderRadius: BorderRadius.circular(14)),
              child: Row(children: [
                Icon(Icons.lock_clock, color: cs.onTertiaryContainer),
                const SizedBox(width: 10),
                Expanded(child: Text(s.hasLogin ? '登录会话已失效，暂停检查以免反复请求。' : '登录一次即可开始检查；平台只保存会话，不保存统一认证密码。', style: TextStyle(color: cs.onTertiaryContainer))),
                FilledButton.tonal(onPressed: () => showLogin(context, ref, s), child: Text(s.hasLogin ? '重新登录' : '登录')),
              ]),
            ),
          ] else if (s.status == 'failed' && (s.lastError ?? '').isNotEmpty) ...[
            const SizedBox(height: 10),
            Text('最近错误：${s.lastError}', style: TextStyle(color: cs.error, fontSize: 12)),
          ],
        ]),
      ),
    );
  }

  Widget _meta(BuildContext context, IconData i, String text) {
    final cs = Theme.of(context).colorScheme;
    return Row(mainAxisSize: MainAxisSize.min, children: [
      Icon(i, size: 14, color: cs.onSurfaceVariant),
      const SizedBox(width: 4),
      Text(text, style: TextStyle(fontSize: 12, color: cs.onSurfaceVariant)),
    ]);
  }

  Future<void> _weight(BuildContext context, WidgetRef ref, Source s) async {
    var v = s.weight;
    final ok = await showDialog<bool>(
      context: context,
      builder: (c) => StatefulBuilder(
        builder: (c, set) => AlertDialog(
          title: const Text('重要程度'),
          content: Column(mainAxisSize: MainAxisSize.min, crossAxisAlignment: CrossAxisAlignment.start, children: [
            const Text('权重越高，这个来源的事项越容易被判为紧急并推送到手机。'),
            Slider(value: v, divisions: 10, label: v.toStringAsFixed(1), onChanged: (x) => set(() => v = x)),
          ]),
          actions: [TextButton(onPressed: () => Navigator.pop(c, false), child: const Text('取消')), FilledButton(onPressed: () => Navigator.pop(c, true), child: const Text('保存'))],
        ),
      ),
    );
    if (ok == true) await ref.read(apiProvider).updateSource(s.id, {'weight': v});
  }
}

Future<void> showLogin(BuildContext context, WidgetRef ref, Source s) async {
  final user = TextEditingController();
  final pw = TextEditingController();
  final smtpHost = TextEditingController();
  final smtpPort = TextEditingController(text: '587');
  final key = TextEditingController();
  // Moodle 默认用安全密钥：学校多为统一认证（CAS / SSO），账号密码换不到 token
  final isMoodle = s.type == 'moodle';
  var useKey = isMoodle;
  var busy = false;
  String? err;
  await showDialog<void>(
    context: context,
    builder: (c) => StatefulBuilder(
      builder: (c, set) => AlertDialog(
        title: Text('登录「${s.name}」'),
        content: SizedBox(
          width: 380,
          child: Column(mainAxisSize: MainAxisSize.min, crossAxisAlignment: CrossAxisAlignment.stretch, children: [
            if (isMoodle) ...[
              SegmentedButton<bool>(
                segments: const [
                  ButtonSegment(value: true, label: Text('粘贴安全密钥'), icon: Icon(Icons.key_outlined)),
                  ButtonSegment(value: false, label: Text('账号密码'), icon: Icon(Icons.password)),
                ],
                selected: {useKey},
                onSelectionChanged: busy
                    ? null
                    : (v) => set(() {
                          useKey = v.first;
                          err = null;
                        }),
              ),
              const SizedBox(height: 12),
            ],
            Text(
              useKey
                  ? '学校使用统一认证时用这种方式，拾课不会接触你的统一认证密码：\n'
                      '1. 在浏览器登录 Moodle，打开“偏好设置 → 安全密钥”；\n'
                      '2. 复制“Moodle mobile web service”那一行的密钥，粘贴到下面。\n'
                      '密钥以 AES-GCM 加密保存；在 Moodle 里重置密钥即可随时撤销。'
                  : s.isMail
                      ? '使用邮箱的“应用专用密码”。口令会以 AES-GCM 加密保存，用于 IMAP/SMTP 连接。'
                      : '账号密码只用于这一次登录，平台只加密保存登录后得到的会话，不保存密码。',
              style: TextStyle(color: Theme.of(c).colorScheme.onSurfaceVariant),
            ),
            const SizedBox(height: 16),
            if (useKey) ...[
              OutlinedButton.icon(
                onPressed: () => launchUrl(Uri.parse(s.endpoint).resolve('/user/managetoken.php')),
                icon: const Icon(Icons.open_in_new),
                label: const Text('打开 Moodle 安全密钥页面'),
              ),
              const SizedBox(height: 12),
              TextField(
                controller: key,
                autocorrect: false,
                enableSuggestions: false,
                decoration: const InputDecoration(labelText: '安全密钥', hintText: '32 位字母数字', prefixIcon: Icon(Icons.key_outlined)),
              ),
            ] else ...[
              TextField(controller: user, decoration: InputDecoration(labelText: s.isMail ? '邮箱地址' : '学号 / 用户名', prefixIcon: const Icon(Icons.person_outline))),
              const SizedBox(height: 12),
              TextField(
                controller: pw,
                obscureText: true,
                decoration: InputDecoration(
                  labelText: s.isMail ? '应用专用密码（不是邮箱登录密码）' : '密码',
                  helperText: s.isMail ? '在邮箱网页版的“设置 → 账户安全”中生成' : null,
                  prefixIcon: const Icon(Icons.lock_outline),
                ),
              ),
            ],
            if (s.isMail) ...[
              const SizedBox(height: 12),
              Row(children: [
                Expanded(flex: 3, child: TextField(controller: smtpHost, decoration: const InputDecoration(labelText: 'SMTP 服务器（发信用，可选）'))),
                const SizedBox(width: 8),
                Expanded(child: TextField(controller: smtpPort, decoration: const InputDecoration(labelText: '端口'))),
              ]),
            ],
            if (err != null) Padding(padding: const EdgeInsets.only(top: 12), child: Text(err!, style: TextStyle(color: Theme.of(c).colorScheme.error))),
          ]),
        ),
        actions: [
          TextButton(onPressed: busy ? null : () => Navigator.pop(c), child: const Text('取消')),
          FilledButton(
            onPressed: busy
                ? null
                : () async {
                    set(() {
                      busy = true;
                      err = null;
                    });
                    try {
                      final api = ref.read(apiProvider);
                      final r = useKey
                          ? await api.sourceLoginToken(s.id, key.text)
                          : await api.sourceLogin(
                              s.id,
                              user.text.trim(),
                              pw.text,
                              smtp: s.isMail && smtpHost.text.isNotEmpty ? {'host': smtpHost.text.trim(), 'port': int.tryParse(smtpPort.text) ?? 587} : null,
                            );
                      if (r['ok'] == true) {
                        ref.invalidate(sourcesProvider);
                        if (c.mounted) Navigator.pop(c);
                        if (context.mounted) toast(context, '登录成功，正在首次检查…');
                        return;
                      }
                      set(() => err = (r['error'] ?? '登录失败').toString());
                    } on ApiException catch (e) {
                      set(() => err = e.message);
                    } finally {
                      set(() => busy = false);
                    }
                  },
            child: busy ? const SizedBox(width: 18, height: 18, child: CircularProgressIndicator(strokeWidth: 2)) : Text(useKey ? '保存密钥' : '登录'),
          ),
        ],
      ),
    ),
  );
}

Future<void> showAddSource(BuildContext context, WidgetRef ref) async {
  await showModalBottomSheet<void>(
    context: context,
    isScrollControlled: true,
    builder: (c) => DraggableScrollableSheet(
      expand: false,
      initialChildSize: 0.85,
      maxChildSize: 0.95,
      builder: (c, scroll) => _AddSourceSheet(scroll: scroll),
    ),
  );
  ref.invalidate(sourcesProvider);
}

class _AddSourceSheet extends ConsumerStatefulWidget {
  final ScrollController scroll;
  const _AddSourceSheet({required this.scroll});
  @override
  ConsumerState<_AddSourceSheet> createState() => _AddSourceSheetState();
}

class _AddSourceSheetState extends ConsumerState<_AddSourceSheet> {
  final url = TextEditingController();
  final name = TextEditingController();
  final region = TextEditingController();
  String type = 'web';
  bool viaAgent = false;
  bool busy = false;
  Map<String, dynamic>? preview;

  @override
  Widget build(BuildContext context) {
    final tpl = ref.watch(templatesProvider);
    final t = Theme.of(context);
    final cs = t.colorScheme;
    return ListView(controller: widget.scroll, padding: const EdgeInsets.fromLTRB(20, 0, 20, 32), children: [
      Text('添加来源', style: t.textTheme.titleLarge),
      const SizedBox(height: 4),
      Text('校园模板已经配好了网页规则，点一下即可。', style: TextStyle(color: cs.onSurfaceVariant)),
      const SizedBox(height: 16),
      tpl.when(
        loading: () => const LinearProgressIndicator(),
        error: (e, _) => Text('$e'),
        data: (list) => LayoutBuilder(
          builder: (context, c) {
            final cols = c.maxWidth > 640 ? 3 : 2;
            return GridView.count(
              shrinkWrap: true,
              physics: const NeverScrollableScrollPhysics(),
              crossAxisCount: cols,
              mainAxisSpacing: 10,
              crossAxisSpacing: 10,
              childAspectRatio: cols == 3 ? 1.5 : 1.25,
              children: [for (final x in list) _TemplateTile(x, onTap: () => _addTemplate(x))],
            );
          },
        ),
      ),
      const SizedBox(height: 24),
      Text('自定义网址', style: t.textTheme.titleMedium),
      const SizedBox(height: 4),
      Text('任意通知列表页或 RSS。可以用 CSS 选择器限定“关注区域”，只监测页面的一部分。', style: TextStyle(color: cs.onSurfaceVariant)),
      const SizedBox(height: 12),
      SegmentedButton<String>(
        segments: const [ButtonSegment(value: 'web', label: Text('网页'), icon: Icon(Icons.public)), ButtonSegment(value: 'rss', label: Text('RSS'), icon: Icon(Icons.rss_feed))],
        selected: {type},
        onSelectionChanged: (v) => setState(() => type = v.first),
      ),
      const SizedBox(height: 12),
      TextField(controller: url, decoration: const InputDecoration(labelText: '网址', hintText: 'https://cs.example.edu/news/', prefixIcon: Icon(Icons.link))),
      const SizedBox(height: 10),
      TextField(controller: name, decoration: const InputDecoration(labelText: '名称（可选）', prefixIcon: Icon(Icons.label_outline))),
      if (type == 'web') ...[
        const SizedBox(height: 10),
        TextField(controller: region, decoration: const InputDecoration(labelText: '关注区域（CSS 选择器，可选）', hintText: '#main .news-list', prefixIcon: Icon(Icons.crop_free))),
      ],
      SwitchListTile(
        contentPadding: EdgeInsets.zero,
        value: viaAgent,
        onChanged: (v) => setState(() => viaAgent = v),
        title: const Text('只能在校园网内访问'),
        subtitle: const Text('由你电脑上的本地采集代理采集后上传'),
      ),
      const SizedBox(height: 8),
      Row(children: [
        OutlinedButton.icon(onPressed: busy ? null : _preview, icon: const Icon(Icons.preview_outlined), label: const Text('预览')),
        const SizedBox(width: 12),
        FilledButton.icon(onPressed: busy ? null : _addCustom, icon: const Icon(Icons.add), label: const Text('添加')),
        if (busy) const Padding(padding: EdgeInsets.only(left: 16), child: SizedBox(width: 20, height: 20, child: CircularProgressIndicator(strokeWidth: 2))),
      ]),
      if (preview != null) ...[
        const SizedBox(height: 16),
        Card(
          child: Padding(
            padding: const EdgeInsets.all(14),
            child: preview!['ok'] == true
                ? Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
                    Text('识别到 ${preview!['count']} 条，前几条：', style: const TextStyle(fontWeight: FontWeight.w700)),
                    const SizedBox(height: 8),
                    for (final it in (preview!['items'] as List).take(5))
                      Padding(
                        padding: const EdgeInsets.symmetric(vertical: 4),
                        child: Row(children: [
                          const Icon(Icons.subdirectory_arrow_right, size: 16),
                          const SizedBox(width: 6),
                          Expanded(child: Text((it as Map)['title'].toString(), maxLines: 1, overflow: TextOverflow.ellipsis)),
                          if (it['deadline_at'] != null) Pill('有截止时间', color: cs.tertiary),
                        ]),
                      ),
                  ])
                : Text('预览失败：${preview!['error']}', style: TextStyle(color: cs.error)),
          ),
        ),
      ],
    ]);
  }

  Map<String, dynamic> _customBody() => {
        'type': type,
        'endpoint': url.text.trim(),
        if (name.text.trim().isNotEmpty) 'name': name.text.trim(),
        'via_agent': viaAgent,
        'private': viaAgent,
        if (type == 'web') 'config': {if (region.text.trim().isNotEmpty) 'region': region.text.trim(), 'item_selector': 'li', 'link_selector': 'a[href]'},
      };

  Future<void> _preview() async {
    setState(() => busy = true);
    try {
      final r = await ref.read(apiProvider).previewSource(_customBody());
      setState(() => preview = r);
    } on ApiException catch (e) {
      setState(() => preview = {'ok': false, 'error': e.message});
    } finally {
      setState(() => busy = false);
    }
  }

  Future<void> _addCustom() async {
    if (url.text.trim().isEmpty) return;
    setState(() => busy = true);
    try {
      await ref.read(apiProvider).addSource(_customBody());
      if (mounted) {
        Navigator.pop(context);
        toast(context, '已添加，稍后会完成首次检查');
      }
    } on ApiException catch (e) {
      if (mounted) toast(context, e.message, error: true);
    } finally {
      if (mounted) setState(() => busy = false);
    }
  }

  Future<void> _addTemplate(SourceTemplate x) async {
    setState(() => busy = true);
    try {
      final r = await ref.read(apiProvider).addSource({'template': x.id});
      ref.invalidate(sourcesProvider);
      if (!mounted) return;
      Navigator.pop(context);
      if (r['needs_login'] == true) {
        final list = await ref.read(apiProvider).sources();
        final s = list.firstWhere((s) => s.id == (r['source'] as Map)['id']);
        if (mounted) await showLogin(context, ref, s);
      } else {
        toast(context, '已添加「${x.name}」');
        ref.read(feedProvider.notifier).refreshAll();
      }
    } on ApiException catch (e) {
      if (mounted) toast(context, e.message, error: true);
    } finally {
      if (mounted) setState(() => busy = false);
    }
  }
}

class _TemplateTile extends StatelessWidget {
  final SourceTemplate t;
  final VoidCallback onTap;
  const _TemplateTile(this.t, {required this.onTap});
  @override
  Widget build(BuildContext context) {
    final cs = Theme.of(context).colorScheme;
    return Material(
      color: cs.surfaceContainer,
      borderRadius: BorderRadius.circular(18),
      child: InkWell(
        borderRadius: BorderRadius.circular(18),
        onTap: onTap,
        child: Padding(
          padding: const EdgeInsets.all(14),
          child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
            Row(children: [
              Icon(templateIcon(t.icon), color: cs.primary),
              const Spacer(),
              if (t.needsLogin) Icon(Icons.lock_outline, size: 16, color: cs.onSurfaceVariant),
            ]),
            const SizedBox(height: 10),
            Text(t.name, style: const TextStyle(fontWeight: FontWeight.w700)),
            const SizedBox(height: 4),
            Expanded(child: Text(t.description, maxLines: 3, overflow: TextOverflow.ellipsis, style: TextStyle(fontSize: 12, color: cs.onSurfaceVariant, height: 1.35))),
          ]),
        ),
      ),
    );
  }
}
