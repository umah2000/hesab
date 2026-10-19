/// HTTP client for the NEXTCAM server's visitor API (`/api/v1/distribution/mobile`).
///
/// * Bearer access token; on 401 the refresh token is used once (single flight) and
///   the request repeated. A refused refresh means the visitor signs in again.
/// * [NetworkException]: no answer (offline, timeout) — the caller keeps the work queued.
/// * [ApiException]: the server answered with an error — shown to the visitor.
library;

import 'dart:async';
import 'dart:convert';

import 'package:http/http.dart' as http;

import 'tokens.dart';

class ApiException implements Exception {
  ApiException(this.status, this.code, this.message);
  final int status;
  final String code;
  final String message;

  bool get signedOut => status == 401;

  @override
  String toString() => 'ApiException($status, $code)';
}

class NetworkException implements Exception {
  NetworkException(this.detail);
  final String detail;

  @override
  String toString() => 'NetworkException';
}

/// The server must be HTTPS outside development: a visitor works over mobile data.
String normalizeServer(String raw, {required bool allowHttp}) {
  var s = raw.trim();
  if (s.isEmpty) throw ApiException(0, 'server', 'نشانی سرور را وارد کنید');
  if (!s.startsWith('http://') && !s.startsWith('https://')) s = 'https://$s';
  final uri = Uri.tryParse(s);
  if (uri == null || uri.host.isEmpty) {
    throw ApiException(0, 'server', 'نشانی سرور نامعتبر است');
  }
  if (uri.scheme != 'https' && !allowHttp) {
    throw ApiException(0, 'server', 'اتصال باید با HTTPS باشد');
  }
  return '${uri.scheme}://${uri.authority}${uri.path.replaceFirst(RegExp(r'/+$'), '')}';
}

class ApiResponse {
  ApiResponse(this.status, this.body, this.etag);
  final int status;
  final dynamic body;
  final String? etag;
}

class ApiClient {
  ApiClient(
    this.store, {
    http.Client? client,
    this.timeout = const Duration(seconds: 20),
  }) : _http = client ?? http.Client();

  final TokenStore store;
  final http.Client _http;
  final Duration timeout;
  Session? session;
  Future<Session>? _refreshing;

  /// Called when the server refused the session (sign-in screen).
  void Function()? onSignedOut;

  Future<Session?> restore() async => session = await store.load();

  Future<ApiResponse> _send(
    String method,
    String url, {
    Object? body,
    Map<String, String>? headers,
  }) async {
    final req = http.Request(method, Uri.parse(url))
      ..headers.addAll({'Accept': 'application/json', ...?headers});
    if (body != null) {
      req.headers['Content-Type'] = 'application/json';
      req.body = jsonEncode(body);
    }
    http.StreamedResponse resp;
    try {
      resp = await _http.send(req).timeout(timeout);
    } on TimeoutException {
      throw NetworkException('timeout');
    } on http.ClientException catch (e) {
      throw NetworkException(e.message);
    } catch (e) {
      // SocketException, HandshakeException … (dart:io is not imported here).
      throw NetworkException(e.toString());
    }
    final text = await resp.stream.bytesToString();
    dynamic data;
    if (text.isNotEmpty) {
      try {
        data = jsonDecode(text);
      } catch (_) {
        data = null;
      }
    }
    if (resp.statusCode >= 400) {
      final err = data is Map ? data['error'] : null;
      throw ApiException(
        resp.statusCode,
        err is Map ? (err['code'] ?? 'error').toString() : 'error',
        err is Map
            ? (err['message'] ?? 'خطای سرور').toString()
            : 'خطای سرور (${resp.statusCode})',
      );
    }
    return ApiResponse(resp.statusCode, data, resp.headers['etag']);
  }

