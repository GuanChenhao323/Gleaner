import 'dart:async';
import 'dart:convert';
import 'dart:math';

import 'package:flutter/foundation.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:uuid/uuid.dart';
import 'package:web_socket_channel/web_socket_channel.dart';

import 'api.dart';
import 'db.dart';
import 'document_lifecycle.dart';
import 'models.dart';
import 'session.dart';

enum Conn { offline, connecting, online }

/// 推给界面的事件：紧急提醒、来源状态变化、扫码配对等。
class AppEvent {
  final String type;
  final String title;
  final String body;
  final int? itemId;
  final String priority;
  final Map<String, dynamic> data;
  const AppEvent(this.type, this.title, this.body, {this.itemId, this.priority = 'normal', this.data = const {}});
}

class FeedState {
  final Map<int, Item> items;
  final int cursor;
  final Conn conn;
  final String? node;
  final int pending;
  final bool loading;
  final DateTime? lastSync;
  final String? error;

  const FeedState({
    this.items = const {},
    this.cursor = 0,
    this.conn = Conn.offline,
    this.node,
    this.pending = 0,
    this.loading = true,
    this.lastSync,
    this.error,
  });

  FeedState copyWith({Map<int, Item>? items, int? cursor, Conn? conn, String? node, int? pending, bool? loading, DateTime? lastSync, String? error, bool clearError = false}) =>
      FeedState(
        items: items ?? this.items,
        cursor: cursor ?? this.cursor,
        conn: conn ?? this.conn,
        node: node ?? this.node,
        pending: pending ?? this.pending,
        loading: loading ?? this.loading,
        lastSync: lastSync ?? this.lastSync,
        error: clearError ? null : error ?? this.error,
      );

  List<Item> get visible => items.values.where((i) => !i.deleted && !i.state.hidden).toList()..sort((a, b) => b.sortTime.compareTo(a.sortTime));
  List<Item> get trashed => items.values.where((i) => !i.deleted && i.state.hidden).toList()..sort((a, b) => b.sortTime.compareTo(a.sortTime));
  int get unread => items.values.where((i) => !i.deleted && !i.state.hidden && !i.state.read).length;
}

final localDbProvider = Provider<LocalDb>((ref) {
  final db = LocalDb.open();
  ref.onDispose(db.close);
  return db;
});

/// 同步引擎：离线优先（先读本地缓存）、WebSocket 实时推送、按 seq 增量补齐、离线操作按幂等键回放。
class FeedStore extends Notifier<FeedState> {
  final _events = StreamController<AppEvent>.broadcast();
  Stream<AppEvent> get events => _events.stream;
  WebSocketChannel? _ws;
  StreamSubscription<dynamic>? _wsSub;
  Timer? _reconnect;
  Timer? _syncDebounce;
  Timer? _ackTimer;
  Timer? _erasureTimer;
  int _backoff = 1;
  int _pendingAck = 0;
  bool _disposed = false;
  int _sessionGeneration = 0;
  final _uuid = const Uuid();
  final Set<int> _erasedIds = {};
  Future<void>? _erasureSync;

  Api get _api => ref.read(apiProvider);
  LocalDb get _db => ref.read(localDbProvider);

  @override
  FeedState build() {
    _disposed = false;
    final generation = ++_sessionGeneration;
    _erasedIds.clear();
    _erasureSync = null;
    _backoff = 1;
    _pendingAck = 0;
    ref.onDispose(() {
      _disposed = true;
      _ackTimer?.cancel();
      _ackTimer = null;
      _reconnect?.cancel();
      _syncDebounce?.cancel();
      _erasureTimer?.cancel();
      _wsSub?.cancel();
      _ws?.sink.close();
    });
    final token = ref.watch(sessionProvider.select((s) => s.token));
    if (token != null) {
      _erasureTimer = Timer.periodic(const Duration(minutes: 1), (_) {
        reconcileErasure().catchError((Object e) {
          debugPrint('erasure reconciliation failed: $e');
        });
      });
      Future.microtask(() => _bootstrap(generation));
    }
    return const FeedState();
  }

  bool _current(int generation) => !_disposed && generation == _sessionGeneration;

