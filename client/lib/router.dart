import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:go_router/go_router.dart';

import 'core/session.dart';
import 'features/courses/course_detail_page.dart';
import 'features/courses/courses_page.dart';
import 'features/dashboard/dashboard_page.dart';
import 'features/inbox/inbox_page.dart';
import 'features/inbox/item_detail.dart';
import 'features/mail/compose_page.dart';
import 'features/settings/settings_page.dart';
import 'features/shell/app_shell.dart';
import 'features/sources/sources_page.dart';
import 'features/sources/reading_settings.dart';
import 'features/sources/reading_detail.dart';
import 'features/transfer/transfer_page.dart';

final routerProvider = Provider<GoRouter>((ref) {
  NoTransitionPage<void> page(Widget w) => NoTransitionPage(child: w);
  final router = GoRouter(
    redirect: (context, state) {
      final loggedIn = ref.read(sessionProvider).loggedIn;
      final loc = state.matchedLocation;
      // 扫码加入传输会话不要求登录（手机可能还没有账号）
      if (loc.startsWith('/transfer/')) return null;
      if (loc == '/calendar' || loc == '/assignments' || loc.startsWith('/assignments')) {
        return '/';
      }
      if (loc == '/login') return '/';
      if (!loggedIn && !destinations.any((d) => d.path == loc) && loc != settingsDest.path) {
        return Uri(path: '/', queryParameters: {'next': state.uri.toString()}).toString();
      }
      if (loggedIn && loc == '/') {
        final next = Uri.tryParse(state.uri.queryParameters['next'] ?? '');
        if (next != null && !next.hasScheme && !next.hasAuthority &&
            next.path.startsWith('/') && next.path != '/' && next.path != '/login') {
          return next.toString();
        }
      }
      return null;
    },
    routes: [
      GoRoute(path: '/login', redirect: (_, _) => '/'),
      GoRoute(path: '/item/:id', builder: (_, s) => ItemDetail(id: int.parse(s.pathParameters['id']!))),
      GoRoute(path: '/compose', builder: (_, _) => const ComposePage()),
      GoRoute(path: '/transfer', builder: (_, _) => const TransferPage()),
      GoRoute(path: '/transfer/:code', builder: (_, s) => TransferPage(code: s.pathParameters['code'])),
      GoRoute(path: '/settings/rules', builder: (_, _) => const RulesPage()),
      ShellRoute(
        builder: (context, state, child) => AppShell(location: state.matchedLocation, child: child),
        routes: [
          GoRoute(path: '/', pageBuilder: (_, state) {
            final type = state.uri.queryParameters['type'];
            return page(DashboardPage(
              key: ValueKey(state.uri.query),
              initialType: type,
              focusItemId: int.tryParse(state.uri.queryParameters['item'] ?? ''),
            ));
          }),
          GoRoute(
            path: '/inbox',
            pageBuilder: (_, s) => page(InboxPage(
              key: ValueKey(s.uri.queryParameters['filter']),
              initial: parseInboxFilter(s.uri.queryParameters['filter']),
            )),
          ),
          GoRoute(path: '/courses', pageBuilder: (_, _) => page(const CoursesPage())),
          GoRoute(
            path: '/courses/detail',
            pageBuilder: (_, s) {
              final fromExtra = s.extra is String ? s.extra as String : null;
              final name = fromExtra ?? s.uri.queryParameters['name'] ?? '';
              return page(CourseDetailPage(name: name));
            },
          ),
          GoRoute(path: '/sources', pageBuilder: (_, _) => page(const SourcesPage())),
          GoRoute(path: '/sources/:id', pageBuilder: (_, s) => page(ReadingDetailPage(id: int.parse(s.pathParameters['id']!), showChanges: s.uri.queryParameters['tab']=='changes'))),
          GoRoute(path: '/sources/:id/settings', pageBuilder: (_, s) => page(ReadingSettingsPage(id: int.parse(s.pathParameters['id']!)))),
          GoRoute(path: '/sources/:id/checks', pageBuilder: (_, s) => page(ReadingChecksPage(id: int.parse(s.pathParameters['id']!)))),
          GoRoute(path: '/settings', pageBuilder: (_, _) => page(const SettingsPage())),
        ],
      ),
    ],
  );
  ref.listen(sessionProvider.select((s) => s.loggedIn), (_, signedIn) {
    if (signedIn) {
      router.refresh();
    } else {
      router.go('/');
    }
  });
  ref.onDispose(router.dispose);
  return router;
});
