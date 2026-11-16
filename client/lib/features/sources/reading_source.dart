import 'dart:async';

import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../core/api.dart';
import '../../core/session.dart';
import 'source_purge.dart';

String readingResultLabel(String value) => switch (value) {
  'documents_purged' => '关联资料已彻底删除 · 请在原网页重新提取',
  'starting' => '自动监测启动中 · 等待首次刷新',
  'user_busy' => '监测页正在编辑 · 延后刷新',
  'tab_missing' => '监测页已关闭 · 请打开原页后重新绑定',
  'tab_rebind_required' => '浏览器会话已重启 · 请重新绑定监测页',
  'tab_ambiguous' => '打开了多个相同网页 · 请保留一个监测页',
  'single_account_conflict' => '本站已绑定另一账号 · 已暂停',
  'restored' => '来源已恢复 · 检查暂停，须重新测试',
  'documents_restored' => '资料已恢复 · 来源检查保持暂停',
  'documents_trashed' => '关联资料已移入回收站 · 检查已暂停',
  'private_source_required' => '检测到登录账号 · 请按需要登录的来源重新采集',
  'not_executed' => '待首次检查',
  'verified' => '重读验证通过 · 待检查',
  'changed' => '发现来源变化',
  'unchanged' => '检查成功 · 无变化',
  'need_login' => '需在原站重新登录',
  'account_unknown' => '无法核对来源账号 · 保留手动采集',
  'account_mismatch' => '来源账号不符 · 已暂停',
  'no_match' => '本次未匹配 · 已保留旧资料',
  'view_mismatch' => '来源视图不符 · 需要重新确认',
  'route_mismatch' => '来源路由改变 · 需要重新采集',
  'permission_denied' => '请在原网页打开插件重新授权',
  'render_timeout' => '页面渲染超时',
  'worker_interrupted' => '浏览器任务中断 · 可重试',
  'preview_only' => '本次内容不完整 · 未覆盖资料',
  'selection_missing' => '原文定位失效',
  'unsupported' => '暂不支持后台重读',
  _ => '检查失败',
};

class ReadingSource {
  final int id, revision, interval, effectiveInterval, matchCount;
  final String mode, result, capability, pending;
  final bool paused, verified, deviceOnline;
  final num? lastSuccess, lastAttempt, nextAt;
  final Map<String, dynamic> recipe;
  final Map<String, dynamic>? activeJob;
  final List<Map<String, dynamic>> items;
  ReadingSource.fromJson(Map<String, dynamic> data)
    : id = data['id'] as int,
      revision = data['revision'] as int,
      interval = data['interval_s'] as int,
      effectiveInterval =
          (data['effective_interval_s'] ?? data['interval_s']) as int,
      matchCount = data['match_count'] as int,
      mode = data['mode'] as String,
      result = data['last_result'] as String,
      capability = data['capability'] as String,
      pending = data['pending'] as String,
      paused = data['paused'] as bool,
      verified = data['verified'] as bool,
      deviceOnline = data['device_online'] as bool,
      lastSuccess = data['last_success_at'] as num?,
      lastAttempt = data['last_attempt_at'] as num?,
      nextAt = data['next_at'] as num?,
      recipe = Map<String, dynamic>.from(data['recipe'] as Map),
      activeJob = data['active_job'] == null
          ? null
          : Map<String, dynamic>.from(data['active_job'] as Map),
      items = (data['items'] as List)
          .map((m) => Map<String, dynamic>.from(m as Map))
          .toList();
  String get query => recipe['query'] as String;
  String get url => recipe['url'] as String;
  String get platform => recipe['source'] as String;
  bool get resident => recipe['resident'] is Map;
  String? get pageId =>
      resident ? (recipe['resident'] as Map)['page_id'] as String : null;
  bool get isTimeline => recipe['representation'] == 'timeline_summary';
  bool get isPublic => (recipe['binding'] as Map)['account_key'] == 'public';
  String get loginRequirement =>
      resident &&
          platform == 'generic' &&
          (recipe['binding'] as Map)['account_key'] == 'unverified'
      ? '复用当前Chrome会话（用户确认）'
      : isPublic
      ? '无需登录（声明）'
      : '需要登录';
  String get identity => resident
      ? (platform == 'generic' ? '专用监测页 · 单账号会话（用户确认）' : '原学校账号 · 专用监测页')
      : isPublic
      ? '无需登录（用户声明）'
      : platform == 'generic'
      ? '${recipe['source_label']} · ${recipe['account_probe'] is Map ? (recipe['account_probe'] as Map)['display'] : '账号未核对'}'
      : '原学校账号 · 本机 Chrome';
  String get title =>
      '${isTimeline ? 'Moodle 活动摘要' : const {'moodle': 'Moodle', 'student': 'WeMust', 'fie': '教师资料', 'generic': '网页资料'}[platform] ?? platform} · $query';
  String get scope => recipe['match_scope'] == 'title'
      ? '标题与链接标题'
      : isTimeline
      ? '当前已加载活动 · 摘要整组'
      : platform == 'generic'
      ? '正文与列表 · 整组匹配'
      : '原条件与约定视图';
  bool get active => pending.isNotEmpty || activeJob != null;
  bool get periodic => mode == 'periodic' && !paused && verified;
  String get status => active
      ? deviceOnline
            ? (activeJob == null ? '已排队 · 等待执行' : '浏览器检查中')
            : '等待本机 Chrome'
      : readingResultLabel(
          capability == 'account_unknown' ? 'account_unknown' : result,
        );
  Map<String, dynamic> settings({String? mode, bool? paused, int? interval}) =>
      {
        'revision': revision,
        'mode': mode ?? this.mode,
        'paused': paused ?? this.paused,
        'interval_s': interval ?? this.interval,
      };
}