  Future<void> _bootstrap(int generation) async {
    if (!_current(generation)) return;
    // 1) 本地缓存：离线时照常浏览
    try {
      final cached = await _db.loadItems();
      final cur = int.tryParse(await _db.getKv('cursor') ?? '') ?? 0;
      final pend = (await _db.pending()).length;
      if (!_current(generation)) return;
      state = state.copyWith(items: {for (final j in cached) j['id'] as int: Item.fromJson(j)}, cursor: cur, pending: pend, loading: cached.isEmpty);
    } catch (e) {
      debugPrint('cache load failed: $e');
    }
    if (!_current(generation)) return;
    // 2) 网络：首次全量拉取；之后由 WebSocket hello 带 last_seq 补发
    try {
      if (state.cursor == 0 || state.items.isEmpty) {
        await refreshAll();
      } else {
        state = state.copyWith(loading: false);
      }
    } finally {
      // 本地缓存不可用（例如浏览器禁止 Worker / IndexedDB）时也要建立实时连接
      if (_current(generation)) _connect();
    }
  }

  Future<void> reconcileErasure() => _erasureSync ??=
      _reconcileErasure().whenComplete(() => _erasureSync = null);

  Future<void> _reconcileErasure() async {
    final api = _api, session = ref.read(sessionProvider);
    final context = await api.captureContext(), generation = context['generation'];
    if (_disposed || !identical(api, _api)) return;
    if (generation is! int || context['item_ids'] is! List) {
      throw const FormatException('Capture generation response invalid');
    }
    final key = 'capture_generation:${session.server}|${session.me?.id ?? 'current'}';
    if (await _db.getKv(key) == '$generation') return;
    final keep = (context['item_ids'] as List).cast<int>().toSet();
    _erasedIds.addAll(state.items.keys.where((id) => !keep.contains(id)));
    final next = {...state.items}..removeWhere((id, _) => !keep.contains(id));
    state = state.copyWith(items: next);
    final cleared = await _cache(() async {
      await _db.retainItems(keep);
      await _db.setKv(key, '$generation');
    });
    if (!cleared) throw StateError('Local cache cleanup failed. Reconnect and retry.');
  }

  Future<void> forgetPermanently(List<int> ids, int generation) async {
    _erasedIds.addAll(ids);
    final next = {...state.items}..removeWhere((id, _) => ids.contains(id));
    state = state.copyWith(items: next);
    final cleared = await _cache(() => _db.forgetItems(ids));
    if (!cleared) throw StateError('Local cache cleanup failed. Reconnect and retry.');
    await reconcileErasure();
    await refreshAll();
  }

  Future<void> refreshAll() async {
    final generation = _sessionGeneration;
    try {
      await reconcileErasure();
      if (!_current(generation)) return;
      final all = <int, Item>{};
      String? cursor;
      int syncCursor = state.cursor;
      for (final filter in [null, 'trash']) {
        cursor = null;
        for (var page = 0; page < 6; page++) {
          final f = await _api.feed(cursor: cursor, limit: 100, filter: filter);
          if (!_current(generation)) return;
          for (final j in (f['items'] as List)) {
            final it = Item.fromJson(Map<String, dynamic>.from(j as Map));
            all[it.id] = it;
          }
          syncCursor = max(syncCursor, (f['sync_cursor'] ?? 0) as int);
          cursor = f['next_cursor'] as String?;
          if (cursor == null) break;
        }
      }
      final merged = {...state.items}..removeWhere((k, v) => !all.containsKey(k) && !v.deleted);
      merged.addAll(all);
      state = state.copyWith(items: merged, cursor: syncCursor, loading: false, lastSync: DateTime.now(), clearError: true);
      await _cache(() async {
        await _db.saveItems(all.values.map((i) => i.toJson()));
        await _db.setKv('cursor', '$syncCursor');
      });
    } on ApiException catch (e) {
      if (!_current(generation)) return;
      state = state.copyWith(loading: false, error: e.message);
      if (e.status == 401) {
        await clearLocal();
        if (_current(generation)) await ref.read(sessionProvider.notifier).signOut();
      }
    }
  }

  // ---- WebSocket ----

  Uri _wsUri() {
    final s = ref.read(sessionProvider);
    final base = Uri.parse(s.server);
    return base.replace(scheme: base.scheme == 'https' ? 'wss' : 'ws', path: '/ws', queryParameters: {'token': s.token});
  }

