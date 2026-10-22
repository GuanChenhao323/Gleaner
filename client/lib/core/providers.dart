import 'package:flutter_riverpod/flutter_riverpod.dart';

import 'models.dart';
import 'session.dart';
import 'store.dart';

final templatesProvider = FutureProvider<List<SourceTemplate>>((ref) => ref.watch(apiProvider).templates());

final sourcesProvider = FutureProvider<List<Source>>((ref) async {
  // 来源状态变化（需要重新登录、恢复）时刷新
  ref.watch(feedProvider.select((s) => s.cursor));
  return ref.watch(apiProvider).sources();
});

final coursesProvider = FutureProvider<List<Course>>((ref) async {
  ref.watch(feedProvider.select((s) => s.cursor));
  return ref.watch(apiProvider).courses();
});

final rulesProvider = FutureProvider<List<Rule>>((ref) => ref.watch(apiProvider).rules());

final versionsProvider = FutureProvider.family<List<ItemVersion>, int>((ref, id) async {
  ref.watch(feedProvider.select((s) => s.items[id]?.version));
  return ref.watch(apiProvider).versions(id);
});

class DashboardNotifier extends AsyncNotifier<List<DashWidget>> {
  @override
  Future<List<DashWidget>> build() => ref.watch(apiProvider).dashboard();

  Future<void> save(List<DashWidget> ws) async {
    state = AsyncData(ws);
    await ref.read(apiProvider).saveDashboard(ws);
  }
}

final dashboardProvider = AsyncNotifierProvider<DashboardNotifier, List<DashWidget>>(DashboardNotifier.new);

/// 跨课程作业：按截止时间排序（场景 1“周日规划一周”）。
final assignmentsProvider = Provider<List<Item>>((ref) {
  final items = ref.watch(feedProvider.select((s) => s.items));
  final list = items.values.where((i) => i.isAssignment && !i.deleted && !i.state.hidden).toList();
  list.sort((a, b) => (a.effectiveDeadline ?? double.infinity).compareTo(b.effectiveDeadline ?? double.infinity));
  return list;
});

/// 所有带截止时间的事项（作业 + 通知里抽取出的截止时间），供日历使用。
final deadlinesProvider = Provider<List<Item>>((ref) {
  final items = ref.watch(feedProvider.select((s) => s.items));
  final list = items.values.where((i) => i.effectiveDeadline != null && !i.deleted && !i.state.hidden).toList();
  list.sort((a, b) => a.effectiveDeadline!.compareTo(b.effectiveDeadline!));
  return list;
});
