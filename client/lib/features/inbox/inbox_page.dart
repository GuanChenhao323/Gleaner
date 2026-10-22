import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:go_router/go_router.dart';

import '../../core/models.dart';
import '../../core/store.dart';
import '../../widgets/common.dart';
import 'item_card.dart';
import 'item_detail.dart';

enum InboxFilter { all, unread, important, starred, todo, assignment, notice, mail }

const _labels = {
  InboxFilter.all: '全部',
  InboxFilter.unread: '未读',
  InboxFilter.important: '重要',
  InboxFilter.starred: '收藏',
  InboxFilter.todo: '待办',
  InboxFilter.assignment: '作业',
  InboxFilter.notice: '通知',
  InboxFilter.mail: '邮件',
};

bool _match(Item i, InboxFilter f, String q) {
  final ok = switch (f) {
    InboxFilter.all => true,
    InboxFilter.unread => !i.state.read,
    InboxFilter.important => i.priority != 'low' || i.importantChange,
    InboxFilter.starred => i.state.starred,
    InboxFilter.todo => i.state.todo == 'todo' || i.state.todo == 'doing',
    InboxFilter.assignment => i.kind == 'assignment',
    InboxFilter.notice => i.kind == 'notice' || i.kind == 'rss',
    InboxFilter.mail => i.kind == 'mail',
  };
  if (!ok) return false;
  if (q.isEmpty) return true;
  final s = q.toLowerCase();
  return i.title.toLowerCase().contains(s) || i.summary.toLowerCase().contains(s) || i.course.toLowerCase().contains(s) || (i.source?.name.contains(q) ?? false);
}

class InboxPage extends ConsumerStatefulWidget {
  final InboxFilter initial;
  const InboxPage({super.key, this.initial = InboxFilter.all});
  @override
  ConsumerState<InboxPage> createState() => _InboxPageState();
}

class _InboxPageState extends ConsumerState<InboxPage> {
  late InboxFilter filter = widget.initial;
  String q = '';
  int? selected;
  bool searching = false;

  @override
  Widget build(BuildContext context) {
    final st = ref.watch(feedProvider);
    final items = st.visible.where((i) => _match(i, filter, q)).toList();
    final wide = MediaQuery.sizeOf(context).width >= 1100;
    final cs = Theme.of(context).colorScheme;

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
                  const Text('收件箱'),
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
            preferredSize: const Size.fromHeight(52),
            child: SizedBox(
              height: 52,
              child: ListView(
                scrollDirection: Axis.horizontal,
                padding: const EdgeInsets.symmetric(horizontal: 16, vertical: 8),
                children: [
                  for (final f in InboxFilter.values)
                    Padding(
                      padding: const EdgeInsets.only(right: 8),
                      child: ChoiceChip(label: Text(_labels[f]!), selected: filter == f, onSelected: (_) => setState(() => filter = f), showCheckmark: false),
                    ),
                ],
              ),
            ),
          ),
        ),
        if (st.loading && st.items.isEmpty)
          const SliverFillRemaining(child: Center(child: CircularProgressIndicator()))
        else if (items.isEmpty)
          SliverFillRemaining(
            hasScrollBody: false,
            child: EmptyState(
              icon: q.isNotEmpty ? Icons.search_off : Icons.inbox_outlined,
              title: q.isNotEmpty ? '没有找到“$q”' : (filter == InboxFilter.all ? '收件箱还是空的' : '这里没有${_labels[filter]}的事项'),
              message: filter == InboxFilter.all && q.isEmpty ? '去“来源”用校园模板添加 Moodle、学院通知或学校邮箱，新的作业与通知会自动出现在这里。' : null,
              action: filter == InboxFilter.all && q.isEmpty ? FilledButton.icon(onPressed: () => context.go('/sources'), icon: const Icon(Icons.add), label: const Text('添加来源')) : null,
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
                selected: wide && selected == items[i].id,
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
    return Scaffold(
      body: Row(children: [
        SizedBox(width: 460, child: list),
        VerticalDivider(width: 1, color: cs.outlineVariant),
        Expanded(
          child: selected != null && st.items.containsKey(selected)
              ? ItemDetail(key: ValueKey(selected), id: selected!, embedded: true)
              : const EmptyState(icon: Icons.touch_app_outlined, title: '选择一条事项查看详情', message: '详情里有截止倒计时、修改历史、附件和原文入口。'),
        ),
      ]),
    );
  }
}