  void _connect() {
    if (_disposed || !ref.read(sessionProvider).loggedIn) return;
    _reconnect?.cancel();
    state = state.copyWith(conn: Conn.connecting);
    try {
      final ch = WebSocketChannel.connect(_wsUri());
      _ws = ch;
      ch.ready.then((_) {
        ch.sink.add(jsonEncode({'type': 'hello', 'token': ref.read(sessionProvider).token, 'last_seq': state.cursor}));
      }).catchError((Object e) {
        _scheduleReconnect();
      });
      _wsSub = ch.stream.listen(_onMessage, onDone: _scheduleReconnect, onError: (_) => _scheduleReconnect(), cancelOnError: true);
    } catch (_) {
      _scheduleReconnect();
    }
  }

  void _scheduleReconnect() {
    if (_disposed) return;
    _wsSub?.cancel();
    _ws = null;
    state = state.copyWith(conn: Conn.offline);
    _reconnect?.cancel();
    // 指数退避 + 抖动：1s → 30s
    final delay = Duration(milliseconds: (_backoff * 1000 * (0.5 + Random().nextDouble())).round());
    _backoff = min(_backoff * 2, 30);
    _reconnect = Timer(delay, _connect);
  }

  void reconnectNow() {
    _backoff = 1;
    _wsSub?.cancel();
    _ws?.sink.close();
    _connect();
  }

  void _onMessage(dynamic raw) {
    final m = Map<String, dynamic>.from(jsonDecode(raw as String) as Map);
    final type = m['type'];
    switch (type) {
      case 'welcome':
        _backoff = 1;
        state = state.copyWith(conn: Conn.online, node: m['node'] as String?, lastSync: DateTime.now());
        reconcileErasure().then((_) {
          if (!_disposed) {
            flushPending();
            _scheduleSync();
          }
        }).catchError((Object e) { debugPrint('erasure sync failed: $e'); });
        _scheduleSync(); // 兜底：补齐握手期间可能错过的投递
      case 'item' || 'change' || 'reminder':
        _applyItemPayload(m);
      case 'purged':
        forgetPermanently((m['item_ids'] as List).cast<int>(), m['generation'] as int)
            .catchError((Object e) { debugPrint('purge cache failed: $e'); });
      case 'state':
        _applyState(m);
      case 'source_status':
        _events.add(AppEvent(
          'source_status',
          m['status'] == 'need_login' ? '“${m['name']}” needs sign-in again' : '“${m['name']}” check failed',
          m['status'] == 'need_login' ? 'Session expired. Sign in again under Sources.' : (m['error'] ?? '').toString(),
          priority: 'urgent',
          data: m,
        ));
        _advance(m);
      case 'digest':
        final d = Map<String, dynamic>.from(m['digest'] as Map);
        _events.add(AppEvent('digest', 'Daily digest', 'Past 24 hours: ${d['new_count']} new items, ${(d['upcoming'] as List).length} due soon', data: d));
      case 'transfer':
        _events.add(AppEvent('transfer', 'Scan transfer', (m['status'] ?? '').toString(), data: m));
      case 'resync_hint':
        _scheduleSync();
      case 'item_updated':
        // 字段修改、冲突处理、监测结果：重新拉取该事项详情（IC-002 4.5）
        final id = m['item_id'];
        if (id is int && state.items.containsKey(id)) loadDetail(id).catchError((_) => state.items[id]!);
    }
  }

  void _applyItemPayload(Map<String, dynamic> m) {
    final j = m['item'];
    if (j is Map) {
      final incoming = Map<String, dynamic>.from(j);
      final id = incoming['id'] as int;
      if (_erasedIds.contains(id)) {
        _advance(m);
        return;
      }
      final old = state.items[id];
      final it = old == null ? Item.fromJson(incoming) : old.merge(incoming);
      state = state.copyWith(items: {...state.items, id: it});
      _cache(() => _db.saveItems([it.toJson()]));
      final live = m['replay'] != true && m['silent'] != true;
      if (live && (m['priority'] == 'urgent' || m['type'] == 'reminder' || m['important'] == true)) {
        final title = m['type'] == 'reminder' ? 'Deadline reminder' : m['type'] == 'change' ? 'Important change' : 'New item';
        _events.add(AppEvent(m['type'] as String, '$title · ${it.title}', (m['note'] ?? m['text'] ?? it.summary).toString(), itemId: id, priority: 'urgent'));
      } else if (live && m['priority'] == 'normal') {
        _events.add(AppEvent(m['type'] as String, it.title, (m['note'] ?? it.summary).toString(), itemId: id));
      }
    }
    _advance(m);
  }

