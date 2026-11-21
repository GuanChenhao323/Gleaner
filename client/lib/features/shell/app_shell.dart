import 'dart:async';

import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:go_router/go_router.dart';

import '../../core/format.dart';
import '../../core/notifications.dart';
import '../../core/session.dart';
import '../../core/store.dart';
import '../../l10n/app_localizations.dart';
import '../../theme.dart';
import '../../widgets/common.dart';
import '../auth/login_page.dart';

class Dest {
  final String path;
  final IconData icon;
  final IconData selected;
  const Dest(this.path, this.icon, this.selected);

  String labelOf(AppLocalizations l10n) => switch (path) {
        '/' => l10n.navDesk,
        '/inbox' => l10n.navInbox,
        '/courses' => l10n.navCourses,
        '/sources' => l10n.navSources,
        '/settings' => l10n.navSettings,
        _ => path,
      };
}

/// 侧栏第一段：主功能
const destinations = [
  Dest('/', Icons.space_dashboard_outlined, Icons.space_dashboard),
  Dest('/inbox', Icons.inbox_outlined, Icons.inbox),
  Dest('/courses', Icons.class_outlined, Icons.class_),
  Dest('/sources', Icons.hub_outlined, Icons.hub),
];

/// 侧栏第三段：设置单独一行
const settingsDest = Dest('/settings', Icons.settings_outlined, Icons.settings);

const _railCollapsed = 72.0;
const _railExpanded = 220.0;
const _railLabelsAt = 168.0;

/// 自适应外壳：手机底栏；桌面侧栏默认收起（仅图标），悬停展开（Gmail 逻辑）。
class AppShell extends ConsumerStatefulWidget {
  final Widget child;
  final String location;
  const AppShell({super.key, required this.child, required this.location});
  @override
  ConsumerState<AppShell> createState() => _AppShellState();
}

class _AppShellState extends ConsumerState<AppShell> {
  StreamSubscription<AppEvent>? _sub;
  bool pinned = false;
  bool hovering = false;

  bool get _expanded => pinned || hovering;

  @override
  void dispose() {
    _sub?.cancel();
    super.dispose();
  }

  void _onEvent(AppEvent e) {
    if (!mounted) return;
    final cs = Theme.of(context).colorScheme;
    final l10n = AppLocalizations.of(context);
    final urgent = e.priority == 'urgent';
    final (title, body) = _localizedEvent(e, l10n);
    ScaffoldMessenger.of(context)
      ..hideCurrentSnackBar()
      ..showSnackBar(SnackBar(
        duration: Duration(seconds: urgent ? 8 : 4),
        backgroundColor: urgent ? cs.inverseSurface : null,
        content: Row(children: [
          Icon(urgent ? Icons.notifications_active : Icons.notifications_none, color: urgent ? Brand.wheat : null),
          const SizedBox(width: 12),
          Expanded(
            child: Column(mainAxisSize: MainAxisSize.min, crossAxisAlignment: CrossAxisAlignment.start, children: [
              Text(title, maxLines: 1, overflow: TextOverflow.ellipsis, style: const TextStyle(fontWeight: FontWeight.w700)),
              if (body.isNotEmpty) Text(body, maxLines: 2, overflow: TextOverflow.ellipsis),
            ]),
          ),
        ]),
        action: e.itemId != null
            ? SnackBarAction(label: l10n.actionView, onPressed: () => context.push('/item/${e.itemId}'))
            : e.type == 'source_status'
                ? SnackBarAction(label: l10n.goHandle, onPressed: () => context.go('/sources'))
                : null,
      ));
  }

