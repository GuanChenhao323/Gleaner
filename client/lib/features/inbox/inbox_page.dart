import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:go_router/go_router.dart';

import '../../core/models.dart';
import '../../core/store.dart';
import '../../theme.dart';
import '../../widgets/common.dart';
import 'item_card.dart';
import 'item_detail.dart';

/// `null` = 全部（默认，不占筛选项）。待办／日程／通知是三类事项（产品定义 2.3 节）；
/// 收藏合并了原「重要」：星标或系统判重要/重要变更。
enum InboxFilter { unread, starred, todo, event, notice }

const _labels = {
  InboxFilter.unread: '未读',
  InboxFilter.starred: '收藏',
  InboxFilter.todo: '待办',
  InboxFilter.event: '日程',
  InboxFilter.notice: '通知',
};

/// 每类事项可以按处理状态再筛：第一个是“未处理”。
const typeStatuses = {
  'todo': [('open', '待完成'), ('done', '已完成')],
  'event': [('active', '未归档'), ('archived', '已归档')],
  'notice': [('unread', '未读'), ('read', '已读')],
};

Color? _filterAccent(InboxFilter f) => switch (f) {
      InboxFilter.unread => null,
      InboxFilter.starred => Brand.wheat,
      InboxFilter.todo => const Color(0xFFD9534F),
      InboxFilter.event => const Color(0xFF5C6BC0),
      InboxFilter.notice => const Color(0xFF3A7BD5),
    };

String? _typeOf(InboxFilter? f) => switch (f) {
      InboxFilter.todo => 'todo',
      InboxFilter.event => 'event',
      InboxFilter.notice => 'notice',
      _ => null,
    };

bool _match(Item i, InboxFilter? f, String? status, String q) {
  final ok = switch (f) {
    null => true,
    InboxFilter.unread => !i.state.read,
    InboxFilter.starred => i.state.starred || i.priority != 'low' || i.importantChange,
    InboxFilter.todo || InboxFilter.event || InboxFilter.notice => i.type == _typeOf(f),
  };
  if (!ok) return false;
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
  String? status; // 选中类型后的状态筛选；null = 全部状态
  String q = '';
  int? selected;
  bool searching = false;

  @override
  Widget build(BuildContext context) {
    final st = ref.watch(feedProvider);
    final items = st.visible.where((i) => _match(i, filter, status, q)).toList();
    final type = _typeOf(filter);
    final wide = MediaQuery.sizeOf(context).width >= 900;
    final cs = Theme.of(context).colorScheme;
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
                  decoration: const InputDecoration(hintText: '搜索标题、课程、来源', prefixIcon: Icon(Icons.search), isDense: true),
                  onChanged: (v) => setState(() => q = v.trim()),
                )
              : Row(children: [
                  const Text('事项'),
                  const SizedBox(width: 10),
                  if (st.unread > 0) Pill('${st.unread} 未读', color: cs.primary),
                ]),
          actions: [
            IconButton(
              tooltip: searching ? '关闭搜索' : '搜索',
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
              },
              itemBuilder: (_) => const [
                PopupMenuItem(value: 'read', child: ListTile(leading: Icon(Icons.done_all), title: Text('当前列表全部已读'))),
                PopupMenuItem(value: 'refresh', child: ListTile(leading: Icon(Icons.refresh), title: Text('重新同步'))),
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
                        label: _labels[f]!,
                        selected: filter == f,
                        accent: _filterAccent(f),
                        badge: f == InboxFilter.unread && st.unread > 0 ? st.unread : null,
                        emphasize: f == InboxFilter.unread && st.unread > 0,
                        onSelected: () => setState(() {
                          filter = filter == f ? null : f;
                          // 切到某类事项时默认只看未处理的（待完成／未归档／未读）
                          final t = _typeOf(filter);
                          status = t == null ? null : typeStatuses[t]!.first.$1;
                        }),
                      ),
                      const SizedBox(width: 8),
                    ],
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
                      for (final (value, label) in [...typeStatuses[type]!, (null, '全部')]) ...[
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
                  ? '没有找到“$q”'
                  : (filter == null ? '还没有事项' : '这里没有${_labels[filter]}的事项'),
              message: filter == null && q.isEmpty
                  ? '在 Chrome 里打开 Moodle 或校园网页，用 Campus Radar 插件勾选要保存的事项；也可以去「信息源」订阅整个来源。'
                  : null,
              action: filter == null && q.isEmpty
                  ? FilledButton.icon(onPressed: () => context.go('/sources'), icon: const Icon(Icons.add), label: const Text('添加信息源'))
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
                    items.isEmpty ? '当前筛选没有事项' : '',
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