  void _advance(Map<String, dynamic> m) {
    final seq = m['seq'];
    if (seq is! int) return;
    if (seq > state.cursor + 1 && m['replay'] != true) {
      _scheduleSync(); // seq 有缺口（如背压丢弃）：经 /api/sync 补齐
    }
    if (seq > state.cursor) {
      state = state.copyWith(cursor: seq);
      _cache(() => _db.setKv('cursor', '$seq'));
      _pendingAck = max(_pendingAck, seq);
      _ackTimer ??= Timer(const Duration(milliseconds: 400), () {
        _ackTimer = null;
        _ws?.sink.add(jsonEncode({'type': 'ack', 'seq': _pendingAck}));
      });
    }
  }

  void _scheduleSync() {
    _syncDebounce?.cancel();
    _syncDebounce = Timer(const Duration(milliseconds: 600), syncNow);
  }

  /// GET /api/sync?cursor=：取回 cursor 之后的全部投递。
  Future<void> syncNow() async {
    final generation = _sessionGeneration;
    try {
      var more = true;
      while (more) {
        final r = await _api.sync(state.cursor);
        if (!_current(generation)) return;
        if (r['reset'] == true) {
          await refreshAll();
          return;
        }
        for (final d in (r['deliveries'] as List)) {
          final m = Map<String, dynamic>.from(d as Map)..['replay'] = true;
          if (m['item'] is Map) {
            _applyItemPayload(m);
          } else if (m['type'] == 'state') {
            _applyState(m);
          } else {
            _advance(m);
          }
        }
        final c = r['cursor'] as int;
        if (c > state.cursor) {
          state = state.copyWith(cursor: c);
          await _cache(() => _db.setKv('cursor', '$c'));
        }
        more = r['has_more'] == true;
      }
      state = state.copyWith(lastSync: DateTime.now(), clearError: true);
    } on ApiException catch (e) {
      if (!e.offline) state = state.copyWith(error: e.message);
    }
  }

  void _applyState(Map<String, dynamic> m) {
    final id = m['item_id'];
    final it = id is int ? state.items[id] : null;
    if (it != null && m['state'] is Map) {
      final next = it.withState(ItemState.fromJson(Map<String, dynamic>.from(m['state'] as Map)));
      state = state.copyWith(items: {...state.items, id: next});
      _cache(() => _db.saveItems([next.toJson()]));
    }
    final op = m['op_id'];
    if (op is String) {
      _cache(() => _db.dequeue([op])).then((_) => _refreshPendingCount());
    }
  }

  Future<void> _refreshPendingCount() async {
    try {
      final n = (await _db.pending()).length;
      if (n != state.pending) state = state.copyWith(pending: n);
    } catch (_) {}
  }

  /// 本地缓存（drift）写入：失败只影响离线浏览，不能打断在线流程。
  /// 例如浏览器禁止 Worker / IndexedDB 时，实时连接与操作照常进行。返回是否成功。
  Future<bool> _cache(Future<void> Function() write) async {
    try {
      await write();
      return true;
    } catch (e) {
      debugPrint('local cache unavailable: $e');
      return false;
    }
  }

  // ---- 个人状态：乐观更新 + 离线队列 ----

