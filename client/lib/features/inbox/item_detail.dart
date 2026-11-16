import 'document_trash_button.dart';
import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:go_router/go_router.dart';
import 'package:url_launcher/url_launcher.dart';

import '../../core/format.dart';
import '../../core/models.dart';
import '../../core/providers.dart';
import '../../core/session.dart';
import '../../core/store.dart';
import '../../theme.dart';
import '../../widgets/common.dart';
import '../sources/browser_monitors.dart';
import '../sources/reading_source.dart';
import 'source_changes.dart';
import 'item_load_failure.dart';
import 'web_capture_details.dart';

class ItemDetail extends ConsumerStatefulWidget {
  final int id;
  final bool embedded;
  const ItemDetail({super.key, required this.id, this.embedded = false});

  @override
  ConsumerState<ItemDetail> createState() => _ItemDetailState();
}

class _ItemDetailState extends ConsumerState<ItemDetail> {
  Object? _loadError;
  bool _detailLoading = true;
  @override
  void initState() {
    super.initState();
    _load();
  }

  @override
  void didUpdateWidget(covariant ItemDetail old) {
    super.didUpdateWidget(old);
    if (old.id != widget.id) _load();
  }

  Future<void> _load() async {
    setState(() { _detailLoading = true; _loadError = null; });
    final store = ref.read(feedProvider.notifier);
    final it = ref.read(feedProvider).items[widget.id];
    if (it != null && !it.state.read) store.setState(it, read: true);
    try {
      await store.loadDetail(widget.id);
    } catch (e) {
      if (mounted) setState(() => _loadError = e);
    } finally {
      if (mounted) setState(() => _detailLoading = false);
    }
  }

