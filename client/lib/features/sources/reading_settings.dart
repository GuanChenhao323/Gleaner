import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:go_router/go_router.dart';
import 'package:url_launcher/url_launcher.dart';

import '../../core/format.dart';
import '../../core/models.dart';
import '../../widgets/common.dart';
import 'reading_source.dart';

class ReadingSettingsPage extends ConsumerStatefulWidget {
  final int id;
  const ReadingSettingsPage({super.key, required this.id});
  @override
  ConsumerState<ReadingSettingsPage> createState() => _ReadingSettingsState();
}

class _ReadingSettingsState extends ConsumerState<ReadingSettingsPage> {
  String? mode;
  int? interval;
  bool busy = false;
  Future<void> act(Future<void> Function() action, String message) async {
    setState(() => busy = true);
    try {
      await action();
      if (mounted) toast(context, message);
    } catch (e) {
      if (mounted) toast(context, '$e', error: true);
    } finally {
      if (mounted) setState(() => busy = false);
    }
  }

  @override
  Widget build(BuildContext context) {
    final data = ref.watch(readingSourcesProvider);
    return Scaffold(
      appBar: AppBar(
        title: const Text('来源检查设置'),
        leading: IconButton(
          tooltip: '返回信息源',
          icon: const Icon(Icons.arrow_back),
          onPressed: () => context.go('/sources'),
        ),
      ),
      body: data.when(
        loading: () => const Center(child: CircularProgressIndicator()),
        error: (e, _) => Center(child: Text('无法读取来源：$e')),
        data: (rows) {
          final s = rows.where((s) => s.id == widget.id).firstOrNull;
          if (s == null) return const Center(child: Text('来源不存在，或不属于当前工作台账号。'));
          final controller = ref.read(readingSourcesProvider.notifier),
              cs = Theme.of(context).colorScheme;
          final selected = mode ?? s.mode, period = interval ?? s.interval;
          Widget heading(String text) => Padding(
            padding: const EdgeInsets.only(top: 23, bottom: 12),
            child: Text(text, style: Theme.of(context).textTheme.titleMedium),
          );
          Widget fact(String name, String value) => Padding(
            padding: const EdgeInsets.symmetric(vertical: 5),
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Text(
                  name,
                  style: TextStyle(fontSize: 12, color: cs.onSurfaceVariant),
                ),
                SelectableText(value),
              ],
            ),
          );
          return ListView(
            padding: const EdgeInsets.all(24),
            children: [
              Text(s.title, style: Theme.of(context).textTheme.headlineSmall),
              const SizedBox(height: 5),
              const Text(
                '保留原资料、关键词和历史。请在本机Chrome登录原站，并保留唯一的原网页作为专用监测页。重新登录后，先刷新原页确认内容可见，再重新绑定。',
              ),
              heading('01 · 检查内容'),
              fact('来源网页', s.url),
              fact('原关键词', s.query),
              fact('原站登录要求', s.loginRequirement),
              fact('资料可见范围', '仅自己可见'),
              fact('匹配范围', s.scope),
              fact('关联资料', '${s.matchCount} 条匹配 · ${s.items.length} 份资料'),
              heading('02 · 来源会话与后台重读'),
              if (s.result == 'documents_purged')
                const Text('部分关联资料已经彻底删除。请先在原网页重新提取并保存，确认新的采集范围。'),
              Card(
                child: Padding(
                  padding: const EdgeInsets.all(16),
                  child: Column(
                    crossAxisAlignment: CrossAxisAlignment.start,
                    children: [
                      Text(
                        s.identity,
                        style: const TextStyle(fontWeight: FontWeight.w600),
                      ),
                      const SizedBox(height: 6),
                      Text(
                        s.isPublic
                            ? '公开来源依据你的声明；测试验证当次页面能否重新读取。'
                            : '复用专用标签页的Chrome会话，每次实际刷新后读取；不复制Cookie到工作台。',
                      ),
                      const SizedBox(height: 9),
                      Text(s.status, style: TextStyle(color: cs.primary)),
                      if (s.capability == 'account_unknown')
                        const Padding(
                          padding: EdgeInsets.only(top: 8),
                          child: Text(
                            '可以明确绑定当前原页会话进行单账号监测；无需为了识别邮箱而停留在手动模式。未识别到账号不代表已经认证，已知账号切换仍会暂停。',
                          ),
                        ),
                      const SizedBox(height: 12),
                      Wrap(
                        spacing: 8,
                        runSpacing: 8,
                        children: [
                          OutlinedButton.icon(
                            onPressed: () => launchUrl(Uri.parse(s.url)),
                            icon: const Icon(Icons.open_in_new),
                            label: Text(s.isPublic ? '打开原网页' : '去原站登录'),
                          ),
                          FilledButton.icon(
                            onPressed:
                                busy ||
                                    s.active ||
                                    s.result == 'documents_purged'
                                ? null
                                : () => act(
                                    () => controller.activate(s, period),
                                    '正在绑定原网页并启动自动监测；首次实际刷新完成后显示成功时间。',
                                  ),
                            icon: const Icon(Icons.play_arrow),
                            label: Text(
                              s.active
                                  ? '等待执行'
                                  : s.resident
                                  ? '重新绑定监测页并启动'
                                  : '绑定原页并开启定期监测',
                            ),
                          ),
                          if (!s.resident && s.capability != 'account_unknown')
                            FilledButton.tonal(
                              onPressed: busy || s.active
                                  ? null
                                  : () => act(
                                      () => controller.check(s, 'verify'),
                                      '重读测试已排队；请保持 Chrome 与扩展运行。',
                                    ),
                              child: Text(
                                s.active
                                    ? '等待浏览器执行'
                                    : s.verified
                                    ? '重新测试重读'
                                    : '授权并测试重读',
                              ),
                            ),
                        ],
                      ),
                      if (s.result == 'permission_denied')
                        const Text('请在原网站打开插件并点击提取，允许访问后，再回到这里测试。'),
                    ],
                  ),
                ),
              ),
              if (!s.deviceOnline)
                const Padding(
                  padding: EdgeInsets.only(top: 10),
                  child: Text('尚未检测到执行设备近期连接；排队不代表已执行。'),
                ),
              heading('03 · 检查方式'),
              if (s.resident)
                const Padding(
                  padding: EdgeInsets.only(bottom: 12),
                  child: Text('周期、暂停和立即检查作用于此监测页的全部规则；删除只影响所选规则。'),
                ),
              DropdownButtonFormField<String>(
                initialValue: selected,
                decoration: const InputDecoration(labelText: '检查方式'),
                items: const [
                  DropdownMenuItem(value: 'manual', child: Text('仅手动检查')),
                  DropdownMenuItem(value: 'periodic', child: Text('定期检查')),
                ],
                onChanged: !s.verified || busy
                    ? null
                    : (v) => setState(() => mode = v),
              ),
              if (selected == 'periodic')
                Padding(
                  padding: const EdgeInsets.only(top: 15),
                  child: DropdownButtonFormField<int>(
                    initialValue: period,
                    decoration: const InputDecoration(labelText: '检查周期'),
                    items: const [
                      DropdownMenuItem(value: 1800, child: Text('每 30 分钟')),
                      DropdownMenuItem(value: 3600, child: Text('每 1 小时')),
                      DropdownMenuItem(value: 7200, child: Text('每 2 小时')),
                    ],
                    onChanged: !s.verified || busy
                        ? null
                        : (v) => setState(() => interval = v),
                  ),
                ),
              const SizedBox(height: 13),
              const Text(
                '专用监测页需要保持打开；可以关闭工作台页面。编辑时延后刷新，登录失效或标签关闭时暂停。Chrome、扩展与本地服务需保持运行；失败不覆盖成功资料。',
              ),
              const SizedBox(height: 24),
              Wrap(
                spacing: 10,
                runSpacing: 10,
                children: [
                  FilledButton(
                    onPressed: !s.verified || busy || s.active
                        ? null
                        : () => act(
                            () => controller.configure(
                              s,
                              s.settings(
                                mode: selected,
                                interval: period,
                                paused: false,
                              ),
                            ),
                            selected == 'periodic' ? '定期检查已启用。' : '手动检查设置已保存。',
                          ),
                    child: Text(selected == 'periodic' ? '启用定期检查' : '保存检查设置'),
                  ),
                  if (s.verified)
                    OutlinedButton(
                      onPressed: busy || s.active
                          ? null
                          : () => act(
                              () => controller.check(s, 'check'),
                              '检查请求已排队，结果确认后更新状态。',
                            ),
                      child: const Text('立即检查'),
                    ),
                  TextButton(
                    onPressed: () => context.push('/sources/${s.id}/checks'),
                    child: const Text('检查日志'),
                  ),
                ],
              ),
              heading('已保存资料'),
              for (final item in s.items)
                ListTile(
                  contentPadding: EdgeInsets.zero,
                  leading: const Icon(Icons.article_outlined),
                  title: Text('${item['title']}'),
                  subtitle: Text('v${item['version']} · 可查看原文与版本差异'),
                  trailing: const Icon(Icons.chevron_right),
                  onTap: () => context.push('/item/${item['id']}'),
                ),
            ],
          );
        },
      ),
    );
  }
}

