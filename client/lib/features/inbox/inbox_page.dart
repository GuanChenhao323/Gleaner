import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:go_router/go_router.dart';

import '../../core/api.dart';
import '../../core/models.dart';
import '../../core/providers.dart';
import '../../core/session.dart';
import '../../core/store.dart';
import '../../l10n/app_localizations.dart';
import '../../theme.dart';
import '../../widgets/common.dart';
import 'item_card.dart';
import 'label_editor.dart';
import 'item_detail.dart';

/// `null` = 全部（默认，不占筛选项）。待办／日程／通知是三类事项（产品定义 2.3 节）；
/// 收藏合并了原「重要」：星标或系统判重要/重要变更。
enum InboxFilter { unread, starred, todo, event, notice, trash }

String _filterLabel(AppLocalizations l10n, InboxFilter f) => switch (f) {
      InboxFilter.unread => l10n.inboxUnread,
      InboxFilter.starred => l10n.inboxStarred,
      InboxFilter.todo => l10n.inboxTodo,
      InboxFilter.event => l10n.inboxEvent,
      InboxFilter.notice => l10n.inboxNotice,
      InboxFilter.trash => l10n.inboxTrash,
    };

/// 每类事项可以按处理状态再筛：第一个是“未处理”。
List<(String?, String)> _typeStatuses(AppLocalizations l10n, String type) => switch (type) {
      'todo' => [('open', l10n.statusOpen), ('done', l10n.statusDone)],
      'event' => [('active', l10n.statusActive), ('archived', l10n.statusArchived)],
      'notice' => [('unread', l10n.statusUnread), ('read', l10n.statusRead)],
      _ => const [],
    };

Color? _filterAccent(InboxFilter f) => switch (f) {
      InboxFilter.unread => null,
      InboxFilter.trash => null,
      InboxFilter.starred => Brand.yellow,
      InboxFilter.todo => const Color(0xFFD9534F),
      InboxFilter.event => const Color(0xFFC9891F),
      InboxFilter.notice => const Color(0xFFB07A28),
    };

Color _labelAccent(UserLabel label) => Brand.labelColor(label.color);

String? _typeOf(InboxFilter? f) => switch (f) {
      InboxFilter.todo => 'todo',
      InboxFilter.event => 'event',
      InboxFilter.notice => 'notice',
      _ => null,
    };

bool _match(Item i, InboxFilter? f, int? labelId, String? status, String q) {
  if (labelId != null) {
    if (!i.labelIds.contains(labelId) || i.state.hidden) return false;
  } else {
    final ok = switch (f) {
      null => true,
      InboxFilter.unread => !i.state.read,
      InboxFilter.trash => i.state.hidden,
      InboxFilter.starred => i.state.starred || i.priority != 'low' || i.importantChange,
      InboxFilter.todo || InboxFilter.event || InboxFilter.notice => i.type == _typeOf(f),
    };
    if (!ok) return false;
  }
  if (status != null && i.status != status) return false;
  if (q.isEmpty) return true;
  final s = q.toLowerCase();
  return i.title.toLowerCase().contains(s) ||
      i.summary.toLowerCase().contains(s) ||
      i.course.toLowerCase().contains(s) ||
      (i.source?.name.contains(q) ?? false);
}

InboxFilter? parseInboxFilter(String? name) {
  if (name == null || name.isEmpty || name == 'all') return null;
  if (name == 'important') return InboxFilter.starred;
  if (name == 'assignment') return InboxFilter.todo; // 旧链接
  for (final f in InboxFilter.values) {
    if (f.name == name) return f;
  }
  return null;
}

class InboxPage extends ConsumerStatefulWidget {
  final InboxFilter? initial;
  const InboxPage({super.key, this.initial});
  @override
  ConsumerState<InboxPage> createState() => _InboxPageState();
}

class _InboxPageState extends ConsumerState<InboxPage> {
  late InboxFilter? filter = widget.initial;
  int? labelId;
  String? status; // 选中类型后的状态筛选；null = 全部状态
  String q = '';
  int? selected;
  bool searching = false;

  Future<void> _createLabel() async {
    final label = await createInboxLabel(context, ref);
    if (mounted && label != null) toast(context, AppLocalizations.of(context).labelCreated(label.name));
  }

