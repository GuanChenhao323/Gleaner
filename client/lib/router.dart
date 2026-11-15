import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:go_router/go_router.dart';

import 'core/session.dart';
import 'features/assignments/assignments_page.dart';
import 'features/auth/login_page.dart';
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

/// 登录状态变化时让 GoRouter 重新计算 redirect。
class _AuthListenable extends ChangeNotifier {
  _AuthListenable(Ref ref) {
    ref.listen(sessionProvider.select((s) => s.loggedIn), (_, _) => notifyListeners());
  }
}

final routerProvider = Provider<GoRouter>((ref) {
  final auth = _AuthListenable(ref);
  NoTransitionPage<void> page(Widget w) => NoTransitionPage(child: w);
  return GoRouter(
    refreshListenable: auth,
    redirect: (context, state) {
      final loggedIn = ref.read(sessionProvider).loggedIn;
      final loc = state.matchedLocation;
      // 扫码加入传输会话不要求登录（手机可能还没有账号）
      if (loc.startsWith('/transfer/')) return null;
      // 日历已并入作业页
      if (loc == '/calendar') return loggedIn ? '/assignments?view=calendar' : '/login';
      if (!loggedIn && loc != '/login') return '/login';
      if (loggedIn && loc == '/login') return '/';
      return null;
    },
    routes: [
      GoRoute(path: '/login', builder: (_, _) => const LoginPage()),
      GoRoute(path: '/item/:id', builder: (_, s) => ItemDetail(id: int.parse(s.pathParameters['id']!))),
      GoRoute(path: '/compose', builder: (_, _) => const ComposePage()),
      GoRoute(path: '/transfer', builder: (_, _) => const TransferPage()),
      GoRoute(path: '/transfer/:code', builder: (_, s) => TransferPage(code: s.pathParameters['code'])),
      GoRoute(path: '/settings/rules', builder: (_, _) => const RulesPage()),
      ShellRoute(
        builder: (context, state, child) => AppShell(location: state.matchedLocation, child: child),
        routes: [
          GoRoute(path: '/', pageBuilder: (_, _) => page(const DashboardPage())),
          GoRoute(
            path: '/inbox',
            pageBuilder: (_, s) => page(InboxPage(
              key: ValueKey(s.uri.queryParameters['filter']),
              initial: parseInboxFilter(s.uri.queryParameters['filter']),
            )),
          ),
          GoRoute(
            path: '/assignments',
            pageBuilder: (_, s) => page(AssignmentsPage(
              key: ValueKey(s.uri.queryParameters['view']),
              initialCalendar: s.uri.queryParameters['view'] == 'calendar',
            )),
          ),
          GoRoute(path: '/courses', pageBuilder: (_, _) => page(const CoursesPage())),
          GoRoute(path: '/sources', pageBuilder: (_, _) => page(const SourcesPage())),
          GoRoute(path: '/sources/:id', pageBuilder: (_, s) => page(ReadingDetailPage(id: int.parse(s.pathParameters['id']!), showChanges: s.uri.queryParameters['tab']=='changes'))),
          GoRoute(path: '/sources/:id/settings', pageBuilder: (_, s) => page(ReadingSettingsPage(id: int.parse(s.pathParameters['id']!)))),
          GoRoute(path: '/sources/:id/checks', pageBuilder: (_, s) => page(ReadingChecksPage(id: int.parse(s.pathParameters['id']!)))),
          GoRoute(path: '/settings', pageBuilder: (_, _) => page(const SettingsPage())),
        ],
      ),
    ],
  );
});
