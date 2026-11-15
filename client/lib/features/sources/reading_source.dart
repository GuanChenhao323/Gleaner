import 'dart:async';

import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../core/api.dart';
import '../../core/session.dart';

String readingResultLabel(String value) => switch (value) {
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
  final int id, revision, interval, matchCount;
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
  bool get isPublic => (recipe['binding'] as Map)['account_key'] == 'public';
  String get identity => isPublic
      ? '公开网页'
      : platform == 'generic'
      ? '${recipe['source_label']} · 账号未核对'
      : '原学校账号 · 本机 Chrome';
  String get title =>
      '${const {'moodle': 'Moodle', 'student': 'WeMust', 'fie': '教师资料', 'generic': '网页资料'}[platform] ?? platform} · $query';
  String get scope => recipe['match_scope'] == 'title'
      ? '标题与链接标题'
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
  Future<void> check(ReadingSource source, String purpose) =>
      api.checkReading(source.id, source.revision, purpose);
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
