import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:go_router/go_router.dart';

import '../../core/api.dart';
import '../../core/models.dart';
import '../../core/notifications.dart';
import '../../core/providers.dart';
import '../../core/session.dart';
import '../../core/store.dart';
import '../../widgets/common.dart';

class SettingsPage extends ConsumerWidget {
  const SettingsPage({super.key});

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final s = ref.watch(sessionProvider);
    final me = s.me;
    final feed = ref.watch(feedProvider);
    final mqtt = ref.watch(mqttProvider);
    final cs = Theme.of(context).colorScheme;
    return Scaffold(
      appBar: AppBar(title: const Text('设置')),
      body: Align(
        alignment: Alignment.topCenter,
        child: ConstrainedBox(
          constraints: const BoxConstraints(maxWidth: 760),
          child: ListView(padding: const EdgeInsets.fromLTRB(16, 0, 16, 96), children: [
            Card(
              child: ListTile(
                contentPadding: const EdgeInsets.all(16),
                leading: Avatar(me?.name ?? '', size: 52),
                title: Text(me?.name ?? '', style: Theme.of(context).textTheme.titleMedium),
                subtitle: Text([me?.email, me?.grade, me?.major].where((e) => e != null && e.isNotEmpty).join(' · ')),
                trailing: const Icon(Icons.edit_outlined),
                onTap: () => _editProfile(context, ref),
              ),
            ),
            const SectionHeader('通知'),
            Card(
              child: Column(children: [
                ListTile(
                  leading: const Icon(Icons.bedtime_outlined),
                  title: const Text('免打扰时段'),
                  subtitle: Text('${me?.quietStart ?? '23:00'} – ${me?.quietEnd ?? '07:00'}，只放行紧急通知'),
                  onTap: () => _editTimes(context, ref),
                ),
                ListTile(
                  leading: const Icon(Icons.wb_twilight),
                  title: const Text('每日摘要时间'),
                  subtitle: Text('每天 ${me?.digestTime ?? '08:00'} 推送一次摘要（MQTT 保留消息）'),
                  onTap: () => _editTimes(context, ref),
                ),
                SwitchListTile(
                  secondary: const Icon(Icons.forward_to_inbox),
                  title: const Text('每日摘要邮件'),
                  subtitle: Text('同时把摘要发到 ${me?.email ?? '注册邮箱'}（默认关闭）'),
                  value: me?.digestEmail ?? false,
                  onChanged: (v) => _save(context, ref, {'digest_email': v}),
                ),
                ListTile(
                  leading: const Icon(Icons.tune),
                  title: const Text('个性化规则'),
                  subtitle: const Text('加分关键词、屏蔽词、白名单发件人'),
                  trailing: const Icon(Icons.chevron_right),
                  onTap: () => context.push('/settings/rules'),
                ),
              ]),
            ),
            const SectionHeader('连接与同步'),
            Card(
              child: Column(children: [
                const ListTile(leading: Icon(Icons.bolt_outlined), title: Text('实时推送（WebSocket）'), trailing: ConnectionDot(showLabel: true)),
                ListTile(
                  leading: const Icon(Icons.notifications_active_outlined),
                  title: const Text('系统通知（MQTT）'),
                  subtitle: Text(switch (mqtt) { MqttConn.on => '已连接，紧急通知会推送到本设备', MqttConn.connecting => '连接中…', MqttConn.off => '未连接' }),
                ),
                ListTile(
                  leading: const Icon(Icons.sync),
                  title: const Text('同步游标'),
                  subtitle: Text('seq ${feed.cursor} · 本地缓存 ${feed.items.length} 条 · 待同步操作 ${feed.pending} 个'),
                  trailing: TextButton(onPressed: () => ref.read(feedProvider.notifier).syncNow(), child: const Text('立即同步')),
                ),
                ListTile(leading: const Icon(Icons.dns_outlined), title: const Text('服务器'), subtitle: Text(s.server)),
              ]),
            ),
            const SectionHeader('隐私与账号'),
            Card(
              child: Column(children: [
                const ListTile(
                  leading: Icon(Icons.shield_outlined),
                  title: Text('隐私说明'),
                  subtitle: Text(
                    'Moodle 等来源只保存登录会话，不保存统一认证密码；学校邮箱的应用专用密码与会话均用 AES-GCM 加密保存；'
                    '邮件只保存标题、发件人、摘要与链接；可随时删除账号与全部数据。',
                  ),
                ),
                ListTile(
                  leading: const Icon(Icons.password),
                  title: const Text('修改密码'),
                  subtitle: const Text('修改后其他设备需要重新登录'),
                  onTap: () => _changePassword(context, ref),
                ),
                ListTile(
                  leading: const Icon(Icons.logout),
                  title: const Text('退出登录'),
                  onTap: () async {
                    try {
                      await ref.read(apiProvider).logout();
                    } catch (_) {}
                    await ref.read(feedProvider.notifier).clearLocal();
                    await ref.read(sessionProvider.notifier).signOut();
                  },
                ),
                ListTile(
                  leading: Icon(Icons.delete_forever_outlined, color: cs.error),
                  title: Text('删除账号及全部数据', style: TextStyle(color: cs.error)),
                  onTap: () => _delete(context, ref),
                ),
              ]),
            ),
          ]),
        ),
      ),
    );
  }

  Future<void> _editProfile(BuildContext context, WidgetRef ref) async {
    final me = ref.read(sessionProvider).me!;
    final name = TextEditingController(text: me.name);
    final grade = TextEditingController(text: me.grade);
    final major = TextEditingController(text: me.major);
    final courses = TextEditingController(text: me.courses.join('、'));
    final ok = await showDialog<bool>(
      context: context,
      builder: (c) => AlertDialog(
        title: const Text('个人资料'),
        content: SizedBox(
          width: 400,
          child: Column(mainAxisSize: MainAxisSize.min, children: [
            TextField(controller: name, decoration: const InputDecoration(labelText: '昵称')),
            const SizedBox(height: 10),
            TextField(controller: grade, decoration: const InputDecoration(labelText: '年级', hintText: '2024级')),
            const SizedBox(height: 10),
            TextField(controller: major, decoration: const InputDecoration(labelText: '专业', hintText: '计算机')),
            const SizedBox(height: 10),
            TextField(controller: courses, decoration: const InputDecoration(labelText: '我的课程（用、分隔）', hintText: '网络编程、操作系统')),
            const SizedBox(height: 8),
            Text('年级、专业与课程用于判断通知是否与你相关。', style: TextStyle(fontSize: 12, color: Theme.of(c).colorScheme.onSurfaceVariant)),
          ]),
        ),
        actions: [TextButton(onPressed: () => Navigator.pop(c, false), child: const Text('取消')), FilledButton(onPressed: () => Navigator.pop(c, true), child: const Text('保存'))],
      ),
    );
    if (ok != true || !context.mounted) return;
    await _save(context, ref, {
      'name': name.text.trim(),
      'grade': grade.text.trim(),
      'major': major.text.trim(),
      'courses': courses.text.split(RegExp(r'[、,，\s]+')).where((e) => e.isNotEmpty).toList(),
    });
  }

  Future<void> _editTimes(BuildContext context, WidgetRef ref) async {
    final me = ref.read(sessionProvider).me!;
    TimeOfDay parse(String s) => TimeOfDay(hour: int.parse(s.split(':')[0]), minute: int.parse(s.split(':')[1]));
    String fmt(TimeOfDay t) => '${t.hour.toString().padLeft(2, '0')}:${t.minute.toString().padLeft(2, '0')}';
    final qs = await showTimePicker(context: context, initialTime: parse(me.quietStart), helpText: '免打扰开始');
    if (qs == null || !context.mounted) return;
    final qe = await showTimePicker(context: context, initialTime: parse(me.quietEnd), helpText: '免打扰结束');
    if (qe == null || !context.mounted) return;
    final dg = await showTimePicker(context: context, initialTime: parse(me.digestTime), helpText: '每日摘要时间');
    if (dg == null || !context.mounted) return;
    await _save(context, ref, {'quiet_start': fmt(qs), 'quiet_end': fmt(qe), 'digest_time': fmt(dg)});
  }

  Future<void> _save(BuildContext context, WidgetRef ref, Map<String, dynamic> body) async {
    try {
      final api = ref.read(apiProvider);
      final me = await api.updateMe(body);
      final raw = await api.dio.get('/api/me');
      await ref.read(sessionProvider.notifier).updateMe(me, Map<String, dynamic>.from(raw.data as Map));
      if (context.mounted) toast(context, '已保存');
    } on ApiException catch (e) {
      if (context.mounted) toast(context, e.message, error: true);
    }
  }

  Future<void> _changePassword(BuildContext context, WidgetRef ref) async {
    final oldPw = TextEditingController();
    final newPw = TextEditingController();
    String? err;
    await showDialog<void>(
      context: context,
      builder: (c) => StatefulBuilder(
        builder: (c, set) => AlertDialog(
          title: const Text('修改密码'),
          content: SizedBox(
            width: 360,
            child: Column(mainAxisSize: MainAxisSize.min, children: [
              TextField(controller: oldPw, obscureText: true, decoration: const InputDecoration(labelText: '当前密码')),
              const SizedBox(height: 10),
              TextField(controller: newPw, obscureText: true, decoration: const InputDecoration(labelText: '新密码（至少 8 位）')),
              if (err != null) Padding(padding: const EdgeInsets.only(top: 12), child: Text(err!, style: TextStyle(color: Theme.of(c).colorScheme.error))),
            ]),
          ),
          actions: [
            TextButton(onPressed: () => Navigator.pop(c), child: const Text('取消')),
            FilledButton(
              onPressed: () async {
                try {
                  final resp = await ref.read(apiProvider).changePassword(oldPw.text, newPw.text);
                  await ref.read(sessionProvider.notifier).signedIn(resp);
                  if (c.mounted) Navigator.pop(c);
                  if (context.mounted) toast(context, '密码已修改，其他设备需要重新登录');
                } on ApiException catch (e) {
                  set(() => err = e.message);
                }
              },
              child: const Text('确认修改'),
            ),
          ],
        ),
      ),
    );
  }

  Future<void> _delete(BuildContext context, WidgetRef ref) async {
    final pw = TextEditingController();
    String? err;
    final ok = await showDialog<bool>(
      context: context,
      builder: (c) => StatefulBuilder(
        builder: (c, set) => AlertDialog(
          icon: const Icon(Icons.warning_amber_rounded),
          title: const Text('删除账号？'),
          content: SizedBox(
            width: 380,
            child: Column(mainAxisSize: MainAxisSize.min, children: [
              const Text('将删除你的账号、订阅、登录会话、个人状态与发信记录，且无法恢复。请输入密码确认。'),
              const SizedBox(height: 12),
              TextField(controller: pw, obscureText: true, decoration: const InputDecoration(labelText: '密码')),
              if (err != null) Padding(padding: const EdgeInsets.only(top: 12), child: Text(err!, style: TextStyle(color: Theme.of(c).colorScheme.error))),
            ]),
          ),
          actions: [
            TextButton(onPressed: () => Navigator.pop(c, false), child: const Text('取消')),
            FilledButton(
              style: FilledButton.styleFrom(backgroundColor: Theme.of(c).colorScheme.error),
              onPressed: () async {
                try {
                  await ref.read(apiProvider).deleteAccount(pw.text);
                  if (c.mounted) Navigator.pop(c, true);
                } on ApiException catch (e) {
                  set(() => err = e.message);
                }
              },
              child: const Text('永久删除'),
            ),
          ],
        ),
      ),
    );
    if (ok != true) return;
    await ref.read(feedProvider.notifier).clearLocal();
    await ref.read(sessionProvider.notifier).signOut();
  }
}

