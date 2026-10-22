import 'dart:async';

import 'package:flutter/foundation.dart';
import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../core/api.dart';
import '../../core/session.dart';
import '../../theme.dart';
import '../../widgets/common.dart';

class LoginPage extends ConsumerStatefulWidget {
  const LoginPage({super.key});
  @override
  ConsumerState<LoginPage> createState() => _LoginPageState();
}

class _LoginPageState extends ConsumerState<LoginPage> {
  bool register = false;
  bool busy = false;
  bool agree = true;
  String? error;
  final email = TextEditingController();
  final pw = TextEditingController();
  final name = TextEditingController();
  final grade = TextEditingController();
  final major = TextEditingController();
  final code = TextEditingController();
  late final server = TextEditingController(text: ref.read(sessionProvider).server);
  int resendIn = 0; // 验证码重发倒计时（秒）
  Timer? _countdown;
  bool sendingCode = false;

  @override
  void dispose() {
    _countdown?.cancel();
    super.dispose();
  }

  Future<void> _sendCode() async {
    setState(() {
      sendingCode = true;
      error = null;
    });
    try {
      if (!kIsWeb) await ref.read(sessionProvider.notifier).setServer(server.text);
      final r = await ref.read(apiProvider).sendCode(email.text.trim());
      if (!mounted) return;
      toast(context, '验证码已发送到 ${email.text.trim()}，10 分钟内有效');
      _startCountdown((r['resend_after'] ?? 60) as int);
    } on ApiException catch (e) {
      setState(() => error = e.message);
      if (e.status == 429) _startCountdown(60);
    } finally {
      if (mounted) setState(() => sendingCode = false);
    }
  }

  void _startCountdown(int seconds) {
    _countdown?.cancel();
    setState(() => resendIn = seconds);
    _countdown = Timer.periodic(const Duration(seconds: 1), (t) {
      if (!mounted || resendIn <= 1) {
        t.cancel();
        if (mounted) setState(() => resendIn = 0);
        return;
      }
      setState(() => resendIn--);
    });
  }

  Future<void> _submit() async {
    setState(() {
      busy = true;
      error = null;
    });
    try {
      if (!kIsWeb) await ref.read(sessionProvider.notifier).setServer(server.text);
      final api = ref.read(apiProvider);
      final r = register
          ? await api.register({
              'email': email.text.trim(),
              'code': code.text.trim(),
              'password': pw.text,
              'name': name.text.trim(),
              'grade': grade.text.trim(),
              'major': major.text.trim(),
              'agree_privacy': agree,
            })
          : await api.login(email.text.trim(), pw.text);
      await ref.read(sessionProvider.notifier).signedIn(r);
    } on ApiException catch (e) {
      setState(() => error = e.message);
    } finally {
      if (mounted) setState(() => busy = false);
    }
  }

