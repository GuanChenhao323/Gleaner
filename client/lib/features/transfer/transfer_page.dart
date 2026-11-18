import 'dart:async';

import 'package:crypto/crypto.dart';
import 'package:file_picker/file_picker.dart';
import 'package:flutter/foundation.dart';
import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:go_router/go_router.dart';
import 'package:mobile_scanner/mobile_scanner.dart';
import 'package:qr_flutter/qr_flutter.dart';
import 'package:url_launcher/url_launcher.dart';

import '../../core/api.dart';
import '../../core/session.dart';
import '../../widgets/common.dart';

const _chunk = 512 * 1024;

/// 跨设备扫码传输：电脑生成二维码，手机扫码配对后双向传文件；分块上传、断点续传、SHA-256 校验。
class TransferPage extends ConsumerStatefulWidget {
  final String? code;
  const TransferPage({super.key, this.code});
  @override
  ConsumerState<TransferPage> createState() => _TransferPageState();
}

class _TransferPageState extends ConsumerState<TransferPage> {
  String? code;
  String? token;
  String status = '';
  List<Map<String, dynamic>> files = [];
  final progress = <String, double>{};
  Timer? poll;
  final codeCtl = TextEditingController();
  String? error;

  @override
  void initState() {
    super.initState();
    if (widget.code != null) _join(widget.code!);
  }

  @override
  void dispose() {
    poll?.cancel();
    super.dispose();
  }

  Api get api => ref.read(apiProvider);

  Future<void> _create() async {
    try {
      final r = await api.transferCreate();
      setState(() {
        code = r['code'] as String;
        token = r['token'] as String;
        status = 'waiting';
      });
      _startPoll();
    } on ApiException catch (e) {
      setState(() => error = e.message);
    }
  }

  Future<void> _join(String c) async {
    try {
      final r = await api.transferJoin(c.toUpperCase(), kIsWeb ? '浏览器' : defaultTargetPlatform.name);
      setState(() {
        code = r['code'] as String;
        token = r['token'] as String;
        status = 'paired';
        error = null;
      });
      _startPoll();
    } on ApiException catch (e) {
      setState(() => error = e.message);
    }
  }

  void _startPoll() {
    poll?.cancel();
    _refresh();
    poll = Timer.periodic(const Duration(seconds: 2), (_) => _refresh());
  }

  Future<void> _refresh() async {
    if (code == null) return;
    try {
      final r = await api.transferStatus(code!, token);
      if (!mounted) return;
      setState(() {
        status = r['status'] as String;
        files = (r['files'] as List).map((e) => Map<String, dynamic>.from(e as Map)).toList();
      });
    } catch (_) {}
  }

  Future<void> _send() async {
    final picked = await FilePicker.pickFiles();
    for (final f in picked) {
      final bytes = await f.xFile.readAsBytes();
      await _upload(f.name, bytes);
    }
  }

  /// 分块上传；中断后先查询服务器已接收的字节数，再从该位置继续。
  Future<void> _upload(String name, Uint8List data) async {
    final sha = sha256.convert(data).toString();
    final decl = await api.transferDeclare(code!, token, {'name': name, 'size': data.length, 'sha256': sha});
    final fid = decl['id'] as int;
    var offset = 0;
    var retries = 0;
    while (offset < data.length) {
      final end = (offset + _chunk).clamp(0, data.length);
      try {
        final r = await api.transferChunk(code!, token, fid, data.sublist(offset, end), offset, data.length);
        offset = r['received'] as int;
        retries = 0;
        if (r['status'] == 'corrupt' && mounted) toast(context, '「$name」校验失败，请重新发送', error: true);
      } on ApiException catch (_) {
        if (++retries > 8) {
          if (mounted) toast(context, '网络中断，「$name」已暂停', error: true);
          return;
        }
        await Future<void>.delayed(Duration(seconds: retries));
        final st = await api.transferFile(code!, token, fid);
        offset = st['received'] as int; // 断点续传
      }
      if (mounted) setState(() => progress['$fid'] = offset / data.length);
    }
    await _refresh();
  }

