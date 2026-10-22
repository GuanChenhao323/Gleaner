import 'dart:async';

import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:go_router/go_router.dart';

import '../../core/notifications.dart';
import '../../core/session.dart';
import '../../core/store.dart';
import '../../theme.dart';
import '../../widgets/common.dart';

class Dest {
  final String path;
  final String label;
  final IconData icon;
  final IconData selected;
  const Dest(this.path, this.label, this.icon, this.selected);
}

const destinations = [
  Dest('/', '工作台', Icons.space_dashboard_outlined, Icons.space_dashboard),
  Dest('/inbox', '收件箱', Icons.inbox_outlined, Icons.inbox),
  Dest('/assignments', '作业', Icons.assignment_outlined, Icons.assignment),
  Dest('/calendar', '日历', Icons.calendar_month_outlined, Icons.calendar_month),
  Dest('/courses', '课程', Icons.class_outlined, Icons.class_),
  Dest('/sources', '来源', Icons.hub_outlined, Icons.hub),
  Dest('/settings', '设置', Icons.settings_outlined, Icons.settings),
];

/// 自适应外壳：手机底部导航栏，平板侧边导航栏，宽屏展开侧栏（Material 3 窗口尺寸类别）。
class AppShell extends ConsumerStatefulWidget {
  final Widget child;
  final String location;
  const AppShell({super.key, required this.child, required this.location});
  @override
  ConsumerState<AppShell> createState() => _AppShellState();
}

class _AppShellState extends ConsumerState<AppShell> {
  StreamSubscription<AppEvent>? _sub;

  @override
  void initState() {
    super.initState();
    ref.read(mqttProvider);
    ref.read(systemNotifierProvider);
    _sub = ref.read(feedProvider.notifier).events.listen(_onEvent);
  }

  @override
  void dispose() {
    _sub?.cancel();
    super.dispose();
  }

  void _onEvent(AppEvent e) {
    if (!mounted) return;
    final cs = Theme.of(context).colorScheme;
    final urgent = e.priority == 'urgent';
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
              Text(e.title, maxLines: 1, overflow: TextOverflow.ellipsis, style: const TextStyle(fontWeight: FontWeight.w700)),
              if (e.body.isNotEmpty) Text(e.body, maxLines: 2, overflow: TextOverflow.ellipsis),
            ]),
          ),
        ]),
        action: e.itemId != null
            ? SnackBarAction(label: '查看', onPressed: () => context.push('/item/${e.itemId}'))
            : e.type == 'source_status'
                ? SnackBarAction(label: '去处理', onPressed: () => context.go('/sources'))
                : null,
      ));
  }

  int _index() {
    final loc = widget.location;
    for (var i = destinations.length - 1; i >= 0; i--) {
      final p = destinations[i].path;
      if (p == '/' ? loc == '/' : loc.startsWith(p)) return i;
    }
    return 0;
  }

  @override
  Widget build(BuildContext context) {
    final w = MediaQuery.sizeOf(context).width;
    final idx = _index();
    final cs = Theme.of(context).colorScheme;
    final unread = ref.watch(feedProvider.select((s) => s.unread));
    final me = ref.watch(sessionProvider.select((s) => s.me));

    Widget badge(int i, Widget icon) => i == 1 && unread > 0 ? Badge(label: Text(unread > 99 ? '99+' : '$unread'), child: icon) : icon;

    if (w < 600) {
      // 手机：底部 5 个入口，其余放进“更多”
      const primary = [0, 1, 2, 3];
      final sel = primary.contains(idx) ? primary.indexOf(idx) : 4;
      return Scaffold(
        body: widget.child,
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
              NavigationDestination(icon: badge(i, Icon(destinations[i].icon)), selectedIcon: badge(i, Icon(destinations[i].selected)), label: destinations[i].label),
            const NavigationDestination(icon: Icon(Icons.more_horiz), label: '更多'),
          ],
        ),
      );
    }
    final extended = w >= 1280;
    return Scaffold(
      body: Row(children: [
        NavigationRail(
          extended: extended,
          minExtendedWidth: 220,
          selectedIndex: idx,
          labelType: extended ? NavigationRailLabelType.none : NavigationRailLabelType.all,
          onDestinationSelected: (i) => context.go(destinations[i].path),
          leading: Padding(
            padding: const EdgeInsets.fromLTRB(8, 16, 8, 20),
            child: extended
                ? Row(mainAxisSize: MainAxisSize.min, children: [
                    const GleanerLogo(size: 40),
                    const SizedBox(width: 12),
                    Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
                      Text('拾课', style: Theme.of(context).textTheme.titleLarge),
                      Text('Gleaner', style: Theme.of(context).textTheme.labelSmall?.copyWith(color: cs.onSurfaceVariant)),
                    ]),
                  ])
                : const GleanerLogo(size: 40),
          ),
          trailing: Expanded(
            child: Align(
              alignment: Alignment.bottomCenter,
              child: Padding(
                padding: const EdgeInsets.only(bottom: 20),
                child: Column(mainAxisSize: MainAxisSize.min, children: [
                  if (extended) const ConnectionDot(showLabel: true) else const ConnectionDot(),
                  const SizedBox(height: 14),
                  Tooltip(
                    message: me?.email ?? '',
                    child: InkWell(customBorder: const CircleBorder(), onTap: () => context.go('/settings'), child: Avatar(me?.name ?? '', size: 38)),
                  ),
                ]),
              ),
            ),
          ),
          destinations: [
            for (var i = 0; i < destinations.length; i++)
              NavigationRailDestination(icon: badge(i, Icon(destinations[i].icon)), selectedIcon: badge(i, Icon(destinations[i].selected)), label: Text(destinations[i].label)),
          ],
        ),
        VerticalDivider(width: 1, color: cs.outlineVariant.withValues(alpha: 0.5)),
        Expanded(child: widget.child),
      ]),
    );
  }

  void _more(BuildContext context) {
    showModalBottomSheet<void>(
      context: context,
      builder: (c) => SafeArea(
        child: Column(mainAxisSize: MainAxisSize.min, children: [
          for (final i in [4, 5, 6])
            ListTile(
              leading: Icon(destinations[i].icon),
              title: Text(destinations[i].label),
              onTap: () {
                Navigator.pop(c);
                context.go(destinations[i].path);
              },
            ),
          ListTile(leading: const Icon(Icons.edit_note), title: const Text('写邮件'), onTap: () {
            Navigator.pop(c);
            context.push('/compose');
          }),
          ListTile(leading: const Icon(Icons.qr_code_2), title: const Text('扫码传输'), onTap: () {
            Navigator.pop(c);
            context.push('/transfer');
          }),
          const Padding(padding: EdgeInsets.all(12), child: ConnectionDot(showLabel: true)),
        ]),
      ),
    );
  }
}
