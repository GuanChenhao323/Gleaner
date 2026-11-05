import 'dart:async';

import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:go_router/go_router.dart';
import 'package:url_launcher/url_launcher.dart';

import '../../core/format.dart';
import '../../core/models.dart';
import '../../core/providers.dart';
import '../../core/session.dart';

String browserCheckLabel(String result) => switch (result) {
  'not_executed' => '待首次检查',
  'unchanged' => '检查成功 · 无变化',
  'changed' => '已发现来源变化',
  'need_login' => '请在学校原站重新登录',
  'account_mismatch' => '学校账号已切换 · 旧绑定已停止',
  'selection_missing' => '原文定位失效 · 需要重新采集',
  'view_mismatch' => '原学期／周次视图失效 · 需要重新采集',
  'route_mismatch' => '来源路由已改变 · 需要重新采集',
  'render_timeout' => '页面加载超时',
  'permission_denied' => '浏览器来源权限不足',
  'unsupported' => '暂不支持监测',
  _ => '检查失败',
};

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
          '从校园网页选择信息',
          style: TextStyle(fontWeight: FontWeight.bold, fontSize: 18),
        ),
        const Text('在原站自行登录，打开 Campus Radar 插件识别、勾选并预览。只保存所选内容；未支持的页面会明确提示。'),
        Wrap(
          spacing: 8,
          children: [
            for (final entry in const {
              'Moodle': 'https://moodle.must.edu.mo/my/',
              '学生系统': 'https://student-wmweb.must.edu.mo/',
              '学院人员目录':
                  'https://fie.must.edu.mo/person/id-828.html?locale=zh_MO',
            }.entries)
              TextButton(
                onPressed: () => launchUrl(Uri.parse(entry.value)),
                child: Text('打开${entry.key}'),
              ),
            TextButton(onPressed: load, child: const Text('刷新采集来源')),
          ],
        ),
        if (error != null)
          Text(
            '无法读取采集来源：$error',
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
                    '${m['title'] ?? '已保存来源'}',
                    style: const TextStyle(fontWeight: FontWeight.bold),
                  ),
                  SelectableText('${(m['recipe'] as Map)['url']}'),
                  Text(
                    m['supported'] != true
                        ? '仅保存 · 暂不支持监测'
                        : '${m['enabled'] == true ? '已启用' : '已暂停'} · ${browserCheckLabel('${m['last_result']}')}',
                  ),
                  Text('最后成功检查：${relative(tsToDate(m['last_success_at']))}'),
                  if ('${m['error']}'.isNotEmpty)
                    Text(browserCheckLabel('${m['error']}')),
                  Wrap(
                    spacing: 8,
                    children: [
                      TextButton(
                        onPressed: () => context.push('/item/${m['item_id']}'),
                        child: const Text('查看事项与变化'),
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
                          child: Text(m['enabled'] == true ? '暂停' : '恢复'),
                        ),
                        if (m['enabled'] == true)
                          TextButton(
                            onPressed: () =>
                                act(() => api.browserCheck(m['id'] as int)),
                            child: const Text('立即检查'),
                          ),
                      ],
                      TextButton(
                        onPressed: () =>
                            act(() => api.browserRemove(m['id'] as int)),
                        child: const Text('停止监测，保留事项'),
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
