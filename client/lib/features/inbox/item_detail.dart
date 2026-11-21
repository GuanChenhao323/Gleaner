import 'document_trash_button.dart';
import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:go_router/go_router.dart';
import 'package:intl/intl.dart';
import 'package:url_launcher/url_launcher.dart';

import '../../core/api.dart';
import '../../core/format.dart';
import '../../core/models.dart';
import '../../core/providers.dart';
import '../../core/session.dart';
import '../../core/store.dart';
import '../../l10n/app_localizations.dart';
import '../../theme.dart';
import '../../widgets/common.dart';
import '../sources/browser_monitors.dart';
import '../sources/reading_source.dart';
import 'item_load_failure.dart';
import 'label_editor.dart';
import 'item_workbench.dart';
import 'source_changes.dart';
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
  bool _savingType = false;
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

  Future<void> _changeType(Item item, String type) async {
    if (_savingType || type == item.type) return;
    final messenger = ScaffoldMessenger.of(context);
    final router = GoRouter.of(context);
    final l10n = AppLocalizations.of(context);
    setState(() => _savingType = true);
    try {
      await ref.read(feedProvider.notifier).editFields(item, set: {'type': type});
      if (messenger.mounted) {
        messenger
          ..hideCurrentSnackBar()
          ..showSnackBar(SnackBar(
            content: Text(l10n.changedToType(typeLabel(type, context))),
            action: item.state.hidden || (type == 'todo' && item.isDone)
                ? null
                : SnackBarAction(label: l10n.goWorkbench, onPressed: () => router.go('/?type=$type&item=${item.id}')),
          ));
      }
    } catch (error) {
      if (mounted) toast(context, error is ApiException ? error.message : l10n.changeTypeFailed);
    } finally {
      if (mounted) setState(() => _savingType = false);
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
    final l10n = AppLocalizations.of(context);
    final t = Theme.of(context);
    final cs = t.colorScheme;
    final store = ref.read(feedProvider.notifier);
    final courseColor = Brand.course(item.course);
    final sfLabels = {
      'course': l10n.sfCourse,
      'semester': l10n.sfSemester,
      'week': l10n.sfWeek,
      'weekday': l10n.sfWeekday,
      'period': l10n.sfPeriod,
      'datetime_text': l10n.sfDatetime,
      'office': l10n.sfOffice,
      'department': l10n.sfDepartment,
      'role': l10n.sfRole,
      'phone': l10n.sfPhone,
      'email': l10n.sfEmail,
      'requirements': l10n.requirements,
      'subtype': l10n.sfSubtype,
    };
    final checkLabel = item.raw['reading_source'] is Map
        ? l10n.lastSuccessCheck
        : item.raw['web_capture'] is Map
            ? l10n.lastSaved
            : l10n.lastSuccessCheck;
    final body = ListView(
      padding: const EdgeInsets.fromLTRB(24, 8, 24, 40),
      children: [
        TypeStatusRow(item: item),
        const SizedBox(height: 8),
        Wrap(spacing: 8, runSpacing: 8, crossAxisAlignment: WrapCrossAlignment.center, children: [
          Pill(item.raw['web_capture'] is Map ? l10n.webMaterial : kindLabel(item.kind, context), color: courseColor, icon: kindIcon(item.kind)),
          if (item.course.isNotEmpty) CourseTag(item.course),
          if (item.priority != 'low')
            Pill('${priorityLabel(item.priority, context)} · ${l10n.scorePoints(item.score)}',
                color: item.priority == 'urgent' ? Brand.dueCritical : Brand.dueSoon),
          if (item.deleted) Pill(l10n.sourceDeleted, color: cs.error, icon: Icons.delete_outline),
          ..._itemLabelPills(ref, item),
        ]),
        const SizedBox(height: 14),
        SelectableText(item.title, style: t.textTheme.headlineSmall?.copyWith(fontWeight: FontWeight.w800, height: 1.3)),
        if (item.rawTitle != item.title && item.rawTitle.isNotEmpty) ...[
          const SizedBox(height: 4),
          Text(l10n.originalTitle(item.rawTitle), style: t.textTheme.bodySmall?.copyWith(color: cs.onSurfaceVariant)),
        ],
        ConflictBanner(item: item),
        const SizedBox(height: 16),
        if (item.isEvent) EventCard(item: item),
        if (item.deadline != null) _DeadlineCard(item: item),
        if (item.importantChange && item.changeNote.isNotEmpty) ...[
          const SizedBox(height: 12),
          Container(
            padding: const EdgeInsets.all(14),
            decoration: BoxDecoration(color: cs.tertiaryContainer, borderRadius: BorderRadius.circular(16)),
            child: Row(children: [
              Icon(Icons.auto_awesome, color: cs.onTertiaryContainer),
              const SizedBox(width: 10),
              Expanded(
                child: Text(
                  localizeChangeNote(item.changeNote, context),
                  style: TextStyle(color: cs.onTertiaryContainer, fontWeight: FontWeight.w700),
                ),
              ),
            ]),
          ),
        ],
        if (item.summary.isNotEmpty) ...[
          SectionHeader(l10n.summary),
          Card(
            child: Padding(
              padding: const EdgeInsets.all(16),
              child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
                Text(item.summary, style: t.textTheme.bodyLarge?.copyWith(height: 1.6)),
                const SizedBox(height: 8),
                Text(item.raw['summary_by'] == 'llm' ? l10n.summaryLlmHint : l10n.summaryRuleHint,
                    style: t.textTheme.labelSmall?.copyWith(color: cs.onSurfaceVariant)),
              ]),
            ),
          ),
        ],
        if (item.requirements.isNotEmpty) ...[
          SectionHeader(l10n.requirements),
          Card(child: ListTile(leading: const Icon(Icons.rule), title: Text(item.requirements))),
        ],
        if (item.attachments.isNotEmpty) ...[
          SectionHeader(l10n.attachments, trailing: '${item.attachments.length}'),
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
          SectionHeader(l10n.originalContent),
          Card(child: Padding(padding: const EdgeInsets.all(16), child: SelectableText(item.body, style: t.textTheme.bodyMedium?.copyWith(height: 1.7)))),
        ],
        if ((item.raw['source_fields'] as Map? ?? {}).isNotEmpty) ...[
          SectionHeader(l10n.sourceRawFields),
          Card(
            child: Padding(
              padding: const EdgeInsets.all(12),
              child: SelectableText(
                (item.raw['source_fields'] as Map).entries.map((e) => '${sfLabels[e.key] ?? e.key}：${e.value}').join('\n'),
              ),
            ),
          ),
        ],
        if (item.raw['reading_source'] is Map) ...[
          SectionHeader(l10n.conditionSourceCheck),
          Text(readingResultLabel('${(item.raw['reading_source'] as Map)['last_result']}', context)),
          TextButton(onPressed: () => context.push('/sources/${(item.raw['reading_source'] as Map)['id']}'), child: Text(l10n.viewSourceCheckSettings)),
        ] else if (item.raw['browser_monitor'] is Map) ...[
          SectionHeader(l10n.browserSourceCheck),
          Text((item.raw['browser_monitor'] as Map)['supported'] != true ? l10n.snapshotOnlyNoBg : browserCheckLabel('${(item.raw['browser_monitor'] as Map)['last_result']}', context)),
        ],
        if (item.state.note.isNotEmpty) ...[
          SectionHeader(l10n.myNotes),
          SelectableText(item.state.note),
        ],
        _History(id: item.id),
        if (item.raw['reading_source'] is! Map && item.raw['browser_monitor'] is! Map) ...[
          SectionHeader(l10n.sourceMonitor),
          MonitorCard(item: item),
        ],
        SectionHeader(l10n.sourceAndReliability),
        Card(
          child: Column(children: [
            ListTile(
              leading: Icon(sourceIcon(item.source?.type ?? '')),
              title: Text(item.source?.name ?? l10n.unknownSource),
              subtitle: Text('$checkLabel：${relative(tsToDate(item.raw['reading_source'] is Map ? ((item.raw['reading_source'] as Map)['last_success_at'] as num?)?.toDouble() : item.source?.lastSuccessAt), context)}'),
            ),
            if (item.channels.length > 1)
              ListTile(
                leading: const Icon(Icons.merge_type),
                title: Text(l10n.crossChannelMerge),
                subtitle: Text(l10n.sameItemMerged(item.channels.map((c) => channelLabel(c, context)).join('、'))),
              ),
            if (item.reasons.isNotEmpty)
              ListTile(
                leading: const Icon(Icons.insights_outlined),
                title: Text(l10n.whyPushed),
                subtitle: Text(localizeReasons(item.reasons, context)),
              ),
          ]),
        ),
        const SizedBox(height: 16),
        Wrap(spacing: 10, runSpacing: 10, children: [
          if (item.pageUrl.isNotEmpty)
            FilledButton.icon(
              onPressed: () => launchUrl(Uri.parse(item.pageUrl)),
              icon: const Icon(Icons.open_in_new),
              label: Text(l10n.openSource),
            ),
          // 按类型切换处理状态：待办完成、日程归档、通知已读（US05）
          OutlinedButton.icon(
            onPressed: () => store.toggleStatus(item),
            icon: Icon(typeIcon(item.type)),
            label: Text(statusAction(item, context)),
          ),
          OutlinedButton.icon(
            onPressed: () => showEditFields(context, ref, item),
            icon: const Icon(Icons.edit_outlined),
            label: Text(l10n.edit),
          ),
          OutlinedButton.icon(
            onPressed: () async {
              await store.notImportant(item);
              if (context.mounted) toast(context, l10n.notImportantToast);
            },
            icon: const Icon(Icons.thumb_down_alt_outlined),
            label: Text(l10n.notImportant),
          ),
          TextButton.icon(
            onPressed: () {
              Clipboard.setData(ClipboardData(text: '${item.title}\n${item.url}'));
              toast(context, l10n.copiedTitleLink);
            },
            icon: const Icon(Icons.link),
            label: Text(l10n.copyLink),
          ),
        ]),
      ],
    );
    return Scaffold(
      backgroundColor: widget.embedded ? cs.surface : null,
      appBar: AppBar(
        automaticallyImplyLeading: !widget.embedded,
        actions: [
          DocumentTrashButton(item: item),
          IconButton(
            tooltip: item.state.starred ? l10n.unstar : l10n.star,
            icon: Icon(item.state.starred ? Icons.star_rounded : Icons.star_outline_rounded, color: item.state.starred ? Brand.wheat : null),
            onPressed: () => store.setState(item, starred: !item.state.starred),
          ),
          IconButton(
            tooltip: l10n.labels,
            icon: const Icon(Icons.label_outline),
            onPressed: () => showModalBottomSheet<void>(
              context: context,
              showDragHandle: true,
              isScrollControlled: true,
              builder: (_) => ItemLabelEditor(item: item),
            ),
          ),
          IconButton(tooltip: l10n.markUnread, icon: const Icon(Icons.mark_email_unread_outlined), onPressed: () => store.setState(item, read: false)),
          PopupMenuButton<String>(
            enabled: !_savingType,
            tooltip: l10n.changeTypeCurrent(typeLabel(item.type, context)),
            onSelected: (type) => _changeType(item, type),
            itemBuilder: (_) => [
              for (final type in ['todo', 'event', 'notice', 'reference'])
                CheckedPopupMenuItem(value: type, checked: item.type == type, child: Text(typeLabel(type, context))),
            ],
            child: Padding(
              padding: const EdgeInsets.symmetric(horizontal: 6, vertical: 12),
              child: Row(mainAxisSize: MainAxisSize.min, children: [
                Text(typeLabel(item.type, context)),
                const Icon(Icons.arrow_drop_down, size: 18),
              ]),
            ),
          ),
          const SizedBox(width: 8),
        ],
      ),
      body: Align(alignment: Alignment.topCenter, child: ConstrainedBox(constraints: const BoxConstraints(maxWidth: 820), child: body)),
    );
  }
}