  @override
  Widget build(BuildContext context) {
    final t = Theme.of(context);
    final cs = t.colorScheme;
    final wide = MediaQuery.sizeOf(context).width >= 900;
    final form = ConstrainedBox(
      constraints: const BoxConstraints(maxWidth: 420),
      child: Column(mainAxisSize: MainAxisSize.min, crossAxisAlignment: CrossAxisAlignment.stretch, children: [
        if (!wide) ...[
          const Center(child: GleanerLogo(size: 64)),
          const SizedBox(height: 16),
          Center(child: Text('拾课', style: t.textTheme.headlineMedium)),
          const SizedBox(height: 4),
          Center(child: Text('把散落各处的课程信息拾起来', style: TextStyle(color: cs.onSurfaceVariant))),
          const SizedBox(height: 28),
        ],
        Text(register ? '创建账号' : '欢迎回来', style: t.textTheme.headlineSmall?.copyWith(fontWeight: FontWeight.w800)),
        const SizedBox(height: 6),
        Text(register ? '一分钟完成：注册后用校园模板添加来源即可。' : '登录后继续同步你的作业、通知与日程。', style: TextStyle(color: cs.onSurfaceVariant)),
        const SizedBox(height: 24),
        TextField(controller: email, keyboardType: TextInputType.emailAddress, decoration: const InputDecoration(labelText: '邮箱', prefixIcon: Icon(Icons.alternate_email))),
        if (register) ...[
          const SizedBox(height: 12),
          Row(children: [
            Expanded(
              child: TextField(
                controller: code,
                keyboardType: TextInputType.number,
                maxLength: 6,
                decoration: const InputDecoration(labelText: '邮箱验证码', prefixIcon: Icon(Icons.verified_outlined), counterText: ''),
              ),
            ),
            const SizedBox(width: 12),
            SizedBox(
              height: 52,
              child: FilledButton.tonal(
                onPressed: sendingCode || resendIn > 0 ? null : _sendCode,
                child: sendingCode
                    ? const SizedBox(width: 18, height: 18, child: CircularProgressIndicator(strokeWidth: 2))
                    : Text(resendIn > 0 ? '$resendIn 秒后重发' : '获取验证码'),
              ),
            ),
          ]),
        ],
        const SizedBox(height: 12),
        TextField(controller: pw, obscureText: true, onSubmitted: (_) => _submit(), decoration: InputDecoration(labelText: register ? '密码（至少 8 位）' : '密码', prefixIcon: const Icon(Icons.lock_outline))),
        if (register) ...[
          const SizedBox(height: 12),
          TextField(controller: name, decoration: const InputDecoration(labelText: '昵称', prefixIcon: Icon(Icons.person_outline))),
          const SizedBox(height: 12),
          Row(children: [
            Expanded(child: TextField(controller: grade, decoration: const InputDecoration(labelText: '年级', hintText: '2024级'))),
            const SizedBox(width: 12),
            Expanded(child: TextField(controller: major, decoration: const InputDecoration(labelText: '专业', hintText: '计算机'))),
          ]),
          const SizedBox(height: 8),
          CheckboxListTile(
            contentPadding: EdgeInsets.zero,
            value: agree,
            onChanged: (v) => setState(() => agree = v ?? false),
            controlAffinity: ListTileControlAffinity.leading,
            title: const Text('我已阅读隐私说明', style: TextStyle(fontSize: 14)),
            subtitle: const Text(
              '拾课只保存 Moodle 等来源的登录会话，不保存统一认证密码；学校邮箱需使用“应用专用密码”，以 AES-GCM 加密保存；'
              '邮件只保存标题、发件人、摘要与链接；可随时删除账号与全部数据。',
              style: TextStyle(fontSize: 12),
            ),
          ),
        ],
        if (!kIsWeb) ...[
          const SizedBox(height: 12),
          ExpansionTile(
            tilePadding: EdgeInsets.zero,
            title: const Text('服务器地址', style: TextStyle(fontSize: 14)),
            children: [TextField(controller: server, decoration: const InputDecoration(prefixIcon: Icon(Icons.dns_outlined)))],
          ),
        ],
        if (error != null)
          Padding(
            padding: const EdgeInsets.only(top: 12),
            child: Container(
              padding: const EdgeInsets.all(12),
              decoration: BoxDecoration(color: cs.errorContainer, borderRadius: BorderRadius.circular(12)),
              child: Text(error!, style: TextStyle(color: cs.onErrorContainer)),
            ),
          ),
        const SizedBox(height: 20),
        FilledButton(
          onPressed: busy || (register && !agree) ? null : _submit,
          child: busy ? const SizedBox(height: 20, width: 20, child: CircularProgressIndicator(strokeWidth: 2)) : Text(register ? '注册并开始' : '登录'),
        ),
        const SizedBox(height: 8),
        TextButton(onPressed: () => setState(() => register = !register), child: Text(register ? '已有账号？登录' : '还没有账号？注册')),
      ]),
    );

    if (!wide) {
      return Scaffold(body: SafeArea(child: Center(child: SingleChildScrollView(padding: const EdgeInsets.all(24), child: form))));
    }
    return Scaffold(
      body: Row(children: [
        Expanded(
          flex: 5,
          child: Container(
            decoration: BoxDecoration(
              gradient: LinearGradient(colors: [cs.primary, Color.lerp(cs.primary, Colors.black, 0.35)!], begin: Alignment.topLeft, end: Alignment.bottomRight),
            ),
            child: Stack(children: [
              Positioned(right: -80, bottom: -80, child: Opacity(opacity: 0.12, child: GleanerLogo(size: 420))),
              Padding(
                padding: const EdgeInsets.all(56),
                child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
                  Row(children: [
                    const GleanerLogo(size: 48),
                    const SizedBox(width: 14),
                    Text('拾课 Gleaner', style: t.textTheme.titleLarge?.copyWith(color: cs.onPrimary)),
                  ]),
                  const Spacer(),
                  Text('信息发布了，\n不等于你看到了。', style: t.textTheme.displaySmall?.copyWith(color: cs.onPrimary, fontWeight: FontWeight.w800, height: 1.25)),
                  const SizedBox(height: 20),
                  Text('Moodle 作业、学院通知、学校邮箱，拾起来、理好、放进你的日程。', style: t.textTheme.titleMedium?.copyWith(color: cs.onPrimary.withValues(alpha: 0.85))),
                  const SizedBox(height: 36),
                  for (final (i, s) in [
                    (Icons.event_note, '跨课程作业日历，截止时间被修改时自动跟随'),
                    (Icons.bolt, '新事项秒级推送，手机收到紧急提醒'),
                    (Icons.merge_type, '提醒邮件与课程页的同一作业自动合并'),
                    (Icons.cloud_off, '离线也能看，联网后自动补齐'),
                  ])
                    Padding(
                      padding: const EdgeInsets.only(bottom: 14),
                      child: Row(children: [
                        Container(
                          padding: const EdgeInsets.all(8),
                          decoration: BoxDecoration(color: Brand.wheat.withValues(alpha: 0.2), borderRadius: BorderRadius.circular(10)),
                          child: Icon(i, color: Brand.wheat, size: 20),
                        ),
                        const SizedBox(width: 14),
                        Text(s, style: TextStyle(color: cs.onPrimary, fontSize: 15)),
                      ]),
                    ),
                  const Spacer(),
                  Text('网络编程课程项目 · 全部协议从 socket 层自研', style: TextStyle(color: cs.onPrimary.withValues(alpha: 0.6), fontSize: 12)),
                ]),
              ),
            ]),
          ),
        ),
        Expanded(flex: 4, child: Center(child: SingleChildScrollView(padding: const EdgeInsets.all(40), child: form))),
      ]),
    );
  }
}
