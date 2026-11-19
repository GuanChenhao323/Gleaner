import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:go_router/go_router.dart';

import '../../core/api.dart';
import '../../core/locale.dart';
import '../../core/models.dart';
import '../../core/notifications.dart';
import '../../core/providers.dart';
import '../../core/session.dart';
import '../../core/store.dart';
import '../../l10n/app_localizations.dart';
import '../../widgets/common.dart';

class SettingsPage extends ConsumerWidget {
  const SettingsPage({super.key});

  String _languageLabel(AppLocalizations l10n, Locale locale) {
    if (locale.languageCode == 'zh' && locale.countryCode == 'TW') return l10n.languageTraditional;
    if (locale.languageCode == 'zh') return l10n.languageSimplified;
    return l10n.languageEnglish;
  }

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final s = ref.watch(sessionProvider);
    final me = s.me;
    final feed = ref.watch(feedProvider);
    final mqtt = ref.watch(mqttProvider);
    final locale = ref.watch(localeProvider);
    final l10n = AppLocalizations.of(context);
    final cs = Theme.of(context).colorScheme;
    return Scaffold(
      body: Align(
        alignment: Alignment.topCenter,
        child: ConstrainedBox(
          constraints: const BoxConstraints(maxWidth: 760),
          child: ListView(padding: const EdgeInsets.fromLTRB(20, 20, 20, 96), children: [
            Card(
              child: ListTile(
                contentPadding: const EdgeInsets.all(18),
                leading: Avatar(me?.name ?? '', size: 52),
                title: Text(me?.name ?? '', style: Theme.of(context).textTheme.titleMedium),
                subtitle: Text(me?.email ?? ''),
                trailing: const Icon(Icons.edit_outlined),
                onTap: () => _editProfile(context, ref),
              ),
            ),
            const SizedBox(height: 8),
            SectionHeader(l10n.language),
            Card(
              child: Column(children: [
                for (final option in supportedAppLocales)
                  ListTile(
                    leading: const Icon(Icons.translate_outlined),
                    title: Text(_languageLabel(l10n, option)),
                    trailing: encodeAppLocale(locale) == encodeAppLocale(option)
                        ? Icon(Icons.check, color: Theme.of(context).colorScheme.primary)
                        : null,
                    onTap: () => ref.read(localeProvider.notifier).setLocale(option),
                  ),
              ]),
            ),
            const SizedBox(height: 8),
            SectionHeader(l10n.sectionNotifications),
            Card(
              child: Column(children: [
                ListTile(
                  leading: const Icon(Icons.bedtime_outlined),
                  title: Text(l10n.quietHours),
                  subtitle: Text('${me?.quietStart ?? '23:00'} – ${me?.quietEnd ?? '07:00'}'),
                  onTap: () => _editTimes(context, ref),
                ),
                ListTile(
                  leading: const Icon(Icons.wb_twilight),
                  title: Text(l10n.dailyDigest),
                  subtitle: Text(l10n.dailyDigestAt(me?.digestTime ?? '08:00')),
                  onTap: () => _editTimes(context, ref),
                ),
                SwitchListTile(
                  secondary: const Icon(Icons.forward_to_inbox),
                  title: Text(l10n.digestAlsoEmail),
                  value: me?.digestEmail ?? false,
                  onChanged: (v) => _save(context, ref, {'digest_email': v}),
                ),
                ListTile(
                  leading: const Icon(Icons.tune),
                  title: Text(l10n.personalRules),
                  trailing: const Icon(Icons.chevron_right),
                  onTap: () => context.push('/settings/rules'),
                ),
              ]),
            ),
            const SizedBox(height: 8),
            SectionHeader(l10n.sectionConnection),
            Card(
              child: Column(children: [
                ListTile(
                  leading: const Icon(Icons.notifications_active_outlined),
                  title: Text(l10n.pushStatus),
                  subtitle: Text(switch (mqtt) {
                    MqttConn.on => l10n.connected,
                    MqttConn.connecting => l10n.connecting,
                    MqttConn.off => l10n.disconnected,
                  }),
                ),
                ListTile(
                  leading: const Icon(Icons.sync),
                  title: Text(l10n.sync),
                  subtitle: Text(feed.pending > 0 ? l10n.syncPending(feed.pending) : l10n.syncUpToDate),
                  trailing: TextButton(onPressed: () => ref.read(feedProvider.notifier).syncNow(), child: Text(l10n.actionSyncNow)),
                ),
                ListTile(leading: const Icon(Icons.dns_outlined), title: Text(l10n.server), subtitle: Text(s.server)),
              ]),
            ),
            const SizedBox(height: 8),
            SectionHeader(l10n.sectionAccount),
            Card(
              child: Column(children: [
                ListTile(
                  leading: const Icon(Icons.shield_outlined),
                  title: Text(l10n.privacy),
                  trailing: const Icon(Icons.chevron_right),
                  onTap: () => showDialog<void>(
                    context: context,
                    builder: (c) => AlertDialog(
                      title: Text(l10n.privacy),
                      content: Text(l10n.privacyBody),
                      actions: [FilledButton(onPressed: () => Navigator.pop(c), child: Text(l10n.actionGotIt))],
                    ),
                  ),
                ),
                ListTile(
                  leading: const Icon(Icons.password),
                  title: Text(l10n.changePassword),
                  onTap: () => _changePassword(context, ref),
                ),
                ListTile(
                  leading: const Icon(Icons.logout),
                  title: Text(l10n.signOut),
                  onTap: () async {
                    try {
                      await ref.read(apiProvider).logout();
                    } catch (_) {}
                    await ref.read(feedProvider.notifier).clearLocal();
                    await ref.read(sessionProvider.notifier).signOut();
                  },
                ),
                ListTile(
                  leading: Icon(Icons.delete_forever_outlined, color: cs.error),
                  title: Text(l10n.deleteAccount, style: TextStyle(color: cs.error)),
                  onTap: () => _delete(context, ref),
                ),
              ]),
            ),
          ]),
        ),
      ),
    );
  }

  Future<void> _editProfile(BuildContext context, WidgetRef ref) async {
    final me = ref.read(sessionProvider).me!;
    final name = TextEditingController(text: me.name);
    final grade = TextEditingController(text: me.grade);
    final major = TextEditingController(text: me.major);
    final courses = TextEditingController(text: me.courses.join(', '));
    final ok = await showDialog<bool>(
      context: context,
      builder: (c) {
        final loc = AppLocalizations.of(c);
        return AlertDialog(
        title: Text(loc.profileTitle),
        content: SizedBox(
          width: 400,
          child: Column(mainAxisSize: MainAxisSize.min, children: [
            TextField(controller: name, decoration: InputDecoration(labelText: loc.nickname)),
            const SizedBox(height: 10),
            TextField(controller: grade, decoration: InputDecoration(labelText: loc.grade, hintText: loc.gradeHintSample)),
            const SizedBox(height: 10),
            TextField(controller: major, decoration: InputDecoration(labelText: loc.major, hintText: loc.majorHintSample)),
            const SizedBox(height: 10),
            TextField(controller: courses, decoration: InputDecoration(labelText: loc.coursesCommaHint, hintText: loc.coursesHintSample)),
            const SizedBox(height: 8),
            Text(loc.profileMatchHint, style: TextStyle(fontSize: 12, color: Theme.of(c).colorScheme.onSurfaceVariant)),
          ]),
        ),
        actions: [
          TextButton(onPressed: () => Navigator.pop(c, false), child: Text(loc.actionCancel)),
          FilledButton(onPressed: () => Navigator.pop(c, true), child: Text(loc.actionSave)),
        ],
      );
      },
    );
    if (ok != true || !context.mounted) return;
    await _save(context, ref, {
      'name': name.text.trim(),
      'grade': grade.text.trim(),
      'major': major.text.trim(),
      'courses': courses.text.split(RegExp(r'[、,，\s]+')).where((e) => e.isNotEmpty).toList(),
    });
  }

  Future<void> _editTimes(BuildContext context, WidgetRef ref) async {
    final me = ref.read(sessionProvider).me!;
    TimeOfDay parse(String s) => TimeOfDay(hour: int.parse(s.split(':')[0]), minute: int.parse(s.split(':')[1]));
    String fmt(TimeOfDay t) => '${t.hour.toString().padLeft(2, '0')}:${t.minute.toString().padLeft(2, '0')}';
    final l10n = AppLocalizations.of(context);
    final qs = await showTimePicker(context: context, initialTime: parse(me.quietStart), helpText: l10n.quietStartHelp);
    if (qs == null || !context.mounted) return;
    final qe = await showTimePicker(context: context, initialTime: parse(me.quietEnd), helpText: l10n.quietEndHelp);
    if (qe == null || !context.mounted) return;
    final dg = await showTimePicker(context: context, initialTime: parse(me.digestTime), helpText: l10n.digestTimeHelp);
    if (dg == null || !context.mounted) return;
    await _save(context, ref, {'quiet_start': fmt(qs), 'quiet_end': fmt(qe), 'digest_time': fmt(dg)});
  }

  Future<void> _save(BuildContext context, WidgetRef ref, Map<String, dynamic> body) async {
    try {
      final api = ref.read(apiProvider);
      final me = await api.updateMe(body);
      final raw = await api.dio.get('/api/me');
      await ref.read(sessionProvider.notifier).updateMe(me, Map<String, dynamic>.from(raw.data as Map));
      if (context.mounted) toast(context, AppLocalizations.of(context).saved);
    } on ApiException catch (e) {
      if (context.mounted) toast(context, e.message, error: true);
    }
  }

  Future<void> _changePassword(BuildContext context, WidgetRef ref) async {
    final oldPw = TextEditingController();
    final newPw = TextEditingController();
    String? err;
    await showDialog<void>(
      context: context,
      builder: (c) => StatefulBuilder(
        builder: (c, set) {
          final loc = AppLocalizations.of(c);
          return AlertDialog(
          title: Text(loc.changePassword),
          content: SizedBox(
            width: 360,
            child: Column(mainAxisSize: MainAxisSize.min, children: [
              TextField(controller: oldPw, obscureText: true, decoration: InputDecoration(labelText: loc.currentPassword)),
              const SizedBox(height: 10),
              TextField(controller: newPw, obscureText: true, decoration: InputDecoration(labelText: loc.newPasswordMin8)),
              if (err != null) Padding(padding: const EdgeInsets.only(top: 12), child: Text(err!, style: TextStyle(color: Theme.of(c).colorScheme.error))),
            ]),
          ),
          actions: [
            TextButton(onPressed: () => Navigator.pop(c), child: Text(loc.actionCancel)),
            FilledButton(
              onPressed: () async {
                try {
                  final resp = await ref.read(apiProvider).changePassword(oldPw.text, newPw.text);
                  await ref.read(sessionProvider.notifier).signedIn(resp);
                  if (c.mounted) Navigator.pop(c);
                  if (context.mounted) toast(context, AppLocalizations.of(context).passwordChangedToast);
                } on ApiException catch (e) {
                  set(() => err = e.message);
                }
              },
              child: Text(loc.confirmChangePassword),
            ),
          ],
        );
        },
      ),
    );
  }

  Future<void> _delete(BuildContext context, WidgetRef ref) async {
    final pw = TextEditingController();
    String? err;
    final ok = await showDialog<bool>(
      context: context,
      builder: (c) => StatefulBuilder(
        builder: (c, set) {
          final loc = AppLocalizations.of(c);
          return AlertDialog(
          icon: const Icon(Icons.warning_amber_rounded),
          title: Text(loc.deleteAccountTitle),
          content: SizedBox(
            width: 380,
            child: Column(mainAxisSize: MainAxisSize.min, children: [
              Text(loc.deleteAccountBody),
              const SizedBox(height: 12),
              TextField(controller: pw, obscureText: true, decoration: InputDecoration(labelText: loc.password)),
              if (err != null) Padding(padding: const EdgeInsets.only(top: 12), child: Text(err!, style: TextStyle(color: Theme.of(c).colorScheme.error))),
            ]),
          ),
          actions: [
            TextButton(onPressed: () => Navigator.pop(c, false), child: Text(loc.actionCancel)),
            FilledButton(
              style: FilledButton.styleFrom(backgroundColor: Theme.of(c).colorScheme.error),
              onPressed: () async {
                try {
                  await ref.read(apiProvider).deleteAccount(pw.text);
                  if (c.mounted) Navigator.pop(c, true);
                } on ApiException catch (e) {
                  set(() => err = e.message);
                }
              },
              child: Text(loc.deleteForever),
            ),
          ],
        );
        },
      ),
    );
    if (ok != true) return;
    await ref.read(feedProvider.notifier).clearLocal();
    await ref.read(sessionProvider.notifier).signOut();
  }
}

