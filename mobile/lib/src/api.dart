/// HTTP client for the NEXTCAM server's visitor API (`/api/v1/distribution/mobile`).
///
/// * Bearer access token; on 401 the refresh token is used once (single flight) and
///   the request repeated. A refused refresh means the visitor signs in again.
/// * [NetworkException]: no answer (offline, timeout) — the caller keeps the work queued.
/// * [ApiException]: the server answered with an error — shown to the visitor.
/// * Saved connection settings with a password: when the server refuses the refresh
///   (the 30-day session ended), the app signs in again by itself, once.
library;

import 'dart:async';
import 'dart:convert';
import 'dart:typed_data';

import 'package:http/http.dart' as http;

import 'format.dart';
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
/// [port], when given, replaces a port typed into the address.
String normalizeServer(String raw, {required bool allowHttp, int? port}) {
  var s = raw.trim();
  if (s.isEmpty) throw ApiException(0, 'server', 'نشانی سرور را وارد کنید');
  if (!s.startsWith('http://') && !s.startsWith('https://')) s = 'https://$s';
  var uri = Uri.tryParse(s);
  if (uri == null || uri.host.isEmpty) {
    throw ApiException(0, 'server', 'نشانی سرور نامعتبر است');
  }
  if (uri.scheme != 'https' && !allowHttp) {
    throw ApiException(0, 'server', 'اتصال باید با HTTPS باشد');
  }
  if (port != null) {
    if (port < 1 || port > 65535) {
      throw ApiException(0, 'port', 'پورت باید عددی بین ۱ تا ۶۵۵۳۵ باشد');
    }
    uri = uri.replace(port: port);
  }
  return '${uri.scheme}://${uri.authority}${uri.path.replaceFirst(RegExp(r'/+$'), '')}';
}

