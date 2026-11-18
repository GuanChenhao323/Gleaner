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

/// 侧栏第一段：主功能（作业已并入课程详情）
const destinations = [
  Dest('/', '工作台', Icons.space_dashboard_outlined, Icons.space_dashboard),
  Dest('/inbox', '收件箱', Icons.inbox_outlined, Icons.inbox),
  Dest('/courses', '课程', Icons.class_outlined, Icons.class_),
  Dest('/sources', '信息源', Icons.hub_outlined, Icons.hub),
];

/// 侧栏第三段：设置单独一行
const settingsDest = Dest('/settings', '设置', Icons.settings_outlined, Icons.settings);

const _railCollapsed = 72.0;
const _railExpanded = 220.0;
/// 宽度动画还没到位时先只画图标，避免标题行在窄宽度里横向溢出。
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
    if (loc.startsWith(settingsDest.path)) return -1;
    for (var i = destinations.length - 1; i >= 0; i--) {
      final p = destinations[i].path;
      if (p == '/' ? loc == '/' : loc.startsWith(p)) return i;
    }
    return 0;
  }

  bool get _onSettings => widget.location.startsWith(settingsDest.path);

  @override
  Widget build(BuildContext context) {
    final w = MediaQuery.sizeOf(context).width;
    final idx = _index();
    final unread = ref.watch(feedProvider.select((s) => s.unread));
    final me = ref.watch(sessionProvider.select((s) => s.me));

    if (w < 600) {
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
              NavigationDestination(
                icon: _badge(i, unread, Icon(destinations[i].icon)),
                selectedIcon: _badge(i, unread, Icon(destinations[i].selected)),
                label: destinations[i].label,
              ),
            const NavigationDestination(icon: Icon(Icons.more_horiz), label: '更多'),
          ],
        ),
      );
    }

    final cs = Theme.of(context).colorScheme;
    // 侧栏与主内容并排：展开时挤开内容，不再叠在上面遮住。
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
                  onCompose: () => context.push('/compose'),
                  onTransfer: () => context.push('/transfer'),
                  onAvatar: () => context.go('/settings'),
                );
              },
            ),
          ),
        ),
        Expanded(child: widget.child),
      ]),
    );
  }

  Widget _badge(int i, int unread, Widget icon) =>
      i == 1 && unread > 0 ? Badge(label: Text(unread > 99 ? '99+' : '$unread'), child: icon) : icon;

  void _more(BuildContext context) {
    showModalBottomSheet<void>(
      context: context,
      builder: (c) => SafeArea(
        child: Column(mainAxisSize: MainAxisSize.min, children: [
          ListTile(
            leading: const Icon(Icons.edit_note),
            title: const Text('写邮件'),
            onTap: () {
              Navigator.pop(c);
              context.push('/compose');
            },
          ),
          ListTile(
            leading: const Icon(Icons.qr_code_2),
            title: const Text('扫码传输'),
            onTap: () {
              Navigator.pop(c);
              context.push('/transfer');
            },
          ),
          ListTile(
            leading: Icon(settingsDest.icon),
            title: Text(settingsDest.label),
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
    final padH = expanded ? 10.0 : 8.0;
    return Column(crossAxisAlignment: CrossAxisAlignment.stretch, children: [
      Padding(
        padding: EdgeInsets.fromLTRB(expanded ? 12 : 8, 12, expanded ? 12 : 8, 8),
        child: Row(children: [
          SizedBox(
            width: 48,
            height: 48,
            child: IconButton(
              tooltip: pinned ? '收起侧栏' : '固定侧栏',
              onPressed: onPin,
              padding: EdgeInsets.zero,
              icon: _PinMorphIcon(pinned: pinned, color: IconTheme.of(context).color ?? cs.onSurface),
            ),
          ),
          if (expanded) ...[
            const SizedBox(width: 4),
            const GleanerLogo(size: 28),
            const SizedBox(width: 8),
            Expanded(child: Text('拾课', style: t.titleMedium?.copyWith(fontWeight: FontWeight.w800), overflow: TextOverflow.ellipsis)),
          ],
        ]),
      ),
      const SizedBox(height: 4),
      // ① 主功能
      Expanded(
        child: ListView(
          padding: EdgeInsets.symmetric(horizontal: padH),
          children: [
            for (var i = 0; i < destinations.length; i++)
              _NavTile(
                expanded: expanded,
                selected: selected == i,
                icon: selected == i ? destinations[i].selected : destinations[i].icon,
                label: destinations[i].label,
                badge: i == 1 && unread > 0 ? unread : null,
                onTap: () => onSelect(i),
              ),
          ],
        ),
      ),
      // ② 工具
      Padding(
        padding: EdgeInsets.symmetric(horizontal: padH),
        child: Column(children: [
          Divider(color: cs.outlineVariant.withValues(alpha: 0.5)),
          _NavTile(expanded: expanded, selected: false, icon: Icons.edit_note, label: '写邮件', onTap: onCompose),
          _NavTile(expanded: expanded, selected: false, icon: Icons.qr_code_2, label: '扫码传输', onTap: onTransfer),
        ]),
      ),
      // ③ 设置
      Padding(
        padding: EdgeInsets.fromLTRB(padH, 0, padH, 4),
        child: Column(children: [
          Divider(color: cs.outlineVariant.withValues(alpha: 0.5)),
          _NavTile(
            expanded: expanded,
            selected: settingsSelected,
            icon: settingsSelected ? settingsDest.selected : settingsDest.icon,
            label: settingsDest.label,
            onTap: onSettings,
          ),
        ]),
      ),
      Padding(
        padding: const EdgeInsets.fromLTRB(8, 8, 8, 16),
        child: Tooltip(
          message: meEmail,
          child: InkWell(
            customBorder: const CircleBorder(),
            onTap: onAvatar,
            child: Avatar(meName, size: 36),
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
