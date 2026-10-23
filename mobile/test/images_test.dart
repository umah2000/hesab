import 'dart:convert';
import 'dart:typed_data';

import 'package:flutter_test/flutter_test.dart';
import 'package:http/http.dart' as http;
import 'package:nextcam_visitor/src/api.dart';
import 'package:nextcam_visitor/src/db.dart';
import 'package:nextcam_visitor/src/images.dart';
import 'package:nextcam_visitor/src/models.dart';
import 'package:nextcam_visitor/src/tokens.dart';
import 'package:sqflite_common_ffi/sqflite_ffi.dart';

import 'sync_test.dart' show FakeServer, json, server, tokens;

Item item(String id, List<String> images) => Item.fromJson({
  'id': id,
  'code': id,
  'name': id,
  'group_name': null,
  'base_unit_id': 'pcs',
  'units': [
    {
      'unit_id': 'pcs',
      'name': 'عدد',
      'factor': '1',
      'price': '1000',
      'allows_fraction': false,
    },
  ],
  'stock': null,
  'vat_exempt': false,
  'image_ids': images,
});

void main() {
  sqfliteFfiInit();
  late LocalDb db;

  setUp(
    () async =>
        db = await LocalDb.open(databaseFactoryFfi, inMemoryDatabasePath),
  );
  tearDown(() => db.db.close());

  Future<ApiClient> client(FakeServer srv, {String access = 'a1'}) async {
    final store = MemoryTokenStore();
    await store.save(
      Session(
        server: server,
        userId: 'u1',
        username: 'visitor1',
        fullName: '',
        access: access,
        accessExpiresAt: DateTime.now().toUtc().add(
          const Duration(minutes: 10),
        ),
        refresh: 'r1',
        refreshExpiresAt: DateTime.now().toUtc().add(const Duration(days: 9)),
      ),
    );
    final api = ApiClient(store, client: srv.client);
    await api.restore();
    return api;
  }

  http.Response jpeg(String id, String size) => http.Response.bytes(
    utf8.encode('jpeg:$id:$size'),
    200,
    headers: {'content-type': 'image/jpeg'},
  );

  test(
    'a photo is fetched once, then shown from the phone, even offline',
    () async {
      final srv = FakeServer((req) {
        expect(req.headers['Authorization'], 'Bearer a1');
        final id = req.url.pathSegments.last;
        return jpeg(id, req.url.queryParameters['size']!);
      });
      final store = ImageStore(await client(srv), db);
      final first = await store.get('p1', large: true);
      expect(utf8.decode(first!), 'jpeg:p1:large');
      expect(
        srv.calls.single.url.path,
        '/api/v1/distribution/mobile/images/p1',
      );
      // A new store (the app restarted) offline: still there.
      srv.down = true;
      final again = await ImageStore(
        await client(srv),
        db,
      ).get('p1', large: true);
      expect(utf8.decode(again!), 'jpeg:p1:large');
      expect(srv.calls, hasLength(1));
      // Not on the phone and no connection: no photo, no error.
      expect(await store.get('p2'), isNull);
    },
  );

  test('an expired token is refreshed for a photo too', () async {
    final srv = FakeServer((req) {
      if (req.url.path.endsWith('/auth/mobile/refresh')) {
        return json(tokens('a2', 'r2'));
      }
      if (req.headers['Authorization'] == 'Bearer a1') {
        return json({
          'error': {'code': 'not_authenticated', 'message': 'expired'},
        }, 401);
      }
      return jpeg('p1', 'thumb');
    });
    final api = await client(srv);
    final bytes = await api.image('p1');
    expect(utf8.decode(bytes), 'jpeg:p1:thumb');
  });

  test(
    'sync fetches only missing thumbnails and forgets removed photos',
    () async {
      final srv = FakeServer((req) => jpeg(req.url.pathSegments.last, 'thumb'));
      final store = ImageStore(await client(srv), db);
      await db.putImage('p1', 'thumb', Uint8List.fromList([1]));
      await db.putImage('old', 'thumb', Uint8List.fromList([2]));
      final items = [
        item('a', ['p1', 'p2']),
        item('b', ['p3']),
        item('c', []),
      ];
      final progress = <int>[];
      expect(
        await store.prefetch(items, progress: (d, _) => progress.add(d)),
        3,
      );
      expect(srv.calls.map((r) => r.url.pathSegments.last), ['p2', 'p3']);
      expect(progress, [1, 2]);
      await store.keepOnly(items);
      expect(await db.imageIds('thumb'), {'p1', 'p2', 'p3'});

      // Large: only the main photo of each item; a dropped connection stops quietly.
      srv.calls.clear();
      var served = 0;
      final flaky = FakeServer((req) {
        if (served++ == 1) throw http.ClientException('lost');
        return jpeg(req.url.pathSegments.last, 'large');
      });
      final store2 = ImageStore(await client(flaky), db);
      expect(await store2.prefetch(items, large: true), 1);
      expect(await db.imageIds('large'), {'p1'});
    },
  );
}
