import 'dart:async';
import 'dart:convert';

import 'package:flutter/foundation.dart';
import 'package:flutter/widgets.dart';
import 'package:flutter_local_notifications/flutter_local_notifications.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:mqtt_client/mqtt_client.dart';

import 'mqtt/factory_stub.dart' if (dart.library.io) 'mqtt/factory_io.dart' if (dart.library.js_interop) 'mqtt/factory_web.dart';
import 'session.dart';
import 'store.dart';

/// 系统通知：紧急事项在应用不在前台（或实时连接断开）时弹出。
class Notifier2 {
  final _plugin = FlutterLocalNotificationsPlugin();
  bool _ready = false;
  int _id = 1;

  Future<void> init() async {
    if (_ready) return;
    try {
      await _plugin.initialize(
        settings: const InitializationSettings(
          android: AndroidInitializationSettings('@mipmap/ic_launcher'),
          windows: WindowsInitializationSettings(appName: '拾课', appUserModelId: 'Gleaner.Gleaner.App.1', guid: 'b5e1a3c4-7d2f-4c1a-9e0b-3f6a2d8c1e57'),
          web: WebInitializationSettings(),
        ),
      );
      _ready = true;
    } catch (e) {
      debugPrint('notifications unavailable: $e');
    }
  }

  Future<void> show(String title, String body) async {
    if (!_ready) return;
    try {
      await _plugin.show(
        id: _id++,
        title: title,
        body: body,
        notificationDetails: const NotificationDetails(
          android: AndroidNotificationDetails('urgent', '紧急提醒', importance: Importance.high, priority: Priority.high),
        ),
      );
    } catch (e) {
      debugPrint('notify failed: $e');
    }
  }
}

final systemNotifierProvider = Provider<Notifier2>((ref) => Notifier2()..init());

enum MqttConn { off, connecting, on }

/// MQTT 通知通道：持久会话（Clean Session = 0），离线期间的 QoS 1 消息在重连后补收。
class MqttService extends Notifier<MqttConn> with WidgetsBindingObserver {
  MqttClient? _client;
  StreamSubscription<dynamic>? _sub;
  bool _foreground = true;

  @override
  MqttConn build() {
    final s = ref.watch(sessionProvider);
    ref.onDispose(() {
      WidgetsBinding.instance.removeObserver(this);
      _sub?.cancel();
      _client?.disconnect();
    });
    WidgetsBinding.instance.addObserver(this);
    if (s.loggedIn && s.me != null && s.me!.mqttUser.isNotEmpty) {
      Future.microtask(() => _connect(s));
    }
    return MqttConn.off;
  }

  @override
  void didChangeAppLifecycleState(AppLifecycleState state) => _foreground = state == AppLifecycleState.resumed;

  Future<void> _connect(Session s) async {
    final me = s.me!;
    final clientId = 'gleaner-${me.id}-${kIsWeb ? 'web' : defaultTargetPlatform.name}';
    MqttClient c;
    try {
      c = createMqttClient(Uri.parse(s.server), clientId);
    } catch (_) {
      return;
    }
    c.logging(on: false);
    c.setProtocolV311(); // 自研 Broker 实现的是 MQTT 3.1.1（协议名 MQTT，级别 4）
    c.keepAlivePeriod = 60;
    c.autoReconnect = true;
    c.connectionMessage = MqttConnectMessage().withClientIdentifier(clientId).authenticateAs(me.mqttUser, me.mqttPassword);
    c.onConnected = () {
      state = MqttConn.on;
      c.subscribe('gleaner/u/${me.id}/#', MqttQos.atLeastOnce);
    };
    c.onDisconnected = () => state = MqttConn.off;
    _client = c;
    state = MqttConn.connecting;
    try {
      await c.connect();
    } catch (e) {
      debugPrint('mqtt connect failed: $e');
      state = MqttConn.off;
      return;
    }
    c.subscribe('gleaner/u/${me.id}/#', MqttQos.atLeastOnce);
    _sub = c.updates?.listen((msgs) {
      for (final m in msgs) {
        final p = m.payload;
        if (p is! MqttPublishMessage) continue;
        _onMessage(m.topic, utf8.decode(p.payload.message.toList()));
      }
    });
  }

  void _onMessage(String topic, String payload) {
    Map<String, dynamic> j;
    try {
      j = Map<String, dynamic>.from(jsonDecode(payload) as Map);
    } catch (_) {
      return;
    }
    final online = ref.read(feedProvider).conn == Conn.online;
    // 前台且实时连接正常时由界面内提示，避免重复打扰
    if (_foreground && online && !topic.endsWith('/digest')) return;
    final title = topic.endsWith('/digest') ? '拾课 · 今日摘要' : (j['title'] ?? '拾课提醒').toString();
    final body = topic.endsWith('/digest') ? '新事项 ${j['new_count'] ?? 0} 条' : (j['body'] ?? '').toString();
    ref.read(systemNotifierProvider).show(title, body);
  }
}

final mqttProvider = NotifierProvider<MqttService, MqttConn>(MqttService.new);
