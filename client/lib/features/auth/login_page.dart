import 'dart:async';

import 'package:flutter/foundation.dart';
import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../core/api.dart';
import '../../core/session.dart';
import '../../l10n/app_localizations.dart';
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
  int resendIn = 0;
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
      toast(context, AppLocalizations.of(context).codeSent(email.text.trim()));
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
    final l10n = AppLocalizations.of(context);
    final form = ConstrainedBox(
      constraints: const BoxConstraints(maxWidth: 420),
      child: Column(mainAxisSize: MainAxisSize.min, crossAxisAlignment: CrossAxisAlignment.stretch, children: [
        Row(children: [
          const GleanerLogo(size: 32),
          const SizedBox(width: 12),
          Expanded(child: Text(register ? l10n.register : l10n.login, style: t.textTheme.headlineSmall)),
          IconButton(tooltip: l10n.actionClose, onPressed: widget.onClose, icon: const Icon(Icons.close)),
        ]),
        const SizedBox(height: 24),
        TextField(controller: email, keyboardType: TextInputType.emailAddress, decoration: InputDecoration(labelText: l10n.email, prefixIcon: const Icon(Icons.alternate_email))),
        if (register) ...[
          const SizedBox(height: 12),
          Row(children: [
            Expanded(
              child: TextField(
                controller: code,
                keyboardType: TextInputType.number,
                maxLength: 6,
                decoration: InputDecoration(labelText: l10n.emailCode, prefixIcon: const Icon(Icons.verified_outlined), counterText: ''),
              ),
            ),
            const SizedBox(width: 12),
            SizedBox(
              height: 52,
              child: FilledButton.tonal(
                onPressed: sendingCode || resendIn > 0 ? null : _sendCode,
                child: sendingCode
                    ? const SizedBox(width: 18, height: 18, child: CircularProgressIndicator(strokeWidth: 2))
                    : Text(resendIn > 0 ? l10n.resendInSeconds(resendIn) : l10n.getCode),
              ),
            ),
          ]),
        ],
        const SizedBox(height: 12),
        TextField(
          controller: pw,
          obscureText: true,
          onSubmitted: (_) => _submit(),
          decoration: InputDecoration(labelText: register ? l10n.passwordMin8 : l10n.password, prefixIcon: const Icon(Icons.lock_outline)),
        ),
        if (register) ...[
          const SizedBox(height: 12),
          TextField(controller: name, decoration: InputDecoration(labelText: l10n.nickname, prefixIcon: const Icon(Icons.person_outline))),
          const SizedBox(height: 12),
          Row(children: [
            Expanded(child: TextField(controller: grade, decoration: InputDecoration(labelText: l10n.grade, hintText: '2024'))),
            const SizedBox(width: 12),
            Expanded(child: TextField(controller: major, decoration: InputDecoration(labelText: l10n.major))),
          ]),
          const SizedBox(height: 8),
          CheckboxListTile(
            contentPadding: EdgeInsets.zero,
            value: agree,
            onChanged: (v) => setState(() => agree = v ?? false),
            controlAffinity: ListTileControlAffinity.leading,
            title: Text(l10n.agreePrivacy, style: const TextStyle(fontSize: 14)),
            subtitle: Text(l10n.privacyAgreeDetail, style: const TextStyle(fontSize: 12)),
          ),
        ],
        if (!kIsWeb) ...[
          const SizedBox(height: 12),
          ExpansionTile(
            tilePadding: EdgeInsets.zero,
            title: Text(l10n.serverAddress, style: const TextStyle(fontSize: 14)),
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
          child: busy
              ? const SizedBox(height: 20, width: 20, child: CircularProgressIndicator(strokeWidth: 2))
              : Text(register ? l10n.registerAndStart : l10n.login),
        ),
        const SizedBox(height: 8),
        TextButton(
          onPressed: () => setState(() => register = !register),
          child: Text(register ? l10n.haveAccountSignIn : l10n.noAccountRegister),
        ),
      ]),
    );

    final content = SingleChildScrollView(padding: const EdgeInsets.all(24), child: form);
    return Dialog(child: content);
  }
}