List<Widget> _itemLabelPills(WidgetRef ref, Item item) {
  final labels = ref.watch(labelsProvider).asData?.value ?? const <UserLabel>[];
  if (labels.isEmpty || item.labelIds.isEmpty) return const [];
  final byId = {for (final l in labels) l.id: l};
  return [
    for (final id in item.labelIds)
      if (byId[id] != null)
        Pill(byId[id]!.name, color: Brand.labelColor(byId[id]!.color), icon: Icons.label_outline),
  ];
}

class _DeadlineCard extends StatelessWidget {
  final Item item;
  const _DeadlineCard({required this.item});
  @override
  Widget build(BuildContext context) {
    final l10n = AppLocalizations.of(context);
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
            Text(DateFormat.MMM(l10n.localeName).format(due), style: TextStyle(color: c, fontWeight: FontWeight.w700, fontSize: 12)),
            Text('${due.day}', style: TextStyle(fontSize: 26, fontWeight: FontWeight.w800, color: cs.onSurface, height: 1.1)),
            Text(weekday(due, context), style: TextStyle(fontSize: 11, color: cs.onSurfaceVariant)),
          ]),
        ),
        const SizedBox(width: 16),
        Expanded(
          child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
            Text(item.isDone ? l10n.completed : countdown(due, context), style: Theme.of(context).textTheme.titleLarge?.copyWith(color: c, fontWeight: FontWeight.w800)),
            const SizedBox(height: 4),
            Text(l10n.deadlineAt(absolute(due, context)), style: TextStyle(color: cs.onSurfaceVariant)),
            if (item.fields['deadline_at']?.edited == true || item.state.deadlineOverride != null)
              Text(l10n.manuallyCorrected, style: TextStyle(color: cs.onSurfaceVariant, fontSize: 12)),
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
    final l10n = AppLocalizations.of(context);
    final v = ref.watch(versionsProvider(id));
    return v.when(
      loading: () => const SizedBox.shrink(),
      error: (_, _) => const SizedBox.shrink(),
      data: (versions) {
        if (versions.length <= 1) return const SizedBox.shrink();
        final cs = Theme.of(context).colorScheme;
        return Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
          SectionHeader(l10n.editHistory, trailing: l10n.versionsCount(versions.length)),
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
                              versions[i].version == 1 ? l10n.firstSeen : (versions[i].note.isEmpty ? l10n.contentUpdated : versions[i].note),
                              style: TextStyle(fontWeight: versions[i].important ? FontWeight.w700 : FontWeight.w500),
                            ),
                            Text('v${versions[i].version} · ${relative(tsToDate(versions[i].detectedAt), context)}', style: TextStyle(color: cs.onSurfaceVariant, fontSize: 12)),
                            // 版本按新到旧排列：与下一条（更旧的版本）比较
                            if (versions[i].version > 1)
                              VersionDiff(version: versions[i], previous: i + 1 < versions.length ? versions[i + 1] : null),
                            if (versions[i].changed.containsKey('source_fields'))
                              SourceChanges({'source_fields': versions[i].changed['source_fields']}),
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