abstract interface class ReadingSourceRepository {
  Future<List<ReadingSource>> list();
  Future<void> configure(ReadingSource source, Map<String, dynamic> settings);
  Future<void> check(ReadingSource source, String purpose);
  Future<void> activate(ReadingSource source, int interval);
  Future<void> remove(ReadingSource source, bool trashItems);
  Future<List<Map<String, dynamic>>> deleted();
  Future<void> restore(int id, int revision);
  Future<SourcePurgePlan> purgePreview(int id);
  Future<SourcePurgeResult> purge(SourcePurgePlan plan);
  Future<List<Map<String, dynamic>>> checks(int id);
}

class ApiReadingSourceRepository implements ReadingSourceRepository {
  final Api api;
  ApiReadingSourceRepository(this.api);
  @override
  Future<List<ReadingSource>> list() async =>
      (await api.readingSources()).map(ReadingSource.fromJson).toList();
  @override
  Future<void> configure(ReadingSource source, Map<String, dynamic> settings) =>
      api.configureReading(source.id, settings);
  @override
  Future<void> activate(ReadingSource source, int interval) =>
      api.activateReading(source.id, source.revision, interval);
  @override
  Future<void> check(ReadingSource source, String purpose) =>
      api.checkReading(source.id, source.revision, purpose);
  @override
  Future<List<Map<String, dynamic>>> deleted() => api.deletedReadingSources();
  @override
  Future<SourcePurgePlan> purgePreview(int id) async =>
      SourcePurgePlan.fromJson(await api.purgeReadingPreview(id));
  @override
  Future<SourcePurgeResult> purge(SourcePurgePlan plan) async {
    final value = await api.purgeReading(plan.sourceId, plan.body);
    final result = SourcePurgeResult.fromJson(value);
    if (result.itemIds.join(',') != plan.itemIds.join(',') ||
        result.generation <= plan.generation) {
      throw const FormatException('永久删除范围未获完整确认');
    }
    return result;
  }

  @override
  Future<void> restore(int id, int revision) =>
      api.restoreReading(id, revision);
  @override
  Future<void> remove(ReadingSource source, bool trashItems) =>
      api.removeReading(source.id, source.revision, trashItems);
  @override
  Future<List<Map<String, dynamic>>> checks(int id) => api.readingChecks(id);
}

final readingRepositoryProvider = Provider<ReadingSourceRepository>(
  (ref) => ApiReadingSourceRepository(ref.watch(apiProvider)),
);

class ReadingSourcesController extends AsyncNotifier<List<ReadingSource>> {
  @override
  Future<List<ReadingSource>> build() {
    final repo = ref.watch(readingRepositoryProvider);
    final timer = Timer.periodic(const Duration(seconds: 10), (_) {
      refresh().catchError((Object _) {});
    });
    ref.onDispose(timer.cancel);
    return repo.list();
  }

  Future<void> refresh() async {
    final repo = ref.read(readingRepositoryProvider);
    final next = await repo.list();
    if (ref.mounted && identical(repo, ref.read(readingRepositoryProvider))) {
      state = AsyncData(next);
    }
  }

  Future<void> remove(ReadingSource source, bool trashItems) async {
    await ref.read(readingRepositoryProvider).remove(source, trashItems);
    if (ref.mounted) {
      ref.invalidate(deletedReadingSourcesProvider);
      await refresh();
    }
  }

  Future<void> restore(int id, int revision) async {
    await ref.read(readingRepositoryProvider).restore(id, revision);
    if (ref.mounted) {
      ref.invalidate(deletedReadingSourcesProvider);
      await refresh();
    }
  }

  Future<void> activate(ReadingSource source, int interval) async {
    await ref.read(readingRepositoryProvider).activate(source, interval);
    if (ref.mounted) await refresh();
  }

  Future<void> check(ReadingSource source, String purpose) async {
    await ref.read(readingRepositoryProvider).check(source, purpose);
    if (ref.mounted) await refresh();
  }

  Future<void> configure(
    ReadingSource source,
    Map<String, dynamic> settings,
  ) async {
    await ref.read(readingRepositoryProvider).configure(source, settings);
    if (ref.mounted) await refresh();
  }
}

final readingSourcesProvider =
    AsyncNotifierProvider.autoDispose<
      ReadingSourcesController,
      List<ReadingSource>
    >(ReadingSourcesController.new);

final deletedReadingSourcesProvider =
    FutureProvider.autoDispose<List<Map<String, dynamic>>>(
      (ref) => ref.watch(readingRepositoryProvider).deleted(),
    );
