import 'package:flutter/material.dart';

/// A server-signed impact snapshot. UI cannot choose arbitrary item IDs to erase.
class SourcePurgePlan {
  final Map<String, dynamic> plan;
  final String token;
  SourcePurgePlan.fromJson(Map<String, dynamic> value)
    : plan = Map<String, dynamic>.from(
        value['plan'] is Map ? value['plan'] as Map : {},
      ),
      token = value['token'] is String ? value['token'] as String : '' {
    if (plan['source_id'] is! int ||
        plan['revision'] is! int ||
        plan['generation'] is! int ||
        plan['version_count'] is! int ||
        plan['check_count'] is! int ||
        plan['expires_at'] is! num ||
        plan['items'] is! List ||
        plan['affected'] is! List ||
        !RegExp(r'^[0-9a-f]{64}$').hasMatch(token)) {
      throw const FormatException('永久删除范围响应异常');
    }
    for (final item in plan['items'] as List) {
      if (item is! Map ||
          item['id'] is! int ||
          item['id'] <= 0 ||
          item['version'] is! int ||
          item['version'] <= 0) {
        throw const FormatException('删除资料清单异常');
      }
    }
    if (sourceId <= 0 ||
        generation < 0 ||
        versions < 0 ||
        checks < 0 ||
        itemIds.toSet().length != itemIds.length) {
      throw const FormatException('永久删除范围响应异常');
    }
    for (final rule in plan['affected'] as List) {
      if (rule is! Map ||
          rule['id'] is! int ||
          rule['id'] <= 0 ||
          rule['revision'] is! int ||
          rule['revision'] <= 0 ||
          rule['remaining'] is! int ||
          rule['remaining'] < 0) {
        throw const FormatException('关联规则清单异常');
      }
    }
  }
  int get sourceId => plan['source_id'] as int;
  int get generation => plan['generation'] as int;
  int get versions => plan['version_count'] as int;
  int get checks => plan['check_count'] as int;
  List<int> get itemIds =>
      (plan['items'] as List).map((v) => (v as Map)['id'] as int).toList();
  int get removedRules =>
      (plan['affected'] as List).where((v) => v['remaining'] == 0).length;
  int get pausedRules =>
      (plan['affected'] as List).where((v) => v['remaining'] != 0).length;
  Map<String, dynamic> get body => {
    'plan': plan,
    'token': token,
    'confirm': true,
  };
}

class SourcePurgeResult {
  final List<int> itemIds;
  final int generation;
  SourcePurgeResult.fromJson(Map<String, dynamic> value)
    : itemIds = (value['item_ids'] as List).cast<int>(),
      generation = value['generation'] as int;
}

/// The irreversible action requires a separate confirmation with actual impact counts.
class SourcePurgeDialog extends StatefulWidget {
  final SourcePurgePlan plan;
  final String title;
  const SourcePurgeDialog({super.key, required this.plan, required this.title});
  @override
  State<SourcePurgeDialog> createState() => _SourcePurgeDialogState();
}

class _SourcePurgeDialogState extends State<SourcePurgeDialog> {
  bool accepted = false;
  @override
  Widget build(BuildContext context) {
    final p = widget.plan;
    return AlertDialog(
      title: Text('彻底删除「${widget.title}」？'),
      content: SizedBox(
        width: 460,
        child: SingleChildScrollView(
          child: Column(
            mainAxisSize: MainAxisSize.min,
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              Text(
                '将永久删除此来源、${p.itemIds.length} 份关联资料、${p.versions} 个历史版本及 ${p.checks} 条检查记录。包括收件箱和回收站中的关联资料、个人备注与状态。',
              ),
              const SizedBox(height: 12),
              if (p.removedRules > 0)
                Text('另有 ${p.removedRules} 条规则只引用这些资料，将一并移除。'),
              if (p.pausedRules > 0)
                Text('另有 ${p.pausedRules} 条规则包含这些资料，将暂停并要求重新提取；其余资料保留。'),
              const Text(
                '该账号之前未完成的采集预览将统一失效，需要重新提取。其他已保存资料保留。插件离线时，旧缓存会在重新连接后清理。',
              ),
              const SizedBox(height: 12),
              const Text('此操作不可恢复。之后可以重新采集同一网页和条件，作为新资料保存。'),
              CheckboxListTile(
                contentPadding: EdgeInsets.zero,
                value: accepted,
                onChanged: (v) => setState(() => accepted = v ?? false),
                title: const Text('我确认永久删除上述资料和历史版本'),
              ),
            ],
          ),
        ),
      ),
      actions: [
        TextButton(
          onPressed: () => Navigator.pop(context, false),
          child: const Text('取消'),
        ),
        FilledButton(
          style: FilledButton.styleFrom(
            backgroundColor: Theme.of(context).colorScheme.error,
          ),
          onPressed: accepted ? () => Navigator.pop(context, true) : null,
          child: const Text('确认彻底删除'),
        ),
      ],
    );
  }
}