  Future<void> _deleteLabel(UserLabel label) async {
    final l10n = AppLocalizations.of(context);
    final ok = await showDialog<bool>(
      context: context,
      builder: (ctx) {
        final dlg = AppLocalizations.of(ctx);
        return AlertDialog(
          title: Text(dlg.deleteLabelTitle(label.name)),
          content: Text(dlg.deleteLabelBody),
          actions: [
            TextButton(onPressed: () => Navigator.pop(ctx, false), child: Text(dlg.actionCancel)),
            FilledButton(onPressed: () => Navigator.pop(ctx, true), child: Text(dlg.actionDelete)),
          ],
        );
      },
    );
    if (ok != true || !mounted) return;
    try {
      await ref.read(apiProvider).deleteLabel(label.id);
      if (labelId == label.id) setState(() => labelId = null);
      ref.invalidate(labelsProvider);
      if (mounted) toast(context, l10n.labelDeleted(label.name));
    } on ApiException catch (e) {
      if (mounted) toast(context, e.message);
    }
  }

  @override
  Widget build(BuildContext context) {
    final st = ref.watch(feedProvider);
    final userLabels = ref.watch(labelsProvider).asData?.value ?? const <UserLabel>[];
    UserLabel? activeLabel;
    if (labelId != null) {
      for (final l in userLabels) {
        if (l.id == labelId) {
          activeLabel = l;
          break;
        }
      }
    }
    final items = (filter == InboxFilter.trash && labelId == null ? st.trashed : st.visible)
        .where((i) => _match(i, filter, labelId, status, q))
        .toList();
    final type = labelId != null ? null : _typeOf(filter);
    final wide = MediaQuery.sizeOf(context).width >= 900;
    final cs = Theme.of(context).colorScheme;
    final l10n = AppLocalizations.of(context);
    // 宽屏默认选中当前列表第一条，右侧始终是详情（Gmail 式），不再留空。
    final activeId = items.isEmpty
        ? null
        : (selected != null && items.any((i) => i.id == selected) ? selected : items.first.id);
    if (wide && activeId != selected) {
      WidgetsBinding.instance.addPostFrameCallback((_) {
        if (!mounted) return;
        setState(() => selected = activeId);
      });
    }

    final list = RefreshIndicator(
      onRefresh: () => ref.read(feedProvider.notifier).refreshAll(),
      child: CustomScrollView(slivers: [
        SliverAppBar(
          pinned: true,
          title: searching
              ? TextField(
                  autofocus: true,
                  decoration: InputDecoration(hintText: l10n.searchInboxHint, prefixIcon: const Icon(Icons.search), isDense: true),
                  onChanged: (v) => setState(() => q = v.trim()),
                )
              : filter == InboxFilter.trash && labelId == null
                  ? Text(l10n.inboxTrash)
                  : activeLabel != null
                      ? Text(activeLabel.name)
                      : (st.unread > 0 ? Pill('${st.unread} ${l10n.inboxUnread}', color: Brand.yellow) : const SizedBox.shrink()),
          actions: [
            IconButton(
              tooltip: searching ? l10n.actionClose : 'Search',
              icon: Icon(searching ? Icons.close : Icons.search),
              onPressed: () => setState(() {
                searching = !searching;
                if (!searching) q = '';
              }),
            ),
            PopupMenuButton<String>(
              onSelected: (v) async {
                if (v == 'read') await ref.read(feedProvider.notifier).markAllRead(items);
                if (v == 'refresh') await ref.read(feedProvider.notifier).refreshAll();
                if (v == 'new_label') await _createLabel();
              },
              itemBuilder: (_) => [
                PopupMenuItem(value: 'new_label', child: ListTile(leading: const Icon(Icons.new_label_outlined), title: Text(l10n.newLabel))),
              ],
            ),
          ],
          bottom: PreferredSize(
            preferredSize: Size.fromHeight(type == null ? 52 : 96),
            child: Column(children: [
              SizedBox(
                height: 52,
                child: SingleChildScrollView(
                  scrollDirection: Axis.horizontal,
                  padding: const EdgeInsets.fromLTRB(16, 8, 24, 8),
                  child: Row(children: [
                    for (final f in InboxFilter.values) ...[
                      _FilterChip(
                        label: _filterLabel(l10n, f),
                        selected: labelId == null && filter == f,
                        accent: _filterAccent(f),
                        badge: f == InboxFilter.unread && st.unread > 0 ? st.unread : null,
                        emphasize: f == InboxFilter.unread && st.unread > 0,
                        onSelected: () => setState(() {
                          labelId = null;
                          filter = filter == f ? null : f;
                          status = null;
                        }),
                      ),
                      const SizedBox(width: 8),
                    ],
                    for (final label in userLabels) ...[
                      GestureDetector(
                        onLongPress: () => _deleteLabel(label),
                        child: _FilterChip(
                          label: label.name,
                          selected: labelId == label.id,
                          accent: _labelAccent(label),
                          onSelected: () => setState(() {
                            if (labelId == label.id) {
                              labelId = null;
                            } else {
                              labelId = label.id;
                              filter = null;
                              status = null;
                            }
                          }),
                        ),
                      ),
                      const SizedBox(width: 8),
                    ],
                    ActionChip(
                      avatar: const Icon(Icons.add, size: 18),
                      label: Text(l10n.labels),
                      onPressed: _createLabel,
                    ),
                  ]),
                ),
              ),
              if (type != null)
                SizedBox(
                  height: 44,
                  child: SingleChildScrollView(
                    scrollDirection: Axis.horizontal,
                    padding: const EdgeInsets.fromLTRB(16, 2, 24, 8),
                    child: Row(children: [
                      for (final (value, label) in [..._typeStatuses(l10n, type), (null, l10n.statusAll)]) ...[
                        ChoiceChip(
                          label: Text(label),
                          selected: status == value,
                          visualDensity: VisualDensity.compact,
                          onSelected: (_) => setState(() => status = value),
                        ),
                        const SizedBox(width: 8),
                      ],
                    ]),
                  ),
                ),
            ]),
          ),
        ),
        if (st.loading && st.items.isEmpty)
          const SliverFillRemaining(child: Center(child: CircularProgressIndicator()))
        else if (items.isEmpty)
          SliverFillRemaining(
            hasScrollBody: false,
            child: EmptyState(
              icon: q.isNotEmpty ? Icons.search_off : Icons.inbox_outlined,
              title: q.isNotEmpty
                  ? q
                  : activeLabel != null
                      ? activeLabel.name
                      : (filter == null ? l10n.navInbox : _filterLabel(l10n, filter!)),
              message: null,
              action: filter == null && labelId == null && q.isEmpty
                  ? FilledButton.icon(onPressed: () => context.go('/sources'), icon: const Icon(Icons.add), label: Text(l10n.navSources))
                  : null,
            ),
          )
        else
          SliverPadding(
            padding: const EdgeInsets.fromLTRB(12, 4, 12, 96),
            sliver: SliverList.separated(
              itemCount: items.length,
              separatorBuilder: (_, _) => const SizedBox(height: 6),
              itemBuilder: (_, i) => ItemCard(
                item: items[i],
                selected: wide && activeId == items[i].id,
                onTap: () {
                  if (wide) {
                    setState(() => selected = items[i].id);
                    ref.read(feedProvider.notifier).setState(items[i], read: true);
                  } else {
                    context.push('/item/${items[i].id}');
                  }
                },
              ),
            ),
          ),
      ]),
    );

    if (!wide) return Scaffold(body: list);
    final listW = (MediaQuery.sizeOf(context).width * 0.36).clamp(340.0, 480.0);
    return Scaffold(
      body: Row(children: [
        SizedBox(width: listW, child: list),
        VerticalDivider(width: 1, color: cs.outlineVariant),
        Expanded(
          child: activeId != null && st.items.containsKey(activeId)
              ? ItemDetail(key: ValueKey(activeId), id: activeId, embedded: true)
              : Center(
                  child: Text(
                    items.isEmpty ? l10n.inboxEmptyFilter : '',
                    style: TextStyle(color: cs.onSurfaceVariant),
                  ),
                ),
        ),
      ]),
    );
  }
}

