import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../core/format.dart';
import '../../core/models.dart';
import '../../core/store.dart';
import '../../theme.dart';
import '../../widgets/common.dart';

class ItemCard extends ConsumerWidget {
  final Item item;
  final bool selected;
  final VoidCallback onTap;
  final bool dense;
  const ItemCard({super.key, required this.item, required this.onTap, this.selected = false, this.dense = false});

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final t = Theme.of(context);
    final cs = t.colorScheme;
    final unread = !item.state.read;
    final due = item.deadline;
    final courseColor = Brand.course(item.course);
    final urgent = item.priority == 'urgent';
    final card = Material(
      color: selected ? cs.secondaryContainer.withValues(alpha: 0.7) : (unread ? cs.surfaceContainerLow : cs.surface),
      borderRadius: BorderRadius.circular(18),
      child: InkWell(
        borderRadius: BorderRadius.circular(18),
        onTap: onTap,
        child: Padding(
          padding: EdgeInsets.fromLTRB(14, dense ? 10 : 14, 8, dense ? 10 : 14),
          child: Row(crossAxisAlignment: CrossAxisAlignment.start, children: [
            Container(
              width: 40,
              height: 40,
              decoration: BoxDecoration(color: courseColor.withValues(alpha: 0.14), borderRadius: BorderRadius.circular(12)),
              child: Stack(children: [
                Center(child: Icon(kindIcon(item.kind), size: 20, color: courseColor)),
                if (urgent && unread)
                  Positioned(right: 4, top: 4, child: Container(width: 8, height: 8, decoration: const BoxDecoration(color: Brand.urgent, shape: BoxShape.circle))),
              ]),
            ),
            const SizedBox(width: 12),
            Expanded(
              child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
                Row(children: [
                  Expanded(
                    child: Text(item.title,
                        maxLines: 2,
                        overflow: TextOverflow.ellipsis,
                        style: t.textTheme.titleSmall?.copyWith(
                          fontWeight: unread ? FontWeight.w700 : FontWeight.w500,
                          color: item.isDone ? cs.onSurfaceVariant : cs.onSurface,
                          decoration: item.isDone ? TextDecoration.lineThrough : null,
                        )),
                  ),
                  if (unread) Container(margin: const EdgeInsets.only(left: 6, top: 4), width: 7, height: 7, decoration: BoxDecoration(color: cs.primary, shape: BoxShape.circle)),
                ]),
                if (item.summary.isNotEmpty && !dense) ...[
                  const SizedBox(height: 4),
                  Text(item.summary, maxLines: 2, overflow: TextOverflow.ellipsis, style: t.textTheme.bodySmall?.copyWith(color: cs.onSurfaceVariant, height: 1.4)),
                ],
                if (item.importantChange && item.changeNote.isNotEmpty) ...[const SizedBox(height: 8), ChangeBadge(item.changeNote)],
                const SizedBox(height: 8),
                Wrap(spacing: 10, runSpacing: 6, crossAxisAlignment: WrapCrossAlignment.center, children: [
                  if (due != null) DeadlineBadge(due, done: item.isDone),
                  if (item.course.isNotEmpty) CourseTag(item.course),
                  Text(
                    '${item.source?.name ?? kindLabel(item.kind)} · ${relative(item.sortTime)}',
                    style: t.textTheme.labelSmall?.copyWith(color: cs.onSurfaceVariant),
                  ),
                  if (item.channels.length > 1)
                    Pill('${item.channels.length} 个渠道已合并', color: cs.primary, icon: Icons.merge_type),
                  if (item.state.todo == 'todo' || item.state.todo == 'doing') Pill('待办', color: cs.secondary, icon: Icons.checklist),
                ]),
              ]),
            ),
            IconButton(
              visualDensity: VisualDensity.compact,
              tooltip: item.state.starred ? '取消收藏' : '收藏',
              icon: Icon(item.state.starred ? Icons.star_rounded : Icons.star_outline_rounded, color: item.state.starred ? Brand.wheat : cs.outline),
              onPressed: () => ref.read(feedProvider.notifier).setState(item, starred: !item.state.starred),
            ),
          ]),
        ),
      ),
    );
    // 左滑加入待办，右滑标为已读
    return Dismissible(
      key: ValueKey('card-${item.id}'),
      confirmDismiss: (dir) async {
        final store = ref.read(feedProvider.notifier);
        if (dir == DismissDirection.startToEnd) {
          await store.setState(item, read: !item.state.read);
        } else {
          await store.setState(item, todo: item.state.todo == 'todo' ? '' : 'todo');
        }
        return false;
      },
      background: _swipeBg(context, Icons.mark_email_read_outlined, item.state.read ? '标为未读' : '标为已读', Alignment.centerLeft, cs.primaryContainer),
      secondaryBackground: _swipeBg(context, Icons.playlist_add_check, item.state.todo == 'todo' ? '移出待办' : '加入待办', Alignment.centerRight, cs.tertiaryContainer),
      child: card,
    );
  }

  Widget _swipeBg(BuildContext context, IconData icon, String label, Alignment align, Color color) => Container(
        decoration: BoxDecoration(color: color, borderRadius: BorderRadius.circular(18)),
        alignment: align,
        padding: const EdgeInsets.symmetric(horizontal: 24),
        child: Row(mainAxisSize: MainAxisSize.min, children: [Icon(icon), const SizedBox(width: 8), Text(label)]),
      );
}