  @override
  Widget build(BuildContext context) {
    final item = ref.watch(feedProvider.select((s) => s.items[widget.id]));
    if (item == null) {
      return Scaffold(body: _detailLoading
          ? const Center(child: CircularProgressIndicator())
          : ItemLoadFailure(error: _loadError, email: ref.watch(sessionProvider).me?.email ?? '',
              onRetry: _load, onSources: () => context.go('/sources')));
    }
    final t = Theme.of(context);
    final cs = t.colorScheme;
    final store = ref.read(feedProvider.notifier);
    final courseColor = Brand.course(item.course);
    final body = ListView(
      padding: const EdgeInsets.fromLTRB(24, 8, 24, 40),
      children: [
        Wrap(spacing: 8, runSpacing: 8, crossAxisAlignment: WrapCrossAlignment.center, children: [
          Pill(item.raw['web_capture'] is Map ? '网页资料' : kindLabel(item.kind), color: courseColor, icon: kindIcon(item.kind)),
          if (item.course.isNotEmpty) CourseTag(item.course),
          if (item.priority != 'low') Pill('${priorityLabel(item.priority)} · ${item.score} 分', color: item.priority == 'urgent' ? Brand.urgent : cs.primary),
          if (item.deleted) Pill('来源已删除', color: cs.error, icon: Icons.delete_outline),
        ]),
        const SizedBox(height: 14),
        SelectableText(item.title, style: t.textTheme.headlineSmall?.copyWith(fontWeight: FontWeight.w800, height: 1.3)),
        if (item.rawTitle != item.title && item.rawTitle.isNotEmpty) ...[
          const SizedBox(height: 4),
          Text('原标题：${item.rawTitle}', style: t.textTheme.bodySmall?.copyWith(color: cs.onSurfaceVariant)),
        ],
        const SizedBox(height: 16),
        if (item.deadline != null) _DeadlineCard(item: item),
        if (item.importantChange && item.changeNote.isNotEmpty) ...[
          const SizedBox(height: 12),
          Container(
            padding: const EdgeInsets.all(14),
            decoration: BoxDecoration(color: cs.tertiaryContainer, borderRadius: BorderRadius.circular(16)),
            child: Row(children: [
              Icon(Icons.auto_awesome, color: cs.onTertiaryContainer),
              const SizedBox(width: 10),
              Expanded(child: Text(item.changeNote, style: TextStyle(color: cs.onTertiaryContainer, fontWeight: FontWeight.w700))),
            ]),
          ),
        ],
        if (item.summary.isNotEmpty) ...[
          const SectionHeader('摘要'),
          Card(
            child: Padding(
              padding: const EdgeInsets.all(16),
              child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
                Text(item.summary, style: t.textTheme.bodyLarge?.copyWith(height: 1.6)),
                const SizedBox(height: 8),
                Text(item.raw['summary_by'] == 'llm' ? '由大模型生成 · 仅作导读，以原文为准' : '规则提取 · 仅作导读，以原文为准',
                    style: t.textTheme.labelSmall?.copyWith(color: cs.onSurfaceVariant)),
              ]),
            ),
          ),
        ],
        if (item.requirements.isNotEmpty) ...[
          const SectionHeader('提交要求'),
          Card(child: ListTile(leading: const Icon(Icons.rule), title: Text(item.requirements))),
        ],
        if (item.attachments.isNotEmpty) ...[
          SectionHeader('附件', trailing: '${item.attachments.length}'),
          Card(
            child: Column(children: [
              for (final a in item.attachments)
                ListTile(
                  leading: const Icon(Icons.attach_file),
                  title: Text(a.name),
                  subtitle: a.size != null ? Text('${(a.size! / 1024).toStringAsFixed(1)} KB') : null,
                  trailing: a.url.isEmpty ? null : const Icon(Icons.open_in_new, size: 18),
                  onTap: a.url.isEmpty ? null : () => launchUrl(Uri.parse(a.url)),
                ),
            ]),
          ),
        ],
        if (item.raw['web_capture'] is Map)
          WebCaptureDetails(Map<String, dynamic>.from(item.raw['web_capture'] as Map), hasReadingSource: item.raw['reading_source'] is Map),
        if (item.body.isNotEmpty) ...[
          const SectionHeader('原文内容'),
          Card(child: Padding(padding: const EdgeInsets.all(16), child: SelectableText(item.body, style: t.textTheme.bodyMedium?.copyWith(height: 1.7)))),
        ],
        if ((item.raw['source_fields'] as Map? ?? {}).isNotEmpty) ...[
          const SectionHeader('来源原始字段'),
          Card(child: Padding(padding: const EdgeInsets.all(12), child: SelectableText((item.raw['source_fields'] as Map).entries.map((e) => '${const {'course':'课程','semester':'学期','week':'周次','weekday':'星期','period':'节次','datetime_text':'原始时间','office':'办公室','department':'部门','role':'角色','phone':'电话','email':'邮箱','requirements':'要求','subtype':'资料类别'}[e.key] ?? e.key}：${e.value}').join('\n')))),
        ],
        if (item.raw['reading_source'] is Map) ...[
          const SectionHeader('条件来源检查'),
          Text(readingResultLabel('${(item.raw['reading_source'] as Map)['last_result']}')),
          TextButton(onPressed: () => context.push('/sources/${(item.raw['reading_source'] as Map)['id']}'), child: const Text('查看来源与检查设置')),
        ] else if (item.raw['browser_monitor'] is Map) ...[
          const SectionHeader('浏览器来源检查'),
          Text((item.raw['browser_monitor'] as Map)['supported'] != true ? '仅保存快照 · 暂不支持后台检查' : browserCheckLabel('${(item.raw['browser_monitor'] as Map)['last_result']}')),
        ],
        if (item.state.note.isNotEmpty) ...[
          const SectionHeader('我的备注（来源更新不会覆盖）'),
          SelectableText(item.state.note),
        ],
        _History(id: item.id),
        const SectionHeader('来源与可靠性'),
        Card(
          child: Column(children: [
            ListTile(
              leading: Icon(sourceIcon(item.source?.type ?? '')),
              title: Text(item.source?.name ?? '未知来源'),
              subtitle: Text('${item.raw['reading_source'] is Map ? '最后成功检查' : item.raw['web_capture'] is Map ? '最后保存' : '最后成功检查'}：${relative(tsToDate(item.raw['reading_source'] is Map ? ((item.raw['reading_source'] as Map)['last_success_at'] as num?)?.toDouble() : item.source?.lastSuccessAt))}'),
            ),
            if (item.channels.length > 1)
              ListTile(
                leading: const Icon(Icons.merge_type),
                title: const Text('跨渠道合并'),
                subtitle: Text('同一事项出现在 ${item.channels.map(channelLabel).join('、')}，已合并为一条'),
              ),
            if (item.reasons.isNotEmpty)
              ListTile(leading: const Icon(Icons.insights_outlined), title: const Text('为什么推给你'), subtitle: Text(item.reasons.join(' · '))),
          ]),
        ),
        const SizedBox(height: 16),
        Wrap(spacing: 10, runSpacing: 10, children: [
          if (item.url.isNotEmpty) FilledButton.icon(onPressed: () => launchUrl(Uri.parse(item.url)), icon: const Icon(Icons.open_in_new), label: const Text('打开原文')),
          OutlinedButton.icon(
            onPressed: () => store.setState(item, todo: item.state.todo == 'todo' ? '' : 'todo'),
            icon: Icon(item.state.todo == 'todo' ? Icons.remove_done : Icons.playlist_add),
            label: Text(item.state.todo == 'todo' ? '移出待办' : '加入待办'),
          ),
          if (item.isAssignment)
            OutlinedButton.icon(
              onPressed: () => store.setState(item, todo: item.isDone ? 'todo' : 'done'),
              icon: Icon(item.isDone ? Icons.undo : Icons.task_alt),
              label: Text(item.isDone ? '标为未完成' : '标为已完成'),
            ),
          OutlinedButton.icon(
            onPressed: () async {
              await store.notImportant(item);
              if (context.mounted) toast(context, '已降低该来源的权重，系统会逐步贴合你的习惯');
            },
            icon: const Icon(Icons.thumb_down_alt_outlined),
            label: const Text('不重要'),
          ),
          TextButton.icon(
            onPressed: () {
              Clipboard.setData(ClipboardData(text: '${item.title}\n${item.url}'));
              toast(context, '已复制标题与链接');
            },
            icon: const Icon(Icons.link),
            label: const Text('复制链接'),
          ),
        ]),
      ],
    );
    return Scaffold(
      backgroundColor: widget.embedded ? cs.surface : null,
      appBar: AppBar(
        automaticallyImplyLeading: !widget.embedded,
        title: Text(item.raw['web_capture'] is Map ? '网页资料' : kindLabel(item.kind)),
        actions: [
          DocumentTrashButton(item: item),
          IconButton(
            tooltip: item.state.starred ? '取消收藏' : '收藏',
            icon: Icon(item.state.starred ? Icons.star_rounded : Icons.star_outline_rounded, color: item.state.starred ? Brand.wheat : null),
            onPressed: () => store.setState(item, starred: !item.state.starred),
          ),
          IconButton(tooltip: '标为未读', icon: const Icon(Icons.mark_email_unread_outlined), onPressed: () => store.setState(item, read: false)),
          const SizedBox(width: 8),
        ],
      ),
      body: Align(alignment: Alignment.topCenter, child: ConstrainedBox(constraints: const BoxConstraints(maxWidth: 820), child: body)),
    );
  }
}

