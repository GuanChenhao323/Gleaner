import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../core/models.dart';
import '../../core/store.dart';
import '../../core/session.dart';
import '../sources/reading_source.dart';

/// Owns action feedback only; the repository owns response validation.
class DocumentTrashButton extends ConsumerStatefulWidget {
  final Item item;
  const DocumentTrashButton({super.key, required this.item});
  @override
  ConsumerState<DocumentTrashButton> createState() =>
      _DocumentTrashButtonState();
}

class _DocumentTrashButtonState extends ConsumerState<DocumentTrashButton> {
  bool busy = false;
  Future<void> act(bool trashed) async {
    if (busy) return;
    final item = widget.item;
    final container = ProviderScope.containerOf(context, listen: false);
    final messenger = ScaffoldMessenger.of(context);
    final api = container.read(apiProvider);
    setState(() => busy = true);
    try {
      await ref.read(feedProvider.notifier).setTrashed(item, trashed);
      container.invalidate(readingSourcesProvider);
      if (!messenger.mounted) return;
      messenger.showSnackBar(
        SnackBar(
          content: Text(trashed ? '已移入回收站，资料与历史保留。' : '已恢复资料；来源检查保持暂停。'),
          action: trashed
              ? SnackBarAction(
                  label: '撤销',
                  onPressed: () async {
                    try {
                      if (!identical(api, container.read(apiProvider))) {
                        throw StateError('工作台账号已变化');
                      }
                      await container
                          .read(feedProvider.notifier)
                          .setTrashed(item, false);
                      container.invalidate(readingSourcesProvider);
                    } catch (e) {
                      messenger.showSnackBar(
                        SnackBar(content: Text('恢复未完成：$e')),
                      );
                    }
                  },
                )
              : null,
        ),
      );
    } catch (e) {
      if (mounted) {
        ScaffoldMessenger.of(context)
            .showSnackBar(SnackBar(content: Text('操作未确认：$e')));
      }
    } finally {
      if (mounted) setState(() => busy = false);
    }
  }

  @override
  Widget build(BuildContext context) => IconButton(
    tooltip: widget.item.state.hidden ? '恢复到收件箱' : '移入回收站',
    onPressed: busy ? null : () => act(!widget.item.state.hidden),
    icon: Icon(
      widget.item.state.hidden
          ? Icons.restore_from_trash_outlined
          : Icons.delete_outline,
    ),
  );
}
