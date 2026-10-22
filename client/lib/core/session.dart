import 'dart:convert';

import 'package:flutter/foundation.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:shared_preferences/shared_preferences.dart';

import 'api.dart';
import 'models.dart';

final prefsProvider = Provider<SharedPreferences>((ref) => throw UnimplementedError('override in main'));

/// Web 版由网关同源分发，直接用当前页面的源；其他平台可在登录页修改服务器地址。
String defaultServer() {
  const fromEnv = String.fromEnvironment('GLEANER_SERVER');
  if (fromEnv.isNotEmpty) return fromEnv;
  if (kIsWeb) return Uri.base.origin;
  if (defaultTargetPlatform == TargetPlatform.android) return 'http://10.0.2.2:8080';
  return 'http://localhost:8080';
}

class Session {
  final String server;
  final String? token;
  final Me? me;
  const Session({required this.server, this.token, this.me});
  bool get loggedIn => token != null;
  Session copyWith({String? server, String? token, Me? me, bool clear = false}) =>
      Session(server: server ?? this.server, token: clear ? null : token ?? this.token, me: clear ? null : me ?? this.me);
}

class SessionNotifier extends Notifier<Session> {
  SharedPreferences get _p => ref.read(prefsProvider);

  @override
  Session build() {
    final p = ref.read(prefsProvider);
    final meJson = p.getString('me');
    return Session(
      server: p.getString('server') ?? defaultServer(),
      token: p.getString('token'),
      me: meJson == null ? null : Me.fromJson(Map<String, dynamic>.from(jsonDecode(meJson) as Map)),
    );
  }

  Future<void> setServer(String s) async {
    final v = s.trim().replaceAll(RegExp(r'/+$'), '');
    await _p.setString('server', v);
    state = state.copyWith(server: v);
  }

  Future<void> signedIn(Map<String, dynamic> resp) async {
    final token = resp['token'] as String;
    final me = Me.fromJson(Map<String, dynamic>.from(resp['user'] as Map));
    await _p.setString('token', token);
    await _p.setString('me', jsonEncode(resp['user']));
    state = state.copyWith(token: token, me: me);
  }

  Future<void> updateMe(Me me, Map<String, dynamic> raw) async {
    await _p.setString('me', jsonEncode(raw));
    state = state.copyWith(me: me);
  }

  Future<void> signOut() async {
    await _p.remove('token');
    await _p.remove('me');
    state = state.copyWith(clear: true);
  }
}

final sessionProvider = NotifierProvider<SessionNotifier, Session>(SessionNotifier.new);

final apiProvider = Provider<Api>((ref) {
  final s = ref.watch(sessionProvider);
  return Api(s.server, token: s.token);
});