  Session _sessionFrom(String server, Map<String, dynamic> j) {
    final user = j['user'] as Map<String, dynamic>;
    return Session(
      server: server,
      userId: user['id'] as String,
      username: user['username'] as String,
      fullName: (user['full_name'] ?? '') as String,
      access: j['access_token'] as String,
      accessExpiresAt: DateTime.parse(j['access_expires_at'] as String),
      refresh: j['refresh_token'] as String,
      refreshExpiresAt: DateTime.parse(j['refresh_expires_at'] as String),
    );
  }

  Future<Session> login(
    String server,
    String username,
    String password,
    String device,
  ) async {
    final r = await _send(
      'POST',
      '$server/api/v1/auth/mobile/login',
      body: {'username': username, 'password': password, 'device_name': device},
    );
    final s = _sessionFrom(server, r.body as Map<String, dynamic>);
    await store.save(s);
    return session = s;
  }

  Future<Session> _refresh() {
    return _refreshing ??= () async {
      final current = session;
      if (current == null) {
        throw ApiException(401, 'signed_out', 'ابتدا وارد شوید');
      }
      try {
        final r = await _send(
          'POST',
          '${current.server}/api/v1/auth/mobile/refresh',
          body: {'refresh_token': current.refresh},
        );
        final s = _sessionFrom(current.server, r.body as Map<String, dynamic>);
        await store.save(s);
        return session = s;
      } on ApiException catch (e) {
        if (e.signedOut) await _signedOut();
        rethrow;
      }
    }().whenComplete(() => _refreshing = null);
  }

  Future<void> _signedOut() async {
    session = null;
    await store.clear();
    onSignedOut?.call();
  }

  Future<void> logout() async {
    final s = session;
    if (s != null) {
      try {
        await _send(
          'POST',
          '${s.server}/api/v1/auth/mobile/logout',
          headers: {'Authorization': 'Bearer ${s.access}'},
        );
      } catch (_) {
        // Signing out on the phone never waits for the server.
      }
    }
    session = null;
    await store.clear();
  }

  /// An authenticated call to the visitor API; refreshes once on an expired token.
  Future<ApiResponse> call(
    String method,
    String path, {
    Object? body,
    Map<String, String>? headers,
  }) async {
    var s = session;
    if (s == null) throw ApiException(401, 'signed_out', 'ابتدا وارد شوید');
    if (s.accessExpiresAt.isBefore(
      DateTime.now().toUtc().add(const Duration(seconds: 30)),
    )) {
      s = await _refresh();
    }
    try {
      return await _send(
        method,
        '${s.server}/api/v1$path',
        body: body,
        headers: {'Authorization': 'Bearer ${s.access}', ...?headers},
      );
    } on ApiException catch (e) {
      if (!e.signedOut) rethrow;
      s = await _refresh();
      return _send(
        method,
        '${s.server}/api/v1$path',
        body: body,
        headers: {'Authorization': 'Bearer ${s.access}', ...?headers},
      );
    }
  }

  Future<ApiResponse> bootstrap(String? etag) => call(
    'GET',
    '/distribution/mobile/bootstrap',
    headers: etag == null ? null : {'If-None-Match': etag},
  );

  Future<Map<String, dynamic>> quote(Map<String, dynamic> body) async =>
      (await call('POST', '/distribution/mobile/quote', body: body)).body
          as Map<String, dynamic>;

  Future<Map<String, dynamic>> submitOrder(Map<String, dynamic> body) async =>
      (await call('POST', '/distribution/mobile/orders', body: body)).body
          as Map<String, dynamic>;

  Future<Map<String, dynamic>> submitVisit(Map<String, dynamic> body) async =>
      (await call('POST', '/distribution/mobile/visits', body: body)).body
          as Map<String, dynamic>;

  Future<List<dynamic>> myOrders() async =>
      (await call('GET', '/distribution/mobile/orders')).body as List<dynamic>;

  Future<Map<String, dynamic>> cancelOrder(String id) async =>
      (await call('POST', '/distribution/mobile/orders/$id/cancel')).body
          as Map<String, dynamic>;
}