  (String, String) _localizedEvent(AppEvent e, AppLocalizations l10n) {
    switch (e.type) {
      case 'source_status':
        final name = '${e.data['name'] ?? ''}';
        if (e.data['status'] == 'need_login') {
          return (l10n.sourceNeedLoginNamed(name), l10n.sourceSessionExpired);
        }
        return (l10n.sourceCheckFailedNamed(name), '${e.data['error'] ?? e.body}');
      case 'digest':
        final upcoming = e.data['upcoming'];
        final upcomingCount = upcoming is List ? upcoming.length : 0;
        final newCount = e.data['new_count'];
        return (
          l10n.digestTitle,
          l10n.digestBody(newCount is int ? newCount : 0, upcomingCount),
        );
      case 'reminder':
      case 'change':
      case 'item':
        if (e.priority == 'urgent') {
          final kind = switch (e.type) {
            'reminder' => l10n.eventReminder,
            'change' => l10n.eventImportantChange,
            _ => l10n.eventNewItem,
          };
          final sep = e.title.indexOf(' · ');
          final itemTitle = sep >= 0 ? e.title.substring(sep + 3) : e.title;
          return ('$kind · $itemTitle', localizeChangeNote(e.body, context));
        }
        return (e.title, localizeChangeNote(e.body, context));
      default:
        return (e.title, e.body);
    }
  }

  int _index() {
    final loc = widget.location;
    if (loc.startsWith(settingsDest.path)) return -1;
    for (var i = destinations.length - 1; i >= 0; i--) {
      final p = destinations[i].path;
      if (p == '/' ? loc == '/' : loc.startsWith(p)) return i;
    }
    return 0;
  }

  Future<void> _account({String? action}) async {
    if (!ref.read(sessionProvider).loggedIn) {
      await showDialog<void>(
        context: context,
        builder: (dialogContext) => LoginDialog(onClose: () => Navigator.pop(dialogContext)),
      );
      if (!mounted || !ref.read(sessionProvider).loggedIn || action == null) return;
    }
    if (action == null) {
      context.go(settingsDest.path);
    } else {
      context.push(action);
    }
  }

  bool get _onSettings => widget.location.startsWith(settingsDest.path);

  @override
  Widget build(BuildContext context) {
    final w = MediaQuery.sizeOf(context).width;
    final idx = _index();
    final signedIn = ref.watch(sessionProvider.select((s) => s.loggedIn));
    if (signedIn) {
      ref.watch(mqttProvider);
      ref.watch(systemNotifierProvider);
      final events = ref.watch(feedProvider.notifier).events;
      _sub ??= events.listen(_onEvent);
    } else {
      _sub?.cancel();
      _sub = null;
    }
    final unread = signedIn ? ref.watch(feedProvider.select((s) => s.unread)) : 0;
    final current = _onSettings ? settingsDest : destinations[idx];
    final body = signedIn ? widget.child : _GuestSection(current);
    final me = ref.watch(sessionProvider.select((s) => s.me));
    final l10n = AppLocalizations.of(context);

    if (w < 600) {
      const primary = [0, 1, 2, 3];
      final sel = primary.contains(idx) ? primary.indexOf(idx) : 4;
      return Scaffold(
        appBar: signedIn ? null : AppBar(
          leading: const Center(child: GleanerLogo(size: 32)),
          title: Text(current.labelOf(l10n)),
          actions: [IconButton(tooltip: l10n.loginOrRegister, onPressed: _account, icon: const Icon(Icons.account_circle_outlined))],
        ),
        body: body,
        bottomNavigationBar: NavigationBar(
          selectedIndex: sel,
          onDestinationSelected: (i) {
            if (i < 4) {
              context.go(destinations[primary[i]].path);
            } else {
              _more(context);
            }
          },
          destinations: [
            for (final i in primary)
              NavigationDestination(
                icon: _badge(i, unread, Icon(destinations[i].icon)),
                selectedIcon: _badge(i, unread, Icon(destinations[i].selected)),
                label: destinations[i].labelOf(l10n),
              ),
            NavigationDestination(icon: const Icon(Icons.more_horiz), label: l10n.navMore),
          ],
        ),
      );
    }

    final cs = Theme.of(context).colorScheme;
    return Scaffold(
      body: Row(children: [
        MouseRegion(
          onEnter: (_) => setState(() => hovering = true),
          onExit: (_) => setState(() => hovering = false),
          child: AnimatedContainer(
            duration: const Duration(milliseconds: 160),
            curve: Curves.easeOut,
            width: _expanded ? _railExpanded : _railCollapsed,
            clipBehavior: Clip.hardEdge,
            decoration: BoxDecoration(
              color: cs.surfaceContainerLow,
              border: Border(right: BorderSide(color: cs.outlineVariant.withValues(alpha: 0.45))),
            ),
            child: LayoutBuilder(
              builder: (context, constraints) {
                final showLabels = constraints.maxWidth >= _railLabelsAt;
                return _SideRail(
                  expanded: showLabels,
                  pinned: pinned,
                  selected: idx,
                  settingsSelected: _onSettings,
                  unread: unread,
                  meName: me?.name ?? '',
                  meEmail: me?.email ?? '',
                  onPin: () => setState(() => pinned = !pinned),
                  onSelect: (i) => context.go(destinations[i].path),
                  onSettings: () => context.go(settingsDest.path),
                  onCompose: () => _account(action: '/compose'),
                  onTransfer: () => _account(action: '/transfer'),
                  onAvatar: _account,
                );
              },
            ),
          ),
        ),
        Expanded(child: body),
      ]),
    );
  }