class _DeadlineCard extends StatelessWidget {
  final Item item;
  const _DeadlineCard({required this.item});
  @override
  Widget build(BuildContext context) {
    final due = item.deadline!;
    final cs = Theme.of(context).colorScheme;
    final u = urgencyOf(due);
    final c = item.isDone ? Brand.ok : urgencyColor(context, u);
    return Container(
      padding: const EdgeInsets.all(18),
      decoration: BoxDecoration(
        borderRadius: BorderRadius.circular(20),
        gradient: LinearGradient(colors: [c.withValues(alpha: 0.16), c.withValues(alpha: 0.04)], begin: Alignment.topLeft, end: Alignment.bottomRight),
        border: Border.all(color: c.withValues(alpha: 0.35)),
      ),
      child: Row(children: [
        Container(
          width: 58,
          padding: const EdgeInsets.symmetric(vertical: 8),
          decoration: BoxDecoration(color: cs.surface, borderRadius: BorderRadius.circular(14)),
          child: Column(children: [
            Text('${due.month}月', style: TextStyle(color: c, fontWeight: FontWeight.w700, fontSize: 12)),
            Text('${due.day}', style: TextStyle(fontSize: 26, fontWeight: FontWeight.w800, color: cs.onSurface, height: 1.1)),
            Text(weekday(due), style: TextStyle(fontSize: 11, color: cs.onSurfaceVariant)),
          ]),
        ),
        const SizedBox(width: 16),
        Expanded(
          child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
            Text(item.isDone ? '已完成' : countdown(due), style: Theme.of(context).textTheme.titleLarge?.copyWith(color: c, fontWeight: FontWeight.w800)),
            const SizedBox(height: 4),
            Text('截止于 ${absolute(due)}', style: TextStyle(color: cs.onSurfaceVariant)),
            if (item.state.deadlineOverride != null) Text('（已手动修正）', style: TextStyle(color: cs.onSurfaceVariant, fontSize: 12)),
          ]),
        ),
      ]),
    );
  }
}

class _History extends ConsumerWidget {
  final int id;
  const _History({required this.id});

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final v = ref.watch(versionsProvider(id));
    return v.when(
      loading: () => const SizedBox.shrink(),
      error: (_, _) => const SizedBox.shrink(),
      data: (versions) {
        if (versions.length <= 1) return const SizedBox.shrink();
        final cs = Theme.of(context).colorScheme;
        return Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
          SectionHeader('修改历史', trailing: '${versions.length} 个版本'),
          Card(
            child: Padding(
              padding: const EdgeInsets.symmetric(vertical: 8),
              child: Column(children: [
                for (var i = 0; i < versions.length; i++)
                  IntrinsicHeight(
                    child: Row(crossAxisAlignment: CrossAxisAlignment.stretch, children: [
                      const SizedBox(width: 18),
                      Column(children: [
                        Container(
                          margin: const EdgeInsets.only(top: 16),
                          width: 12,
                          height: 12,
                          decoration: BoxDecoration(color: versions[i].important ? Brand.wheat : cs.outline, shape: BoxShape.circle),
                        ),
                        if (i < versions.length - 1) Expanded(child: Container(width: 2, color: cs.outlineVariant)),
                      ]),
                      const SizedBox(width: 12),
                      Expanded(
                        child: Padding(
                          padding: const EdgeInsets.fromLTRB(0, 10, 16, 10),
                          child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
                            Text(
                              versions[i].version == 1 ? '首次发现' : (versions[i].note.isEmpty ? '内容更新' : versions[i].note),
                              style: TextStyle(fontWeight: versions[i].important ? FontWeight.w700 : FontWeight.w500),
                            ),
                            Text('v${versions[i].version} · ${relative(tsToDate(versions[i].detectedAt))}', style: TextStyle(color: cs.onSurfaceVariant, fontSize: 12)),
                            if (versions[i].changed.isNotEmpty) SourceChanges(versions[i].changed),
                          ]),
                        ),
                      ),
                    ]),
                  ),
              ]),
            ),
          ),
        ]);
      },
    );
  }
}