class RulesPage extends ConsumerStatefulWidget {
  const RulesPage({super.key});
  @override
  ConsumerState<RulesPage> createState() => _RulesPageState();
}

class _RulesPageState extends ConsumerState<RulesPage> {
  List<Rule>? rules;
  final ctl = TextEditingController();
  String kind = 'keyword';
  bool block = false;

  @override
  Widget build(BuildContext context) {
    final async = ref.watch(rulesProvider);
    rules ??= async.asData?.value.toList();
    final list = rules ?? [];
    final cs = Theme.of(context).colorScheme;
    return Scaffold(
      appBar: AppBar(title: const Text('个性化规则'), actions: [
        TextButton(
          onPressed: rules == null
              ? null
              : () async {
                  await ref.read(apiProvider).saveRules(list);
                  ref.invalidate(rulesProvider);
                  if (context.mounted) toast(context, '规则已保存，对之后的新事项生效');
                },
          child: const Text('保存'),
        ),
        const SizedBox(width: 8),
      ]),
      body: ListView(padding: const EdgeInsets.all(16), children: [
        Card(
          child: Padding(
            padding: const EdgeInsets.all(16),
            child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
              Text('优先级 = 100 ×（0.30 来源权重 + 0.25 关键词 + 0.25 截止临近 + 0.20 与你匹配）', style: TextStyle(color: cs.onSurfaceVariant, fontSize: 12)),
              const SizedBox(height: 4),
              Text('≥ 80 紧急（推送到手机）· 40–79 普通 · < 40 只进信息流与摘要', style: TextStyle(color: cs.onSurfaceVariant, fontSize: 12)),
              const SizedBox(height: 14),
              SegmentedButton<String>(
                segments: const [ButtonSegment(value: 'keyword', label: Text('关键词')), ButtonSegment(value: 'sender', label: Text('白名单发件人'))],
                selected: {kind},
                onSelectionChanged: (v) => setState(() => kind = v.first),
              ),
              const SizedBox(height: 10),
              Row(children: [
                Expanded(child: TextField(controller: ctl, decoration: InputDecoration(hintText: kind == 'keyword' ? '例如：保研、奖学金' : 'teacher@school.edu'))),
                if (kind == 'keyword') ...[const SizedBox(width: 8), FilterChip(label: const Text('屏蔽'), selected: block, onSelected: (v) => setState(() => block = v))],
                const SizedBox(width: 8),
                FilledButton(
                  onPressed: () {
                    if (ctl.text.trim().isEmpty) return;
                    setState(() {
                      rules = [...list, Rule(kind, ctl.text.trim(), block ? -1 : 0.5)];
                      ctl.clear();
                    });
                  },
                  child: const Text('添加'),
                ),
              ]),
            ]),
          ),
        ),
        const SizedBox(height: 12),
        if (list.isEmpty) const EmptyState(icon: Icons.rule, title: '还没有自定义规则', message: '默认关键词：截止、deadline、考试、调课、取消。'),
        Wrap(spacing: 8, runSpacing: 8, children: [
          for (var i = 0; i < list.length; i++)
            InputChip(
              avatar: Icon(list[i].kind == 'sender' ? Icons.verified_user_outlined : (list[i].boost <= 0 ? Icons.block : Icons.trending_up), size: 18),
              label: Text(list[i].pattern),
              onDeleted: () => setState(() => rules = [...list]..removeAt(i)),
            ),
        ]),
      ]),
    );
  }
}