  Widget _badge(int i, int unread, Widget icon) =>
      i == 1 && unread > 0 ? Badge(label: Text(unread > 99 ? '99+' : '$unread'), child: icon) : icon;

  void _more(BuildContext context) {
    final l10n = AppLocalizations.of(context);
    showModalBottomSheet<void>(
      context: context,
      builder: (c) => SafeArea(
        child: Column(mainAxisSize: MainAxisSize.min, children: [
          if (ref.read(sessionProvider).loggedIn)
            ListTile(
              leading: const Icon(Icons.account_circle_outlined),
              title: Text(l10n.navAccount),
              onTap: () { Navigator.pop(c); _account(); },
            ),
          ListTile(
            leading: const Icon(Icons.edit_note),
            title: Text(l10n.navCompose),
            onTap: () {
              Navigator.pop(c);
              _account(action: '/compose');
            },
          ),
          ListTile(
            leading: const Icon(Icons.qr_code_2),
            title: Text(l10n.navTransfer),
            onTap: () {
              Navigator.pop(c);
              _account(action: '/transfer');
            },
          ),
          ListTile(
            leading: Icon(settingsDest.icon),
            title: Text(settingsDest.labelOf(l10n)),
            onTap: () {
              Navigator.pop(c);
              context.go(settingsDest.path);
            },
          ),
        ]),
      ),
    );
  }
}

class _GuestSection extends StatelessWidget {
  final Dest section;
  const _GuestSection(this.section);

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);
    final l10n = AppLocalizations.of(context);
    final description = switch (section.path) {
      '/inbox' => l10n.guestInbox,
      '/courses' => l10n.guestCourses,
      '/sources' => l10n.guestSources,
      '/settings' => l10n.guestSettings,
      _ => l10n.guestDesk,
    };
    return SafeArea(child: ListView(
      padding: const EdgeInsets.all(24),
      children: [
        if (MediaQuery.sizeOf(context).width >= 600)
          Text(section.labelOf(l10n), style: theme.textTheme.headlineMedium),
        const SizedBox(height: 24),
        Card(child: Padding(
          padding: const EdgeInsets.all(24),
          child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
            Icon(section.icon, color: theme.colorScheme.primary),
            const SizedBox(height: 16),
            Text(description, style: theme.textTheme.titleMedium),
            if (section.path == '/') ...[
              const Divider(height: 32),
              for (final dest in destinations.skip(1))
                ListTile(
                  contentPadding: EdgeInsets.zero,
                  leading: Icon(dest.icon),
                  title: Text(dest.labelOf(l10n)),
                  trailing: const Icon(Icons.chevron_right),
                  onTap: () => context.go(dest.path),
                ),
            ],
          ]),
        )),
      ],
    ));
  }
}