class _FilterChip extends StatelessWidget {
  final String label;
  final bool selected;
  final Color? accent;
  final int? badge;
  final bool emphasize;
  final VoidCallback onSelected;
  const _FilterChip({
    required this.label,
    required this.selected,
    required this.onSelected,
    this.accent,
    this.badge,
    this.emphasize = false,
  });

  @override
  Widget build(BuildContext context) {
    final cs = Theme.of(context).colorScheme;
    final color = accent ?? cs.primary;
    final active = selected || emphasize;
    return FilterChip(
      label: Row(mainAxisSize: MainAxisSize.min, children: [
        if (accent != null) ...[
          Container(width: 8, height: 8, decoration: BoxDecoration(color: color, shape: BoxShape.circle)),
          const SizedBox(width: 6),
        ],
        Text(label),
        if (badge != null) ...[
          const SizedBox(width: 6),
          Text(
            badge! > 99 ? '99+' : '$badge',
            style: TextStyle(fontWeight: FontWeight.w700, fontSize: 12, color: selected ? cs.onSecondaryContainer : color),
          ),
        ],
      ]),
      selected: selected,
      showCheckmark: false,
      selectedColor: color.withValues(alpha: 0.22),
      backgroundColor: emphasize && !selected ? color.withValues(alpha: 0.12) : null,
      side: BorderSide(color: active ? color.withValues(alpha: 0.55) : cs.outlineVariant),
      labelStyle: TextStyle(
        fontWeight: active ? FontWeight.w700 : FontWeight.w500,
        color: selected ? color : (emphasize ? color : null),
      ),
      onSelected: (_) => onSelected(),
    );
  }
}
