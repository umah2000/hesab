import 'dart:convert';

import 'package:flutter_test/flutter_test.dart';
import 'package:http/http.dart' as http;
import 'package:http/testing.dart';
import 'package:nextcam_visitor/src/api.dart';
import 'package:nextcam_visitor/src/db.dart';
import 'package:nextcam_visitor/src/sync.dart';
import 'package:nextcam_visitor/src/tokens.dart';
import 'package:sqflite_common_ffi/sqflite_ffi.dart';

const server = 'https://erp.test';

Map<String, dynamic> tokens(String access, String refresh) => {
  'access_token': access,
  'access_expires_at': DateTime.now()
      .toUtc()
      .add(const Duration(minutes: 15))
      .toIso8601String(),
  'refresh_token': refresh,
  'refresh_expires_at': DateTime.now()
      .toUtc()
      .add(const Duration(days: 30))
      .toIso8601String(),
  'user': {'id': 'u1', 'username': 'visitor1', 'full_name': 'ویزیتور یک'},
};

http.Response json(Object body, [int status = 200]) => http.Response(
  jsonEncode(body),
  status,
  headers: {'content-type': 'application/json; charset=utf-8'},
);

/// A scripted server: records what arrives, answers from [handler].
class FakeServer {
  FakeServer(this.handler);
  final http.Response Function(http.Request) handler;
  final calls = <http.Request>[];
  bool down = false;

  MockClient get client => MockClient((req) async {
    calls.add(req);
    if (down) throw http.ClientException('Connection refused');
    return handler(req);
  });
}

void main() {
  sqfliteFfiInit();
  late LocalDb db;

  setUp(
    () async =>
        db = await LocalDb.open(databaseFactoryFfi, inMemoryDatabasePath),
  );
  tearDown(() => db.db.close());

  test(
    'an expired access token is refreshed once, even for parallel calls',
    () async {
      var refreshes = 0;
      final srv = FakeServer((req) {
        if (req.url.path.endsWith('/auth/mobile/refresh')) {
          refreshes++;
          expect(jsonDecode(req.body)['refresh_token'], 'r1');
          return json(tokens('a2', 'r2'));
        }
        if (req.headers['Authorization'] == 'Bearer a1') {
          return json({
            'error': {'code': 'not_authenticated', 'message': 'expired'},
          }, 401);
        }
        return json(<dynamic>[]);
      });
      final store = MemoryTokenStore();
      final api = ApiClient(store, client: srv.client);
      await store.save(
        Session(
          server: server,
          userId: 'u1',
          username: 'visitor1',
          fullName: '',
          access: 'a1',
          accessExpiresAt: DateTime.now().toUtc().add(
            const Duration(minutes: 10),
          ),
          refresh: 'r1',
          refreshExpiresAt: DateTime.now().toUtc().add(const Duration(days: 1)),
        ),
      );
      await api.restore();
      await Future.wait([api.myOrders(), api.myOrders(), api.myOrders()]);
      expect(refreshes, 1);
      expect(store.session!.refresh, 'r2');
    },
  );

  test('a refused refresh signs out but keeps the queue', () async {
    final srv = FakeServer(
      (req) => json({
        'error': {'code': 'not_authenticated', 'message': 'نشست نامعتبر'},
      }, 401),
    );
    final store = MemoryTokenStore();
    final api = ApiClient(store, client: srv.client);
    var signedOut = false;
    api.onSignedOut = () => signedOut = true;
    api.session = Session.fromMap(
      tokens('a1', 'r1').map((k, v) => MapEntry(k, v.toString()))..addAll({
        'server': server,
        'user_id': 'u1',
        'username': 'v',
        'access': 'a1',
        'refresh': 'r1',
      }),
    );
    await db.addOutbox('o1', 'u1', 'order', {'id': 'o1'});
    final sync = SyncService(api, db);
    await expectLater(sync.push(), throwsA(isA<ApiException>()));
    expect(signedOut, isTrue);
    expect((await db.outbox(status: 'pending')).single.id, 'o1');
  });

  test(
    'queue: in order, offline keeps pending, a refusal does not block the rest',
    () async {
      final received = <String>[];
      final srv = FakeServer((req) {
        final body = jsonDecode(req.body) as Map<String, dynamic>;
        received.add(body['id'] as String);
        if (body['id'] == 'o2') {
          return json({
            'error': {
              'code': 'not_assigned',
              'message': 'این مشتری به شما تخصیص داده نشده است',
            },
          }, 403);
        }
        return json({
          ...body,
          'number': received.length,
          'status': 'submitted',
        }, 201);
      });
      final api = ApiClient(MemoryTokenStore(), client: srv.client);
      api.session = Session(
        server: server,
        userId: 'u1',
        username: 'visitor1',
        fullName: '',
        access: 'a',
        accessExpiresAt: DateTime.now().toUtc().add(
          const Duration(minutes: 10),
        ),
        refresh: 'r',
        refreshExpiresAt: DateTime.now().toUtc().add(const Duration(days: 1)),
      );
      final sync = SyncService(api, db);
      for (final id in ['o1', 'o2', 'o3']) {
        await db.addOutbox(id, 'u1', 'order', {'id': id});
      }
      await db.addOutbox('other', 'u2', 'order', {
        'id': 'other',
      }); // another visitor's

      srv.down = true;
      final offline = await sync.push();
      expect(offline.online, isFalse);
      expect((await db.outbox(status: 'pending')).length, 4);

      srv.down = false;
      final r = await sync.push();
      expect((r.sent, r.failed, r.online), (2, 1, true));
      expect(received, ['o1', 'o2', 'o3']);
      final failed = (await db.outbox(status: 'failed')).single;
      expect(
        (failed.id, failed.error),
        ('o2', 'این مشتری به شما تخصیص داده نشده است'),
      );
      expect((await db.outbox(status: 'pending')).single.id, 'other');

      // Sending the same id again is what makes a lost answer safe: the server dedupes.
      await db.retry('o2');
      expect(
        (await db.outbox(userId: 'u1', status: 'pending')).single.id,
        'o2',
      );
    },
  );

  test('catalogue pull uses the ETag', () async {
    var served = 0;
    final srv = FakeServer((req) {
      if (req.headers['If-None-Match'] == '"v1"') return http.Response('', 304);
      served++;
      return http.Response(
        jsonEncode({'version': 'v1'}),
        200,
        headers: {'etag': '"v1"', 'content-type': 'application/json'},
      );
    });
    final api = ApiClient(MemoryTokenStore(), client: srv.client);
    api.session = Session(
      server: server,
      userId: 'u1',
      username: 'v',
      fullName: '',
      access: 'a',
      accessExpiresAt: DateTime.now().toUtc().add(const Duration(minutes: 10)),
      refresh: 'r',
      refreshExpiresAt: DateTime.now().toUtc().add(const Duration(days: 1)),
    );
    final sync = SyncService(api, db);
    expect(await sync.pull(), isTrue);
    expect(await sync.pull(), isFalse);
    expect(served, 1);
  });
}
