/// «تنظیمات اتصال»: address and port, the saved password and signing in again by
/// itself when the 30-day session ends.
library;

import 'dart:convert';

import 'package:flutter_test/flutter_test.dart';
import 'package:http/http.dart' as http;
import 'package:nextcam_visitor/src/api.dart';
import 'package:nextcam_visitor/src/db.dart';
import 'package:nextcam_visitor/src/state.dart';
import 'package:nextcam_visitor/src/tokens.dart';
import 'package:sqflite_common_ffi/sqflite_ffi.dart';

import 'sync_test.dart' show FakeServer, json, server, tokens;

Session expired() => Session(
  server: server,
  userId: 'u1',
  username: 'visitor1',
  fullName: '',
  access: 'a1',
  accessExpiresAt: DateTime.now().toUtc().subtract(const Duration(minutes: 1)),
  refresh: 'r1',
  refreshExpiresAt: DateTime.now().toUtc().subtract(const Duration(days: 1)),
);

http.Response refused() => json({
  'error': {'code': 'not_authenticated', 'message': 'نشست نامعتبر'},
}, 401);

void main() {
  sqfliteFfiInit();

  test('address and port', () {
    expect(
      normalizeServer('erp.shop.ir', allowHttp: false, port: 8443),
      'https://erp.shop.ir:8443',
    );
    expect(
      normalizeServer(
        'https://erp.shop.ir:9000/',
        allowHttp: false,
        port: 8443,
      ),
      'https://erp.shop.ir:8443',
    );
    expect(
      normalizeServer('erp.shop.ir', allowHttp: false),
      'https://erp.shop.ir',
    );
    expect(parsePort(''), isNull);
    expect(parsePort('۸۴۴۳'), 8443);
    expect(() => parsePort('70000'), throwsA(isA<ApiException>()));
    expect(() => parsePort('abc'), throwsA(isA<ApiException>()));
    const c = ConnectionSettings(
      host: 'erp.shop.ir',
      port: 8443,
      username: 'v',
    );
    expect(c.label, 'erp.shop.ir : 8443');
    expect(c.canSignIn, isFalse);
  });

  test('the password is kept only when the visitor asked for it', () async {
    final store = MemoryTokenStore();
    await store.saveSettings(
      const ConnectionSettings(
        host: 'erp.shop.ir',
        username: 'v',
        password: 'p',
        remember: false,
      ),
    );
    expect(store.settings!.password, isNull);
    expect(store.settings!.host, 'erp.shop.ir');
  });

  test('a refused refresh signs in again with the saved password', () async {
    final logins = <Map<String, dynamic>>[];
    final srv = FakeServer((req) {
      if (req.url.path.endsWith('/auth/mobile/refresh')) return refused();
      if (req.url.path.endsWith('/auth/mobile/login')) {
        logins.add(jsonDecode(req.body) as Map<String, dynamic>);
        return json(tokens('a2', 'r2'));
      }
      expect(req.headers['Authorization'], 'Bearer a2');
      return json(<dynamic>[]);
    });
    final store = MemoryTokenStore()
      ..session = expired()
      ..settings = const ConnectionSettings(
        host: 'erp.test',
        username: 'visitor1',
        password: 'Secret-123',
      );
    final api = ApiClient(store, client: srv.client)..device = 'Galaxy A54';
    var signedOut = false;
    api.onSignedOut = () => signedOut = true;
    await api.restore();
    await api.myOrders();
    expect(logins.single, {
      'username': 'visitor1',
      'password': 'Secret-123',
      'device_name': 'Galaxy A54',
    });
    expect(store.session!.access, 'a2');
    expect(signedOut, isFalse);
  });

  test(
    'a changed password is forgotten and the visitor signs in by hand',
    () async {
      final srv = FakeServer((req) {
        if (req.url.path.endsWith('/auth/mobile/login')) {
          return json({
            'error': {
              'code': 'invalid_credentials',
              'message': 'نام کاربری یا رمز نادرست است',
            },
          }, 401);
        }
        return refused();
      });
      final store = MemoryTokenStore()
        ..session = expired()
        ..settings = const ConnectionSettings(
          host: 'erp.test',
          username: 'visitor1',
          password: 'old',
        );
      final api = ApiClient(store, client: srv.client);
      var signedOut = false;
      api.onSignedOut = () => signedOut = true;
      await api.restore();
      await expectLater(api.myOrders(), throwsA(isA<ApiException>()));
      expect(signedOut, isTrue);
      expect(store.session, isNull);
      expect(store.settings!.password, isNull);
      expect(store.settings!.username, 'visitor1');
    },
  );

  test('another visitor\'s saved password is never used', () async {
    var logins = 0;
    final srv = FakeServer((req) {
      if (req.url.path.endsWith('/auth/mobile/login')) logins++;
      return refused();
    });
    final store = MemoryTokenStore()
      ..session = expired()
      ..settings = const ConnectionSettings(
        host: 'erp.test',
        username: 'someone_else',
        password: 'p',
      );
    final api = ApiClient(store, client: srv.client);
    await api.restore();
    await expectLater(api.myOrders(), throwsA(isA<ApiException>()));
    expect(logins, 0);
  });

  test('sign in saves the settings, the next start connects by itself, '
      'sign out forgets the password', () async {
    final db = await LocalDb.open(databaseFactoryFfi, inMemoryDatabasePath);
    addTearDown(db.db.close);
    final srv = FakeServer((req) {
      if (req.url.path.endsWith('/system/health')) {
        return json({'status': 'ok'});
      }
      if (req.url.path.endsWith('/auth/mobile/login')) {
        expect(
          req.url.toString(),
          'https://erp.test:8443/api/v1/auth/mobile/login',
        );
        return json(tokens('a1', 'r1'));
      }
      if (req.url.path.endsWith('/auth/mobile/logout')) return json({});
      throw http.ClientException('offline');
    });
    final store = MemoryTokenStore();
    final state = AppState(
      api: ApiClient(store, client: srv.client),
      db: db,
    );
    const c = ConnectionSettings(
      host: 'erp.test',
      port: 8443,
      username: 'visitor1',
      password: 'Secret-123',
    );
    await state.testConnection(c);
    await state.login(c);
    expect(state.signedIn, isTrue);
    expect(store.settings!.password, 'Secret-123');

    // A new start of the app with the session gone: it signs in by itself.
    store.session = null;
    final again = AppState(
      api: ApiClient(store, client: srv.client),
      db: db,
    );
    await again.start();
    expect(again.signedIn, isTrue);
    while (again.syncing) {
      await Future<void>.delayed(const Duration(milliseconds: 10));
    }

    await again.logout();
    expect(again.signedIn, isFalse);
    expect(store.settings!.password, isNull);
    expect(store.settings!.label, 'erp.test : 8443');
    again.dispose();
    state.dispose();
  });

  test('«آزمایش اتصال» tells a wrong address from NEXTCAM', () async {
    final srv = FakeServer((req) => json({'hello': 'world'}));
    final api = ApiClient(MemoryTokenStore(), client: srv.client);
    await expectLater(
      api.ping('https://example.org'),
      throwsA(isA<ApiException>().having((e) => e.code, 'code', 'not_nextcam')),
    );
  });
}
