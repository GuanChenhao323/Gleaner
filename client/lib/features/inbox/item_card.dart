import 'document_trash_button.dart';
import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../core/format.dart';
import '../../core/models.dart';
import '../../core/store.dart';
import '../../l10n/app_localizations.dart';
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
    final l10n = AppLocalizations.of(context);
    final t = Theme.of(context);
    final cs = t.colorScheme;
    final unread = !item.state.read;
    final due = item.deadline;
    final accent = dueRowAccent(done: item.isDone, priority: item.priority, deadline: due);
    final Color base = selected
        ? cs.secondaryContainer.withValues(alpha: 0.7)
        : (unread ? cs.surfaceContainerLow : cs.surface);
    final meta = [
      if (item.course.isNotEmpty) shortCourse(item.course),
      item.source?.name ?? kindLabel(item.kind, context),
      relative(item.sortTime, context),
    ].join(' · ');
    final card = Material(
      color: base,
      clipBehavior: Clip.antiAlias,
      shape: RoundedRectangleBorder(
        borderRadius: BorderRadius.circular(18),
        side: BorderSide(color: selected ? cs.outline.withValues(alpha: 0.55) : cs.outlineVariant),
      ),
      child: InkWell(
        onTap: onTap,
        child: Stack(
          children: [
            if (accent != null)
              Positioned(
                left: 0,
                top: 12,
                bottom: 12,
                child: Container(
                  width: 3,
                  decoration: BoxDecoration(color: accent, borderRadius: BorderRadius.circular(2)),
                ),
              ),
            Padding(
              padding: EdgeInsets.fromLTRB(14, dense ? 10 : 12, 4, dense ? 10 : 12),
              child: Row(crossAxisAlignment: CrossAxisAlignment.start, children: [
                Padding(
                  padding: const EdgeInsets.only(top: 2),
                  child: Icon(kindIcon(item.kind), size: 20, color: cs.onSurfaceVariant),
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
                            )),
                      ),
                      if (unread)
                        Container(
                          margin: const EdgeInsets.only(left: 6, top: 4),
                          width: 7,
                          height: 7,
                          decoration: const BoxDecoration(color: Brand.yellow, shape: BoxShape.circle),
                        ),
                    ]),
                    const SizedBox(height: 6),
                    Wrap(spacing: 8, runSpacing: 4, crossAxisAlignment: WrapCrossAlignment.center, children: [
                      if (due != null || item.isDone) DeadlineBadge(due ?? DateTime.now(), done: item.isDone),
                      Text(meta, style: t.textTheme.labelSmall?.copyWith(color: cs.onSurfaceVariant)),
                    ]),
                  ]),
                ),
                DocumentTrashButton(item: item),
                IconButton(
                  visualDensity: VisualDensity.compact,
                  tooltip: item.state.starred ? l10n.unstar : l10n.star,
                  icon: Icon(
                    item.state.starred ? Icons.star_rounded : Icons.star_outline_rounded,
                    color: item.state.starred ? Brand.wheat : cs.outline,
                  ),
                  onPressed: () => ref.read(feedProvider.notifier).setState(item, starred: !item.state.starred),
                ),
              ]),
            ),
          ],
        ),
      ),
    );
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
      background: _swipeBg(context, Icons.mark_email_read_outlined, item.state.read ? l10n.markUnreadShort : l10n.markReadShort, Alignment.centerLeft, cs.primaryContainer),
      secondaryBackground: _swipeBg(context, Icons.playlist_add_check, item.state.todo == 'todo' ? l10n.removeTodo : l10n.addTodo, Alignment.centerRight, cs.tertiaryContainer),
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