/// The typed port: empty = the default HTTPS port; Persian digits are accepted.
int? parsePort(String raw) {
  final t = enDigits(raw.trim());
  if (t.isEmpty) return null;
  final p = int.tryParse(t);
  if (p == null || p < 1 || p > 65535) {
    throw ApiException(0, 'port', 'پورت باید عددی بین ۱ تا ۶۵۵۳۵ باشد');
  }
  return p;
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

  /// Name this phone signs in with (also used for the silent sign-in again).
  String device = 'Android';

  /// Called when the server refused the session (sign-in screen).
  void Function()? onSignedOut;

  Future<Session?> restore() async => session = await store.load();

  Future<http.StreamedResponse> _raw(http.Request req) async {
    try {
      return await _http.send(req).timeout(timeout);
    } on TimeoutException {
      throw NetworkException('timeout');
    } on http.ClientException catch (e) {
      throw NetworkException(e.message);
    } catch (e) {
      // SocketException, HandshakeException … (dart:io is not imported here).
      throw NetworkException(e.toString());
    }
  }

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
    final resp = await _raw(req);
    final String text;
    try {
      text = await resp.stream.bytesToString();
    } catch (e) {
      throw NetworkException(e.toString());
    }
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
    this.device = device;
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
        if (!e.signedOut) rethrow;
        final again = await _signInAgain(current);
        if (again != null) return again;
        await _signedOut();
        rethrow;
      }
    }().whenComplete(() => _refreshing = null);
  }

  /// The session ended on the server: sign in with the saved password, if there is
  /// one for this visitor. A refused password is forgotten (it was changed).
  Future<Session?> _signInAgain(Session current) async {
    final c = await store.loadSettings();
    final pass = c?.password;
    if (c == null || pass == null || pass.isEmpty) return null;
    if (c.username != current.username) return null;
    try {
      return await login(current.server, c.username, pass, device);
    } on ApiException {
      await store.forgetPassword();
      return null;
    }
  }

  /// Is a NEXTCAM server answering at [server]? (No sign-in, nothing is sent.)
  Future<void> ping(String server) async {
    final r = await _send('GET', '$server/api/v1/system/health');
    final body = r.body;
    if (body is! Map || body['status'] != 'ok') {
      throw ApiException(0, 'not_nextcam', 'این نشانی، سرور NEXTCAM نیست');
    }
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

  /// Runs [send] with a fresh access token; refreshes once on an expired token.
  Future<T> _authorized<T>(Future<T> Function(Session s) send) async {
    var s = session;
    if (s == null) throw ApiException(401, 'signed_out', 'ابتدا وارد شوید');
    if (s.accessExpiresAt.isBefore(
      DateTime.now().toUtc().add(const Duration(seconds: 30)),
    )) {
      s = await _refresh();
    }
    try {
      return await send(s);
    } on ApiException catch (e) {
      if (!e.signedOut) rethrow;
      return send(await _refresh());
    }
  }

  /// An authenticated call to the visitor API; refreshes once on an expired token.
  Future<ApiResponse> call(
    String method,
    String path, {
    Object? body,
    Map<String, String>? headers,
  }) => _authorized(
    (s) => _send(
      method,
      '${s.server}/api/v1$path',
      body: body,
      headers: {'Authorization': 'Bearer ${s.access}', ...?headers},
    ),
  );

  /// A product photo (JPEG bytes); [large] for showing to the buyer.
  Future<Uint8List> image(String id, {bool large = false}) =>
      _authorized((s) async {
        final req = http.Request(
          'GET',
          Uri.parse(
            '${s.server}/api/v1/distribution/mobile/images/$id'
            '?size=${large ? 'large' : 'thumb'}',
          ),
        )..headers['Authorization'] = 'Bearer ${s.access}';
        final resp = await _raw(req);
        final Uint8List bytes;
        try {
          bytes = await resp.stream.toBytes();
        } catch (e) {
          throw NetworkException(e.toString());
        }
        if (resp.statusCode >= 400) {
          throw ApiException(
            resp.statusCode,
            resp.statusCode == 401 ? 'not_authenticated' : 'image',
            'عکس دریافت نشد (${resp.statusCode})',
          );
        }
        return bytes;
      });

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

  // --- visitor app v2 (ADR-0026) -------------------------------------------------

  /// Every final invoice of the customer, whoever sold it (view only).
  Future<Map<String, dynamic>> customerHistory(String customerId) async =>
      (await call(
            'GET',
            '/distribution/mobile/customers/$customerId/history',
          )).body
          as Map<String, dynamic>;

  Future<Map<String, dynamic>> customerAccount(String customerId) async =>
      (await call(
            'GET',
            '/distribution/mobile/customers/$customerId/account',
          )).body
          as Map<String, dynamic>;

  Future<void> setCustomerLocation(
    String customerId,
    String latitude,
    String longitude,
  ) => call(
    'PUT',
    '/distribution/mobile/customers/$customerId/location',
    body: {'latitude': latitude, 'longitude': longitude},
  );

  Future<Map<String, dynamic>> invoice(String id) async =>
      (await call('GET', '/distribution/mobile/invoices/$id')).body
          as Map<String, dynamic>;

  /// [period]: day / week / month; [date]: any day in it (yyyy-mm-dd), default today.
  Future<Map<String, dynamic>> report(String period, {String? date}) async =>
      (await call(
            'GET',
            '/distribution/mobile/report?period=$period'
                '${date == null ? '' : '&date=$date'}',
          )).body
          as Map<String, dynamic>;

  Future<Map<String, dynamic>> submitCollection(
    Map<String, dynamic> body,
  ) async =>
      (await call('POST', '/distribution/mobile/collections', body: body)).body
          as Map<String, dynamic>;

  Future<List<dynamic>> myCollections() async =>
      (await call('GET', '/distribution/mobile/collections')).body
          as List<dynamic>;

  Future<Map<String, dynamic>> submitCustomerRequest(
    Map<String, dynamic> body,
  ) async =>
      (await call(
            'POST',
            '/distribution/mobile/customer-requests',
            body: body,
          )).body
          as Map<String, dynamic>;

  Future<List<dynamic>> myCustomerRequests() async =>
      (await call('GET', '/distribution/mobile/customer-requests')).body
          as List<dynamic>;

  Future<List<dynamic>> notifications() async =>
      (await call('GET', '/distribution/mobile/notifications')).body
          as List<dynamic>;

  Future<void> markNotificationsRead() => call(
    'POST',
    '/distribution/mobile/notifications/read',
    body: {'all': true},
  );
}