  Future<void> setState(Item item, {bool? read, bool? starred, String? todo, bool? hidden, String? note, bool? archived}) async {
    final patch = <String, dynamic>{
      'read': ?read,
      'starred': ?starred,
      'todo': ?todo,
      'hidden': ?hidden,
      'note': ?note,
      'archived': ?archived,
    };
    if (patch.isEmpty) return;
    final next = item.withState(
        item.state.copyWith(read: read, starred: starred, todo: todo, hidden: hidden, note: note, archived: archived));
    state = state.copyWith(items: {...state.items, item.id: next});
    final opId = _uuid.v4();
    final op = {...patch, 'item_id': item.id, 'op_id': opId, 'ts': DateTime.now().millisecondsSinceEpoch / 1000};
    await _cache(() => _db.saveItems([next.toJson()]));
    final queued = await _cache(() => _db.enqueue(opId, item.id, op));
    if (queued) state = state.copyWith(pending: state.pending + 1);
    // 队列写不进去时（本地数据库不可用）也直接发送，只是断网时无法回放
    if (state.conn == Conn.online || !queued) {
      try {
        await _api.putState(item.id, op, opId);
        if (queued) await _cache(() => _db.dequeue([opId]));
      } on ApiException catch (_) {
        // 离线：留在队列里，联网后回放
      }
      await _refreshPendingCount();
    }
  }

  Future<void> setTrashed(Item item, bool trashed) async {
    final api = _api;
    final repository = ref.read(documentLifecycleRepositoryProvider);
    final next = await repository.setTrashed(item.id, trashed);
    if (_disposed || !identical(api, _api)) throw StateError('Desk account changed. Please confirm again.');
    final current = state.items[item.id] ?? item;
    final value = current.withState(ItemState.fromJson(next));
    state = state.copyWith(items: {...state.items, item.id: value});
    await _cache(() => _db.saveItems([value.toJson()]));
  }

  Future<void> markAllRead(Iterable<Item> items) async {
    for (final i in items.where((i) => !i.state.read).toList()) {
      await setState(i, read: true);
    }
  }

  Future<void> flushPending() async {
    final List<PendingOp> ops;
    try {
      ops = await _db.pending();
    } catch (_) {
      return;
    }
    if (ops.isEmpty) return;
    try {
      final r = await _api.stateBatch(ops.map((o) => Map<String, dynamic>.from(jsonDecode(o.json) as Map)).toList());
      final done = <String>[];
      for (final res in (r['results'] as List)) {
        final m = Map<String, dynamic>.from(res as Map);
        if (m['status'] == 200 || m['status'] == 404) done.add(m['op_id'] as String);
      }
      await _cache(() => _db.dequeue(done));
    } on ApiException catch (_) {}
    await _refreshPendingCount();
  }

  Future<void> notImportant(Item item) async {
    await _api.notImportant(item.id);
    await setState(item, read: true);
  }

  Future<void> setItemLabels(Item item, List<int> labelIds) async {
    final ids = await _api.putItemLabels(item.id, labelIds);
    final next = item.withLabelIds(ids);
    state = state.copyWith(items: {...state.items, item.id: next});
    await _cache(() => _db.saveItems([next.toJson()]));
  }

  Future<Item> loadDetail(int id) async {
    final it = await _api.item(id);
    final old = state.items[id];
    final merged = old == null ? it : old.merge(it.raw);
    state = state.copyWith(items: {...state.items, id: merged});
    await _cache(() => _db.saveItems([merged.toJson()]));
    return merged;
  }

  /// 按类型切换处理状态：待办完成／未完成、日程归档／Cancel归档、通知已读／未读。
  Future<void> toggleStatus(Item item) => switch (item.type) {
        'todo' => setState(item, todo: item.isDone ? 'todo' : 'done'),
        'event' => setState(item, archived: !item.state.archived),
        _ => setState(item, read: !item.state.read),
      };

  void _put(Item it) {
    final old = state.items[it.id];
    final merged = old == null ? it : old.merge(it.raw);
    state = state.copyWith(items: {...state.items, it.id: merged});
    _cache(() => _db.saveItems([merged.toJson()]));
  }

  /// 修改字段（需要在线）：与来源版本分开Save，来源更新不会覆盖。
  Future<void> editFields(Item item, {Map<String, dynamic> set = const {}, List<String> reset = const []}) async =>
      _put(await _api.patchFields(item.id, set: set, reset: reset));

  Future<void> resolveConflict(Item item, String field, String keep) async =>
      _put(await _api.resolveField(item.id, field, keep));

  Future<void> setMonitor(Item item, bool enabled) async => _put(await _api.setMonitor(item.id, enabled));

  Future<void> clearLocal() async {
    await _db.wipe();
    state = const FeedState(loading: false);
  }
}

final feedProvider = NotifierProvider<FeedStore, FeedState>(FeedStore.new);