class ReadingChecksPage extends ConsumerWidget {
  final int id;
  const ReadingChecksPage({super.key, required this.id});
  @override
  Widget build(BuildContext context, WidgetRef ref) {
    return Scaffold(
      appBar: AppBar(
        title: const Text('来源检查日志'),
        actions: [
          IconButton(
            tooltip: '刷新日志',
            icon: const Icon(Icons.refresh),
            onPressed: () => ref.invalidate(readingChecksProvider(id)),
          ),
        ],
      ),
      body: ReadingChecksBody(id: id),
    );
  }
}

class ReadingChecksBody extends ConsumerWidget {
  final int id;
  const ReadingChecksBody({super.key, required this.id});
  @override
  Widget build(BuildContext context, WidgetRef ref) => ref
      .watch(readingChecksProvider(id))
      .when(
        loading: () => const Center(child: CircularProgressIndicator()),
        error: (e, _) => Center(child: Text('日志读取失败：$e')),
        data: (rows) => ListView(
          padding: const EdgeInsets.all(24),
          children: [
            const Text('验证不更新成功检查时间；失败和未匹配不会覆盖已保存内容。'),
            const SizedBox(height: 15),
            if (rows.isEmpty) const Text('尚未执行来源检查。'),
            for (final r in rows)
              Card(
                child: ListTile(
                  leading: Icon(
                    r['result'] == 'changed'
                        ? Icons.change_circle_outlined
                        : r['result'] == 'unchanged' ||
                              r['result'] == 'verified'
                        ? Icons.check_circle_outline
                        : Icons.error_outline,
                  ),
                  title: Text(readingResultLabel('${r['result']}')),
                  subtitle: Text(
                    '${r['purpose'] == 'verify'
                        ? '重读验证'
                        : r['purpose'] == 'activate'
                        ? '首次刷新／绑定'
                        : '来源检查'} · ${relative(tsToDate((r['checked_at'] as num).toDouble()))}',
                  ),
                ),
              ),
          ],
        ),
      );
}

final readingChecksProvider = FutureProvider.autoDispose
    .family<List<Map<String, dynamic>>, int>((ref, id) {
      ref.watch(
        readingSourcesProvider.select(
          (v) => v.value
              ?.where((s) => s.id == id)
              .map((s) => '${s.lastAttempt}|${s.result}|${s.active}')
              .firstOrNull,
        ),
      );
      return ref.watch(readingRepositoryProvider).checks(id);
    });
