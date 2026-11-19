import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../core/api.dart';
import '../../core/models.dart';
import '../../core/providers.dart';
import '../../core/session.dart';
import '../../core/store.dart';
import '../../l10n/app_localizations.dart';
import '../../theme.dart';
import '../../widgets/common.dart';

Future<UserLabel?> createInboxLabel(BuildContext context, WidgetRef ref) async {
  final input = await showDialog<({String name, String color})>(
    context: context,
    builder: (_) => const _CreateLabelDialog(),
  );
  if (input == null || !context.mounted) return null;
  final api = ref.read(apiProvider);
  try {
    final label = await api.createLabel(input.name, color: input.color);
    if (!context.mounted) return null;
    ref.invalidate(labelsProvider);
    return label;
  } on ApiException catch (e) {
    if (context.mounted) toast(context, e.message);
    return null;
  }
}

class ItemLabelEditor extends ConsumerStatefulWidget {
  final Item item;
  const ItemLabelEditor({super.key, required this.item});

  @override
  ConsumerState<ItemLabelEditor> createState() => _ItemLabelEditorState();
}

class _ItemLabelEditorState extends ConsumerState<ItemLabelEditor> {
  late final selected = widget.item.labelIds.toSet();
  bool busy = false;
  String? saveError;

  Future<void> _save() async {
    setState(() { busy = true; saveError = null; });
    try {
      await ref.read(feedProvider.notifier).setItemLabels(widget.item, selected.toList()..sort());
      if (mounted) Navigator.pop(context);
    } on ApiException catch (e) {
      if (mounted) setState(() { busy = false; saveError = e.message; });
    }
  }

  Future<void> _create() async {
    setState(() => busy = true);
    final label = await createInboxLabel(context, ref);
    if (mounted) setState(() {
      busy = false;
      if (label != null) selected.add(label.id);
    });
  }

  @override
  Widget build(BuildContext context) {
    final l10n = AppLocalizations.of(context);
    final labels = ref.watch(labelsProvider);
    return SafeArea(child: SingleChildScrollView(
      padding: const EdgeInsets.fromLTRB(16, 0, 16, 24),
      child: Column(mainAxisSize: MainAxisSize.min, crossAxisAlignment: CrossAxisAlignment.stretch, children: [
        Text(l10n.tagItem, style: Theme.of(context).textTheme.titleMedium),
        const SizedBox(height: 12),
        ...labels.when<List<Widget>>(
          skipLoadingOnRefresh: false,
          loading: () => [LinearProgressIndicator(semanticsLabel: l10n.loadingLabels)],
          error: (error, _) => [
            Text(l10n.labelsLoadFailed),
            TextButton(onPressed: () => ref.invalidate(labelsProvider), child: Text(l10n.retry)),
          ],
          data: (all) => [
            if (all.isEmpty) Text(l10n.noLabelsYet),
            for (final label in all)
              CheckboxListTile(
                title: Text(label.name),
                secondary: Icon(Icons.label, color: Brand.labelColor(label.color)),
                controlAffinity: ListTileControlAffinity.leading,
                value: selected.contains(label.id),
                onChanged: busy ? null : (checked) => setState(() {
                  if (checked == true) { selected.add(label.id); } else { selected.remove(label.id); }
                }),
              ),
            TextButton.icon(onPressed: busy ? null : _create, icon: const Icon(Icons.add), label: Text(l10n.newLabelAction)),
            if (saveError != null) Text(saveError!, style: TextStyle(color: Theme.of(context).colorScheme.error)),
            FilledButton(onPressed: busy || all.isEmpty ? null : _save, child: Text(l10n.actionSave)),
          ],
        ),
      ]),
    ));
  }
}

class _CreateLabelDialog extends StatefulWidget {
  const _CreateLabelDialog();

  @override
  State<_CreateLabelDialog> createState() => _CreateLabelDialogState();
}

class _CreateLabelDialogState extends State<_CreateLabelDialog> {
  final _name = TextEditingController();
  String _color = Brand.labelPalette.first;

  @override
  void dispose() {
    _name.dispose();
    super.dispose();
  }

  void _submit() {
    final name = _name.text.trim();
    if (name.isEmpty) return;
    Navigator.pop(context, (name: name, color: _color));
  }

  @override
  Widget build(BuildContext context) {
    final l10n = AppLocalizations.of(context);
    return AlertDialog(
      title: Text(l10n.newLabelAction),
      content: SizedBox(
        width: 320,
        child: Column(
          mainAxisSize: MainAxisSize.min,
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            TextField(
              controller: _name,
              autofocus: true,
              maxLength: 40,
              decoration: InputDecoration(hintText: l10n.labelNameHint),
              onSubmitted: (_) => _submit(),
            ),
            const SizedBox(height: 8),
            Text(l10n.color, style: Theme.of(context).textTheme.labelLarge),
            const SizedBox(height: 10),
            Wrap(
              spacing: 10,
              runSpacing: 10,
              children: [
                for (final hex in Brand.labelPalette)
                  InkWell(
                    onTap: () => setState(() => _color = hex),
                    borderRadius: BorderRadius.circular(20),
                    child: Container(
                      width: 28,
                      height: 28,
                      decoration: BoxDecoration(
                        color: Brand.labelColor(hex),
                        shape: BoxShape.circle,
                        border: Border.all(
                          color: _color == hex ? Brand.ink : Colors.transparent,
                          width: 2,
                        ),
                      ),
                      child: _color == hex
                          ? const Icon(Icons.check, size: 16, color: Colors.white)
                          : null,
                    ),
                  ),
              ],
            ),
          ],
        ),
      ),
      actions: [
        TextButton(onPressed: () => Navigator.pop(context), child: Text(l10n.actionCancel)),
        FilledButton(onPressed: _submit, child: Text(l10n.create)),
      ],
    );
  }
}