  @override
  Widget build(BuildContext context) {
    final cs = Theme.of(context).colorScheme;
    final server = ref.watch(sessionProvider).server;
    return Scaffold(
      appBar: AppBar(),
      body: Align(
        alignment: Alignment.topCenter,
        child: ConstrainedBox(
          constraints: const BoxConstraints(maxWidth: 720),
          child: ListView(padding: const EdgeInsets.all(16), children: [
            if (code == null) ...[
              Card(
                child: Padding(
                  padding: const EdgeInsets.all(20),
                  child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
                    Text('在电脑上发起', style: Theme.of(context).textTheme.titleMedium),
                    const SizedBox(height: 6),
                    Text('生成二维码，用手机扫码后即可互传文件。配对码 30 分钟内有效。', style: TextStyle(color: cs.onSurfaceVariant)),
                    const SizedBox(height: 14),
                    FilledButton.icon(onPressed: _create, icon: const Icon(Icons.qr_code_2), label: const Text('生成二维码')),
                  ]),
                ),
              ),
              const SizedBox(height: 12),
              Card(
                child: Padding(
                  padding: const EdgeInsets.all(20),
                  child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
                    Text('加入已有会话', style: Theme.of(context).textTheme.titleMedium),
                    const SizedBox(height: 12),
                    Row(children: [
                      Expanded(child: TextField(controller: codeCtl, textCapitalization: TextCapitalization.characters, decoration: const InputDecoration(hintText: '输入 6 位配对码'))),
                      const SizedBox(width: 10),
                      FilledButton(onPressed: () => _join(codeCtl.text.trim()), child: const Text('加入')),
                    ]),
                    if (!kIsWeb || defaultTargetPlatform == TargetPlatform.android || defaultTargetPlatform == TargetPlatform.iOS) ...[
                      const SizedBox(height: 10),
                      OutlinedButton.icon(onPressed: () => _scan(context), icon: const Icon(Icons.qr_code_scanner), label: const Text('扫描二维码')),
                    ],
                  ]),
                ),
              ),
            ] else ...[
              Card(
                child: Padding(
                  padding: const EdgeInsets.all(20),
                  child: Column(children: [
                    if (status == 'waiting') ...[
                      Container(
                        padding: const EdgeInsets.all(12),
                        decoration: BoxDecoration(color: Colors.white, borderRadius: BorderRadius.circular(16)),
                        child: QrImageView(data: '$server/#/transfer/$code', size: 220),
                      ),
                      const SizedBox(height: 12),
                      Text('用手机扫码，或在手机上输入配对码', style: TextStyle(color: cs.onSurfaceVariant)),
                    ] else
                      Icon(Icons.devices, size: 56, color: cs.primary),
                    const SizedBox(height: 8),
                    SelectableText(code!, style: Theme.of(context).textTheme.headlineMedium?.copyWith(letterSpacing: 6, fontWeight: FontWeight.w800)),
                    const SizedBox(height: 8),
                    Pill(status == 'paired' ? '已配对' : '等待配对…', color: status == 'paired' ? Colors.green : cs.outline, icon: status == 'paired' ? Icons.link : Icons.hourglass_top),
                    const SizedBox(height: 16),
                    FilledButton.icon(onPressed: _send, icon: const Icon(Icons.upload_file), label: const Text('发送文件')),
                  ]),
                ),
              ),
              SectionHeader('文件', trailing: '${files.length}'),
              if (files.isEmpty) Padding(padding: const EdgeInsets.all(16), child: Text('还没有文件', style: TextStyle(color: cs.onSurfaceVariant))),
              for (final f in files)
                Card(
                  margin: const EdgeInsets.only(bottom: 8),
                  child: ListTile(
                    leading: Icon(f['status'] == 'done' ? Icons.task_alt : (f['status'] == 'corrupt' ? Icons.gpp_bad : Icons.cloud_upload_outlined),
                        color: f['status'] == 'done' ? Colors.green : (f['status'] == 'corrupt' ? cs.error : null)),
                    title: Text(f['name'].toString()),
                    subtitle: f['status'] == 'uploading'
                        ? LinearProgressIndicator(value: progress['${f['id']}'] ?? ((f['received'] as int) / ((f['size'] as int) == 0 ? 1 : f['size'] as int)))
                        : Text('${((f['size'] as int) / 1024).toStringAsFixed(1)} KB · SHA-256 ${f['sha256'].toString().substring(0, 12)}…'),
                    trailing: f['status'] == 'done'
                        ? IconButton(icon: const Icon(Icons.download), onPressed: () => launchUrl(Uri.parse(api.transferDownloadUrl(code!, token!, f['id'] as int))))
                        : null,
                  ),
                ),
            ],
            if (error != null) Padding(padding: const EdgeInsets.all(12), child: Text(error!, style: TextStyle(color: cs.error))),
          ]),
        ),
      ),
    );
  }

  Future<void> _scan(BuildContext context) async {
    final result = await showDialog<String>(
      context: context,
      builder: (c) => Dialog(
        clipBehavior: Clip.antiAlias,
        child: SizedBox(
          width: 360,
          height: 420,
          child: MobileScanner(
            onDetect: (cap) {
              final v = cap.barcodes.firstOrNull?.rawValue;
              if (v != null) Navigator.pop(c, v);
            },
          ),
        ),
      ),
    );
    if (result == null) return;
    final m = RegExp(r'transfer/([A-Z0-9]{6})').firstMatch(result);
    if (m != null) {
      if (context.mounted) context.go('/transfer/${m.group(1)}');
      _join(m.group(1)!);
    }
  }
}
