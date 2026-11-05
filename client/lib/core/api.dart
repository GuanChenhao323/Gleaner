import 'package:dio/dio.dart';
import 'package:flutter/foundation.dart';

import 'models.dart';

class ApiException implements Exception {
  final int? status;
  final String code;
  final String message;
  ApiException(this.status, this.code, this.message);
  bool get offline => status == null;
  @override
  String toString() => message;
}

/// REST 客户端：所有请求经网关 /api。
class Api {
  final Dio dio;
  final String baseUrl;
  String? token;

  Api(this.baseUrl, {this.token})
      : dio = Dio(BaseOptions(
          baseUrl: baseUrl,
          connectTimeout: const Duration(seconds: 8),
          receiveTimeout: const Duration(seconds: 20),
          contentType: 'application/json',
          responseType: ResponseType.json,
          validateStatus: (_) => true,
        )) {
    dio.interceptors.add(InterceptorsWrapper(onRequest: (o, h) {
      if (token != null) o.headers['Authorization'] = 'Bearer $token';
      h.next(o);
    }));
  }

  Future<dynamic> _req(String method, String path, {Object? data, Map<String, dynamic>? query, Map<String, String>? headers}) async {
    Response r;
    try {
      r = await dio.request(path, data: data, queryParameters: query, options: Options(method: method, headers: headers));
    } on DioException catch (e) {
      throw ApiException(null, 'offline', '网络不可用：${e.message ?? e.type.name}');
    }
    final body = r.data;
    if ((r.statusCode ?? 500) >= 400) {
      final m = body is Map ? body : const {};
      throw ApiException(r.statusCode, (m['error'] ?? 'error').toString(), (m['message'] ?? '请求失败（${r.statusCode}）').toString());
    }
    return body;
  }

  Future<Map<String, dynamic>> _map(String method, String path, {Object? data, Map<String, dynamic>? query, Map<String, String>? headers}) async {
    final b = await _req(method, path, data: data, query: query, headers: headers);
    return Map<String, dynamic>.from((b ?? {}) as Map);
  }

  // ---- 账号 ----
  Future<Map<String, dynamic>> login(String email, String password) => _map('POST', '/api/auth/login', data: {'email': email, 'password': password});
  Future<Map<String, dynamic>> register(Map<String, dynamic> body) => _map('POST', '/api/auth/register', data: body);
  Future<Map<String, dynamic>> sendCode(String email) => _map('POST', '/api/auth/code', data: {'email': email});
  Future<void> logout({bool all = false}) => _req('POST', '/api/auth/logout', data: {'all_devices': all});
  Future<Me> me() async => Me.fromJson(await _map('GET', '/api/me'));
  Future<Me> updateMe(Map<String, dynamic> body) async => Me.fromJson(await _map('PUT', '/api/me', data: body));
  /// 删除账号需要再次输入密码（防止令牌被盗后被删号）。
  Future<void> deleteAccount(String password) => _req('DELETE', '/api/account', data: {'password': password});
  /// 修改密码：其他设备全部退出，返回当前设备的新令牌（与登录响应格式相同）。
  Future<Map<String, dynamic>> changePassword(String oldPassword, String newPassword) =>
      _map('PUT', '/api/me/password', data: {'old_password': oldPassword, 'new_password': newPassword});

  // ---- 事项 ----
  Future<Map<String, dynamic>> feed({String? cursor, String? kind, String? filter, String? q, int limit = 100}) => _map('GET', '/api/feed', query: {
        'cursor': ?cursor,
        'kind': ?kind,
        'filter': ?filter,
        if (q != null && q.isNotEmpty) 'q': q,
        'limit': limit,
      });
  Future<Map<String, dynamic>> sync(int cursor) => _map('GET', '/api/sync', query: {'cursor': cursor});
  Future<Item> item(int id) async => Item.fromJson(await _map('GET', '/api/items/$id'));
  Future<List<ItemVersion>> versions(int id) async {
    final m = await _map('GET', '/api/items/$id/versions');
    return (m['versions'] as List).map((e) => ItemVersion.fromJson(Map<String, dynamic>.from(e as Map))).toList();
  }

  Future<Map<String, dynamic>> putState(int id, Map<String, dynamic> body, String opId) =>
      _map('PUT', '/api/items/$id/state', data: body, headers: {'Idempotency-Key': opId});
  Future<Map<String, dynamic>> stateBatch(List<Map<String, dynamic>> ops) => _map('POST', '/api/state/batch', data: {'ops': ops});
  Future<void> notImportant(int id) => _req('POST', '/api/items/$id/feedback', data: {'not_important': true});
  Future<List<Course>> courses() async {
    final m = await _map('GET', '/api/courses');
    return (m['courses'] as List).map((e) => Course.fromJson(Map<String, dynamic>.from(e as Map))).toList();
  }