class _SideRail extends StatelessWidget {
  final bool expanded;
  final bool pinned;
  final int selected;
  final bool settingsSelected;
  final int unread;
  final String meName;
  final String meEmail;
  final VoidCallback onPin;
  final ValueChanged<int> onSelect;
  final VoidCallback onSettings;
  final VoidCallback onCompose;
  final VoidCallback onTransfer;
  final VoidCallback onAvatar;

  const _SideRail({
    required this.expanded,
    required this.pinned,
    required this.selected,
    required this.settingsSelected,
    required this.unread,
    required this.meName,
    required this.meEmail,
    required this.onPin,
    required this.onSelect,
    required this.onSettings,
    required this.onCompose,
    required this.onTransfer,
    required this.onAvatar,
  });

  @override
  Widget build(BuildContext context) {
    final cs = Theme.of(context).colorScheme;
    final t = Theme.of(context).textTheme;
    final l10n = AppLocalizations.of(context);
    final padH = expanded ? 10.0 : 8.0;
    return Column(crossAxisAlignment: CrossAxisAlignment.stretch, children: [
      Padding(
        padding: const EdgeInsets.fromLTRB(8, 12, 8, 8),
        child: Tooltip(
          message: pinned ? l10n.unpinSidebar : l10n.pinSidebar,
          child: TextButton(
            onPressed: onPin,
            style: TextButton.styleFrom(
              foregroundColor: cs.onSurface,
              padding: const EdgeInsets.only(left: 12, right: 8),
              minimumSize: const Size(0, 48),
            ),
            child: Row(children: [
              const GleanerLogo(size: 32),
              if (expanded) ...[
                const SizedBox(width: 2),
                Expanded(
                  child: ExcludeSemantics(
                    child: Text('leaner', maxLines: 1, overflow: TextOverflow.ellipsis,
                        style: t.titleLarge?.copyWith(fontWeight: FontWeight.w800)),
                  ),
                ),
                _PinMorphIcon(pinned: pinned, color: cs.onSurface),
              ],
            ]),
          ),
        ),
      ),
      const SizedBox(height: 4),
      Expanded(
        child: ListView(
          padding: EdgeInsets.symmetric(horizontal: padH),
          children: [
            for (var i = 0; i < destinations.length; i++)
              _NavTile(
                expanded: expanded,
                selected: selected == i,
                icon: selected == i ? destinations[i].selected : destinations[i].icon,
                label: destinations[i].labelOf(l10n),
                badge: i == 1 && unread > 0 ? unread : null,
                onTap: () => onSelect(i),
              ),
          ],
        ),
      ),
      Padding(
        padding: EdgeInsets.symmetric(horizontal: padH),
        child: Column(children: [
          Divider(color: cs.outlineVariant.withValues(alpha: 0.5)),
          _NavTile(expanded: expanded, selected: false, icon: Icons.edit_note, label: l10n.navCompose, onTap: onCompose),
          _NavTile(expanded: expanded, selected: false, icon: Icons.qr_code_2, label: l10n.navTransfer, onTap: onTransfer),
        ]),
      ),
      Padding(
        padding: EdgeInsets.fromLTRB(padH, 0, padH, 4),
        child: Column(children: [
          Divider(color: cs.outlineVariant.withValues(alpha: 0.5)),
          _NavTile(
            expanded: expanded,
            selected: settingsSelected,
            icon: settingsSelected ? settingsDest.selected : settingsDest.icon,
            label: settingsDest.labelOf(l10n),
            onTap: onSettings,
          ),
        ]),
      ),
      Padding(
        padding: const EdgeInsets.fromLTRB(8, 8, 8, 16),
        child: Tooltip(
          message: meEmail.isEmpty ? l10n.loginOrRegister : meEmail,
          child: InkWell(
            customBorder: const CircleBorder(),
            onTap: onAvatar,
            child: meEmail.isEmpty ? const Icon(Icons.account_circle_outlined, size: 36) : Avatar(meName, size: 36),
          ),
        ),
      ),
    ]);
  }
}

