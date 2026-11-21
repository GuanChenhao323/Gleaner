import 'dart:convert';

import 'package:file_picker/file_picker.dart';
import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:uuid/uuid.dart';

import '../../core/api.dart';
import '../../core/format.dart';
import '../../core/models.dart';
import '../../core/session.dart';
import '../../l10n/app_localizations.dart';
import '../../widgets/common.dart';

class ComposePage extends ConsumerStatefulWidget {
  const ComposePage({super.key});
  @override
  ConsumerState<ComposePage> createState() => _ComposePageState();
}

class _ComposePageState extends ConsumerState<ComposePage> {
  final to = TextEditingController();
  final cc = TextEditingController();
  final subject = TextEditingController();
  final body = TextEditingController();
  final files = <(String, List<int>)>[];
  // 幂等键：同一封草稿多次点击“发送”只会发出一封
  String key = const Uuid().v4();
  bool sending = false;
  List<Map<String, dynamic>> sent = [];

  @override
  void initState() {
    super.initState();
    _loadSent();
  }

  Future<void> _loadSent() async {
    try {
      final s = await ref.read(apiProvider).sentMails();
      if (mounted) setState(() => sent = s);
    } catch (_) {}
  }

  List<String> _split(String s) => s.split(RegExp(r'[,，;；\s]+')).where((e) => e.contains('@')).toList();

  Future<void> _pick() async {
    final picked = await FilePicker.pickFiles();
    for (final f in picked) {
      final bytes = await f.xFile.readAsBytes();
      setState(() => files.add((f.name, bytes)));
    }
  }

  Future<void> _send() async {
    if (_split(to.text).isEmpty) {
      toast(context, AppLocalizations.of(context).pleaseFillRecipient, error: true);
      return;
    }
    setState(() => sending = true);
    try {
      final r = await ref.read(apiProvider).sendMail({
        'to': _split(to.text),
        'cc': _split(cc.text),
        'subject': subject.text,
        'text': body.text,
        'attachments': [for (final (n, b) in files) {'filename': n, 'content_b64': base64Encode(b), 'mime': 'application/octet-stream'}],
      }, key);
      if (!mounted) return;
      if (r['status'] == 'sent') {
      toast(context, r['duplicate'] == true ? AppLocalizations.of(context).duplicateSend : AppLocalizations.of(context).sent);
        setState(() {
          to.clear();
          cc.clear();
          subject.clear();
          body.clear();
          files.clear();
          key = const Uuid().v4();
        });
      } else {
      toast(context, AppLocalizations.of(context).sendFailed('${r['error'] ?? r['status']}'), error: true);
      }
      _loadSent();
    } on ApiException catch (e) {
      if (mounted) toast(context, e.message, error: true);
    } finally {
      if (mounted) setState(() => sending = false);
    }
  }

  @override
  Widget build(BuildContext context) {
    final cs = Theme.of(context).colorScheme;
    return Scaffold(
      appBar: AppBar(actions: [
        IconButton(tooltip: AppLocalizations.of(context).addAttachment, onPressed: _pick, icon: const Icon(Icons.attach_file)),
        Padding(
          padding: const EdgeInsets.only(right: 12),
          child: FilledButton.icon(
            onPressed: sending ? null : _send,
            icon: sending ? const SizedBox(width: 16, height: 16, child: CircularProgressIndicator(strokeWidth: 2)) : const Icon(Icons.send),
            label: Text(AppLocalizations.of(context).send),
          ),
        ),
      ]),
      body: Align(
        alignment: Alignment.topCenter,
        child: ConstrainedBox(
          constraints: const BoxConstraints(maxWidth: 820),
          child: ListView(padding: const EdgeInsets.all(16), children: [
            TextField(controller: to, decoration: InputDecoration(labelText: AppLocalizations.of(context).to, prefixIcon: const Icon(Icons.person_outline))),
            const SizedBox(height: 10),
            TextField(controller: cc, decoration: InputDecoration(labelText: AppLocalizations.of(context).ccOptional, prefixIcon: const Icon(Icons.people_outline))),
            const SizedBox(height: 10),
            TextField(controller: subject, decoration: InputDecoration(labelText: AppLocalizations.of(context).subject, prefixIcon: const Icon(Icons.subject))),
            const SizedBox(height: 10),
            TextField(controller: body, minLines: 10, maxLines: 24, decoration: InputDecoration(hintText: AppLocalizations.of(context).bodyHint, alignLabelWithHint: true)),
            if (files.isNotEmpty) ...[
              const SizedBox(height: 10),
              Wrap(spacing: 8, runSpacing: 8, children: [
                for (var i = 0; i < files.length; i++)
                  InputChip(
                    avatar: const Icon(Icons.insert_drive_file_outlined, size: 18),
                    label: Text('${files[i].$1} · ${(files[i].$2.length / 1024).toStringAsFixed(0)} KB'),
                    onDeleted: () => setState(() => files.removeAt(i)),
                  ),
              ]),
            ],
            if (sent.isNotEmpty) ...[
              SectionHeader(AppLocalizations.of(context).recentSent),
              Card(
                child: Column(children: [
                  for (final m in sent.take(10))
                    ListTile(
                      leading: Icon(m['status'] == 'sent' ? Icons.check_circle : Icons.error_outline, color: m['status'] == 'sent' ? Colors.green : cs.error),
                      title: Text((m['subject'] ?? '').toString().isEmpty ? AppLocalizations.of(context).noSubject : m['subject'].toString()),
                      subtitle: Text('${(m['recipients'] as List).join(', ')} · ${relative(tsToDate(m['sent_at'] ?? m['created_at']), context)}'),
                    ),
                ]),
              ),
            ],
          ]),
        ),
      ),
    );
  }
}