class RulesPage extends ConsumerStatefulWidget {
  const RulesPage({super.key});
  @override
  ConsumerState<RulesPage> createState() => _RulesPageState();
}

class _RulesPageState extends ConsumerState<RulesPage> {
  List<Rule>? rules;
  final ctl = TextEditingController();
  String kind = 'keyword';
  bool block = false;

  @override
  Widget build(BuildContext context) {
    final l10n = AppLocalizations.of(context);
    final async = ref.watch(rulesProvider);
    rules ??= async.asData?.value.toList();
    final list = rules ?? [];
    final cs = Theme.of(context).colorScheme;
    return Scaffold(
      appBar: AppBar(actions: [
        TextButton(
          onPressed: rules == null
              ? null
              : () async {
                  await ref.read(apiProvider).saveRules(list);
                  ref.invalidate(rulesProvider);
                  if (context.mounted) toast(context, AppLocalizations.of(context).rulesSavedToast);
                },
          child: Text(l10n.actionSave),
        ),
        const SizedBox(width: 8),
      ]),
      body: ListView(padding: const EdgeInsets.all(16), children: [
        Card(
          child: Padding(
            padding: const EdgeInsets.all(16),
            child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
              Text(l10n.priorityFormula, style: TextStyle(color: cs.onSurfaceVariant, fontSize: 12)),
              const SizedBox(height: 4),
              Text(l10n.priorityBands, style: TextStyle(color: cs.onSurfaceVariant, fontSize: 12)),
              const SizedBox(height: 14),
              SegmentedButton<String>(
                segments: [
                  ButtonSegment(value: 'keyword', label: Text(l10n.ruleKeyword)),
                  ButtonSegment(value: 'sender', label: Text(l10n.ruleSenderWhitelist)),
                ],
                selected: {kind},
                onSelectionChanged: (v) => setState(() => kind = v.first),
              ),
              const SizedBox(height: 10),
              Row(children: [
                Expanded(child: TextField(controller: ctl, decoration: InputDecoration(hintText: kind == 'keyword' ? l10n.ruleKeywordHint : 'teacher@school.edu'))),
                if (kind == 'keyword') ...[const SizedBox(width: 8), FilterChip(label: Text(l10n.ruleBlock), selected: block, onSelected: (v) => setState(() => block = v))],
                const SizedBox(width: 8),
                FilledButton(
                  onPressed: () {
                    if (ctl.text.trim().isEmpty) return;
                    setState(() {
                      rules = [...list, Rule(kind, ctl.text.trim(), block ? -1 : 0.5)];
                      ctl.clear();
                    });
                  },
                  child: Text(l10n.actionAdd),
                ),
              ]),
            ]),
          ),
        ),
        const SizedBox(height: 12),
        if (list.isEmpty) EmptyState(icon: Icons.rule, title: l10n.noCustomRules, message: l10n.defaultKeywordsHint),
        Wrap(spacing: 8, runSpacing: 8, children: [
          for (var i = 0; i < list.length; i++)
            InputChip(
              avatar: Icon(list[i].kind == 'sender' ? Icons.verified_user_outlined : (list[i].boost <= 0 ? Icons.block : Icons.trending_up), size: 18),
              label: Text(list[i].pattern),
              onDeleted: () => setState(() => rules = [...list]..removeAt(i)),
            ),
        ]),
      ]),
    );
  }
}
