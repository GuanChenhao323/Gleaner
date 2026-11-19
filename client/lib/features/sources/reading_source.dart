import 'dart:async';

import 'package:flutter_riverpod/flutter_riverpod.dart';

import 'package:flutter/material.dart';

import '../../core/api.dart';
import '../../core/session.dart';
import '../../l10n/app_localizations.dart';
import 'source_purge.dart';

String readingResultLabel(String value, BuildContext context) {
  final l10n = AppLocalizations.of(context);
  return switch (value) {
    'result_rejected' => l10n.rrRejected,
    'documents_purged' => l10n.rrPurged,
    'starting' => l10n.rrStarting,
    'user_busy' => l10n.rrUserBusy,
    'tab_missing' => l10n.rrTabMissing,
    'tab_rebind_required' => l10n.rrTabRebind,
    'tab_ambiguous' => l10n.rrTabAmbiguous,
    'single_account_conflict' => l10n.rrSingleAccount,
    'restored' => l10n.rrRestored,
    'documents_restored' => l10n.rrDocsRestored,
    'documents_trashed' => l10n.rrDocsTrashed,
    'private_source_required' => l10n.rrPrivateRequired,
    'not_executed' => l10n.bcNotExecuted,
    'verified' => l10n.rrVerified,
    'changed' => l10n.bcChanged,
    'unchanged' => l10n.bcUnchanged,
    'need_login' => l10n.bcNeedLogin,
    'account_unknown' => l10n.rrAccountUnknown,
    'account_mismatch' => l10n.rrAccountMismatch,
    'no_match' => l10n.rrNoMatch,
    'view_mismatch' => l10n.bcViewMismatch,
    'route_mismatch' => l10n.bcRouteMismatch,
    'permission_denied' => l10n.bcPermissionDenied,
    'render_timeout' => l10n.bcRenderTimeout,
    'worker_interrupted' => l10n.rrWorkerInterrupted,
    'preview_only' => l10n.rrPreviewOnly,
    'selection_missing' => l10n.bcSelectionMissing,
    'unsupported' => l10n.rrUnsupported,
    _ => l10n.bcFailed,
  };
}

class ReadingSource {
  final int id, revision, interval, effectiveInterval, matchCount;
  final String mode, result, capability, pending, executionState;
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
      executionState = (data['execution_state'] ?? 'idle') as String,
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
  String loginRequirement(BuildContext context) {
    final l10n = AppLocalizations.of(context);
    if (resident && platform == 'generic' && (recipe['binding'] as Map)['account_key'] == 'unverified') {
      return l10n.rsLoginReuse;
    }
    return isPublic ? l10n.rsLoginNone : l10n.rsLoginRequired;
  }

  String identity(BuildContext context) {
    final l10n = AppLocalizations.of(context);
    if (resident) {
      return platform == 'generic' ? l10n.rsIdResidentGeneric : l10n.rsIdResidentSchool;
    }
    if (isPublic) return l10n.rsIdPublic;
    if (platform == 'generic') {
      final probe = recipe['account_probe'] is Map ? (recipe['account_probe'] as Map)['display'] : l10n.rsAccountUnchecked;
      return '${recipe['source_label']} · $probe';
    }
    return l10n.rsIdSchoolChrome;
  }

  String title(BuildContext context) {
    final l10n = AppLocalizations.of(context);
    final kind = isTimeline
        ? l10n.rsTitleTimeline
        : switch (platform) {
            'moodle' => 'Moodle',
            'student' => 'WeMust',
            'fie' => l10n.rsTitleTeacher,
            'generic' => l10n.rsTitleWeb,
            _ => platform,
          };
    return '$kind · $query';
  }

  String scope(BuildContext context) {
    final l10n = AppLocalizations.of(context);
    if (recipe['match_scope'] == 'title') return l10n.rsScopeTitle;
    if (isTimeline) return l10n.rsScopeTimeline;
    if (platform == 'generic') return l10n.rsScopeBody;
    return l10n.rsScopeOriginal;
  }

  bool get active => executionState != 'expired' && (pending.isNotEmpty || activeJob != null);
  bool get periodic => mode == 'periodic' && !paused && verified;

  String statusLabel(BuildContext context) {
    final l10n = AppLocalizations.of(context);
    if (executionState == 'expired') return l10n.rsExpired;
    if (active) {
      if (!deviceOnline) return l10n.rsWaitChrome;
      return activeJob == null ? l10n.rsQueued : l10n.rsChecking;
    }
    return readingResultLabel(capability == 'account_unknown' ? 'account_unknown' : result, context);
  }
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
      throw const FormatException('Permanent delete scope was not fully confirmed');
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