  // ---- 来源 ----
  Future<List<SourceTemplate>> templates() async {
    final m = await _map('GET', '/api/templates');
    return (m['templates'] as List).map((e) => SourceTemplate.fromJson(Map<String, dynamic>.from(e as Map))).toList();
  }

  Future<List<Source>> sources() async {
    final m = await _map('GET', '/api/sources');
    return (m['sources'] as List).map((e) => Source.fromJson(Map<String, dynamic>.from(e as Map))).toList();
  }

  Future<Map<String, dynamic>> addSource(Map<String, dynamic> body) => _map('POST', '/api/sources', data: body);
  Future<Map<String, dynamic>> previewSource(Map<String, dynamic> body) => _map('POST', '/api/sources/preview', data: body);
  Future<void> updateSource(int id, Map<String, dynamic> body) => _req('PUT', '/api/sources/$id', data: body);
  Future<void> removeSource(int id) => _req('DELETE', '/api/sources/$id');
  Future<Map<String, dynamic>> sourceLogin(int id, String user, String pw, {Map<String, dynamic>? smtp}) =>
      _map('POST', '/api/sources/$id/login', data: {'username': user, 'password': pw, 'smtp': ?smtp});
  /// 统一认证（CAS / SSO）的 Moodle：粘贴“偏好设置 → 安全密钥”里的密钥，不经手统一认证密码。
  Future<Map<String, dynamic>> sourceLoginToken(int id, String token) => _map('POST', '/api/sources/$id/login', data: {'token': token});
  Future<void> refreshSource(int id) => _req('POST', '/api/sources/$id/refresh');

  // ---- 邮件 ----
  Future<Map<String, dynamic>> sendMail(Map<String, dynamic> body, String key) => _map('POST', '/api/mail/send', data: body, headers: {'Idempotency-Key': key});
  Future<List<Map<String, dynamic>>> sentMails() async {
    final m = await _map('GET', '/api/mail/sent');
    return (m['mails'] as List).map((e) => Map<String, dynamic>.from(e as Map)).toList();
  }

  // ---- 看板与规则 ----
  Future<List<DashWidget>> dashboard() async {
    final m = await _map('GET', '/api/dashboard');
    final layout = Map<String, dynamic>.from(m['layout'] as Map);
    return (layout['widgets'] as List).map((e) => DashWidget.fromJson(Map<String, dynamic>.from(e as Map))).toList();
  }

  Future<void> saveDashboard(List<DashWidget> ws) => _req('PUT', '/api/dashboard', data: {
        'layout': {'widgets': ws.map((w) => w.toJson()).toList()}
      });
  Future<List<Rule>> rules() async {
    final m = await _map('GET', '/api/rules');
    return (m['rules'] as List).map((e) => Rule.fromJson(Map<String, dynamic>.from(e as Map))).toList();
  }

  Future<void> saveRules(List<Rule> rules) => _req('PUT', '/api/rules', data: {'rules': rules.map((r) => r.toJson()).toList()});

  // ---- 扫码传输 ----
  Future<Map<String, dynamic>> transferCreate() => _map('POST', '/api/transfer');
  Future<Map<String, dynamic>> transferJoin(String code, String device) => _map('POST', '/api/transfer/$code/join', data: {'device': device});
  Future<Map<String, dynamic>> transferStatus(String code, String? tok) =>
      _map('GET', '/api/transfer/$code', headers: {'X-Transfer-Token': ?tok});
  Future<Map<String, dynamic>> transferDeclare(String code, String? tok, Map<String, dynamic> body) =>
      _map('POST', '/api/transfer/$code/files', data: body, headers: {'X-Transfer-Token': ?tok});
  Future<Map<String, dynamic>> transferFile(String code, String? tok, int fid) =>
      _map('GET', '/api/transfer/$code/files/$fid', headers: {'X-Transfer-Token': ?tok});

  Future<Map<String, dynamic>> transferChunk(String code, String? tok, int fid, Uint8List chunk, int start, int total) async {
    Response r;
    try {
      r = await dio.put('/api/transfer/$code/files/$fid',
          data: Stream.fromIterable([chunk]),
          options: Options(headers: {
            'X-Transfer-Token': ?tok,
            'Content-Range': 'bytes $start-${start + chunk.length - 1}/$total',
            'Content-Type': 'application/octet-stream',
            Headers.contentLengthHeader: chunk.length,
          }));
    } on DioException catch (e) {
      throw ApiException(null, 'offline', '网络中断：${e.message}');
    }
    final m = Map<String, dynamic>.from((r.data ?? {}) as Map);
    if (r.statusCode == 409) return {...m, 'conflict': true};
    if ((r.statusCode ?? 500) >= 400) throw ApiException(r.statusCode, (m['error'] ?? 'error').toString(), (m['message'] ?? '上传失败').toString());
    return m;
  }

  String transferDownloadUrl(String code, String tok, int fid) => '$baseUrl/api/transfer/$code/files/$fid/content?t=$tok';
}
