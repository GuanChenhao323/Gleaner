import 'dart:async';

import 'package:flutter/foundation.dart';
import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../core/api.dart';
import '../../core/session.dart';
import '../../widgets/common.dart';

class LoginDialog extends ConsumerStatefulWidget {
  final VoidCallback onClose;
  const LoginDialog({super.key, required this.onClose});
  @override
  ConsumerState<LoginDialog> createState() => _LoginDialogState();
}

class _LoginDialogState extends ConsumerState<LoginDialog> {
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
    for (final field in [email, pw, name, grade, major, code, server]) {
      field.dispose();
    }
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
      if (!mounted) return;
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
    if (busy || (register && !agree)) return;
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
      if (!mounted) return;
      await ref.read(sessionProvider.notifier).signedIn(r);
      if (mounted) widget.onClose();
    } on ApiException catch (e) {
      if (!mounted) return;
      setState(() => error = e.message);
    } finally {
      if (mounted) setState(() => busy = false);
    }
  }

  @override
  Widget build(BuildContext context) {
    final t = Theme.of(context);
    final cs = t.colorScheme;
    final form = ConstrainedBox(
      constraints: const BoxConstraints(maxWidth: 420),
      child: Column(mainAxisSize: MainAxisSize.min, crossAxisAlignment: CrossAxisAlignment.stretch, children: [
        Row(children: [
          const GleanerLogo(size: 32),
          const SizedBox(width: 12),
          Expanded(child: Text(register ? '创建账号' : '登录', style: t.textTheme.headlineSmall)),
          IconButton(tooltip: '关闭', onPressed: widget.onClose, icon: const Icon(Icons.close)),
        ]),
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

    final content = SingleChildScrollView(padding: const EdgeInsets.all(24), child: form);
    return Dialog(child: content);
  }
}