/// 竖三点 ↔ 三条横线：同一组圆角条做宽高插值，无淡入淡出。
class _PinMorphIcon extends StatelessWidget {
  final bool pinned;
  final Color color;
  const _PinMorphIcon({required this.pinned, required this.color});

  @override
  Widget build(BuildContext context) {
    return TweenAnimationBuilder<double>(
      // 只设 end，从上一次进度接着演，避免跳动
      tween: Tween(end: pinned ? 1.0 : 0.0),
      duration: const Duration(milliseconds: 320),
      curve: Curves.easeInOutCubic,
      builder: (context, t, _) => CustomPaint(
        size: const Size(24, 24),
        painter: _PinMorphPainter(t: t, color: color),
      ),
    );
  }
}

class _PinMorphPainter extends CustomPainter {
  final double t;
  final Color color;
  _PinMorphPainter({required this.t, required this.color});

  @override
  void paint(Canvas canvas, Size size) {
    final paint = Paint()
      ..color = color
      ..style = PaintingStyle.fill
      ..isAntiAlias = true;
    final cx = size.width / 2;
    final cy = size.height / 2;
    final gap = size.height * 0.22;
    // t=0 圆点；t=1 横线
    final w = size.width * (0.18 + 0.64 * t);
    final h = size.height * (0.18 - 0.08 * t);
    final r = h / 2;
    for (final dy in [-gap, 0.0, gap]) {
      final rect = RRect.fromRectAndRadius(
        Rect.fromCenter(center: Offset(cx, cy + dy), width: w, height: h),
        Radius.circular(r),
      );
      canvas.drawRRect(rect, paint);
    }
  }

  @override
  bool shouldRepaint(covariant _PinMorphPainter old) => old.t != t || old.color != color;
}

class _NavTile extends StatelessWidget {
  final bool expanded;
  final bool selected;
  final IconData icon;
  final String label;
  final int? badge;
  final VoidCallback onTap;
  const _NavTile({
    required this.expanded,
    required this.selected,
    required this.icon,
    required this.label,
    required this.onTap,
    this.badge,
  });

  @override
  Widget build(BuildContext context) {
    final cs = Theme.of(context).colorScheme;
    final fg = selected ? cs.onSecondaryContainer : cs.onSurfaceVariant;
    final child = Container(
      margin: const EdgeInsets.symmetric(vertical: 2),
      padding: EdgeInsets.symmetric(horizontal: expanded ? 14 : 0, vertical: 10),
      decoration: BoxDecoration(
        color: selected ? cs.secondaryContainer : Colors.transparent,
        borderRadius: BorderRadius.circular(24),
      ),
      child: expanded
          ? Row(children: [
              Icon(icon, size: 22, color: fg),
              const SizedBox(width: 14),
              Expanded(
                child: Text(
                  label,
                  maxLines: 1,
                  overflow: TextOverflow.ellipsis,
                  style: TextStyle(fontWeight: selected ? FontWeight.w700 : FontWeight.w500, color: fg),
                ),
              ),
              if (badge != null)
                Text(
                  badge! > 99 ? '99+' : '$badge',
                  style: TextStyle(fontWeight: FontWeight.w800, fontSize: 12, color: fg),
                ),
            ])
          : Center(
              child: badge != null
                  ? Badge(label: Text(badge! > 99 ? '99+' : '$badge'), child: Icon(icon, size: 22, color: fg))
                  : Icon(icon, size: 22, color: fg),
            ),
    );
    final tap = Material(
      color: Colors.transparent,
      child: InkWell(borderRadius: BorderRadius.circular(24), onTap: onTap, child: child),
    );
    return expanded ? tap : Tooltip(message: label, child: tap);
  }
}
