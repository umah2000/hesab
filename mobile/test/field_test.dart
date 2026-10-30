/// Visitor app v2 (ADR-0026): collections and new-customer requests go through the same
/// queue as orders, notifications arrive with a sync and become phone notifications once,
/// server answers are kept for offline reading, the position only with permission.
library;

import 'dart:convert';

import 'package:decimal/decimal.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:http/http.dart' as http;
import 'package:nextcam_visitor/src/api.dart';
import 'package:nextcam_visitor/src/db.dart';
import 'package:nextcam_visitor/src/device.dart';
import 'package:nextcam_visitor/src/models.dart';
import 'package:nextcam_visitor/src/state.dart';
import 'package:nextcam_visitor/src/tokens.dart';
import 'package:sqflite_common_ffi/sqflite_ffi.dart';

import 'sync_test.dart' show FakeServer, json, server;

Session session() => Session(
  server: server,
  userId: 'u1',
  username: 'visitor1',
  fullName: '',
  access: 'a',
  accessExpiresAt: DateTime.now().toUtc().add(const Duration(minutes: 10)),
  refresh: 'r',
  refreshExpiresAt: DateTime.now().toUtc().add(const Duration(days: 20)),
);

Map<String, dynamic> note(String id, String kind, String title) => {
  'id': id,
  'kind': kind,
  'title': title,
  'body': null,
  'ref_type': null,
  'ref_id': null,
  'created_at': DateTime.now().toUtc().toIso8601String(),
  'read_at': null,
};

final bootstrap = {
  'version': 'v1',
  'api_level': 2,
  'generated_at': DateTime.now().toUtc().toIso8601String(),
  'visitor': {'id': 'v1', 'code': 'V01', 'name': 'رضا', 'branch_name': 'مرکزی'},
  'settings': {
    'organization_name': 'فروشگاه',
    'display_currency': 'IRT',
    'prices_include_vat': false,
    'default_vat_rate': '10',
  },
  'customers': [
    {
      'customer_id': 'c1',
      'code': 'C1',
      'name': 'رستوران آفتاب',
      'phone': null,
      'address': null,
      'visit_weekday': 0,
      'credit_limit': null,
      'balance': '0',
      'available': null,
      'latitude': '36.290100',
      'longitude': '59.607000',
    },
  ],
  'items': [
    {
      'id': 'milk',
      'code': '1001',
      'name': 'شير پرچرب',
      'group_name': null,
      'base_unit_id': 'pcs',
      'units': [
        {
          'unit_id': 'pcs',
          'name': 'عدد',
          'factor': '1',
          'price': '110000',
          'allows_fraction': false,
        },
        {
          'unit_id': 'box',
          'name': 'کارتن',
          'factor': '12',
          'price': '1320000',
          'allows_fraction': false,
        },
      ],
      'stock': '10',
      'vat_exempt': false,
      'barcodes': [
        {'barcode': '6260000000017', 'unit_id': null},
        {'barcode': '6260000000024', 'unit_id': 'box'},
      ],
    },
  ],
};

void main() {
  sqfliteFfiInit();
  late LocalDb db;

  setUp(
    () async =>
        db = await LocalDb.open(databaseFactoryFfi, inMemoryDatabasePath),
  );
  tearDown(() => db.db.close());

  /// Lets the background sync started by an action finish (and its reload after it).
  Future<void> settle(AppState s) async {
    do {
      await Future<void>.delayed(const Duration(milliseconds: 30));
    } while (s.syncing);
    await Future<void>.delayed(const Duration(milliseconds: 30));
  }

  test(
    'collections and new customers are queued, sent once, and listed',
    () async {
      final posted = <String, List<Map<String, dynamic>>>{};
      var notes = <Map<String, dynamic>>[];
      final srv = FakeServer((req) {
        final p = req.url.path;
        if (req.method == 'POST' &&
            (p.endsWith('/collections') || p.endsWith('/customer-requests'))) {
          final body = jsonDecode(req.body) as Map<String, dynamic>;
          posted.putIfAbsent(p.split('/').last, () => []).add(body);
          return json({...body, 'status': 'pending'}, 201);
        }
        if (p.endsWith('/bootstrap')) return json(bootstrap);
        if (p.endsWith('/collections')) {
          return json([
            for (final b in posted['collections'] ?? [])
              {...b, 'status': 'pending'},
          ]);
        }
        if (p.endsWith('/customer-requests')) return json(<dynamic>[]);
        if (p.endsWith('/notifications')) return json(notes);
        return json(<dynamic>[]);
      });
      final store = MemoryTokenStore()..session = session();
      final device = FakeDevice();
      final api = ApiClient(store, client: srv.client);
      await api.restore();
      final s = AppState(api: api, db: db, device: device);
      await s.reload();

      // Offline first: both stay in the queue.
      srv.down = true;
      await s.addCollection({
        'customer_id': 'c1',
        'method': 'cash',
        'amount': '1000000',
      });
      await s.addCustomerRequest({'name': 'سوپر ستاره'});
      await settle(s);
      expect(s.pending, 2);
      expect(s.outbox.map((e) => e.kind).toSet(), {
        'collection',
        'customer_request',
      });
      // No permission: no position is sent.
      expect(
        s.outbox
            .firstWhere((e) => e.kind == 'collection')
            .payload
            .containsKey('latitude'),
        isFalse,
      );

      srv.down = false;
      notes = [note('n1', 'order_approved', 'سفارش ۳ تأیید شد')];
      await s.syncNow();
      expect(s.pending, 0);
      expect(posted['collections']!.single['amount'], '1000000');
      expect(posted['customer-requests']!.single['name'], 'سوپر ستاره');
      expect(s.collections.single['status'], 'pending');
      expect(s.unread, 1);
      // The first sync after sign-in does not replay what was already there.
      expect(device.shown, isEmpty);

      notes = [note('n2', 'collection_approved', 'وصول ثبت شد'), ...notes];
      await s.syncNow();
      expect(device.shown, ['وصول ثبت شد']);
      await s.syncNow();
      expect(device.shown, ['وصول ثبت شد']); // never twice

      await s.readAllNotifications();
      expect(s.unread, 0);
      expect(
        srv.calls.any((r) => r.url.path.endsWith('/notifications/read')),
        isTrue,
      );
      s.dispose();
    },
  );

  test('a server not yet updated: orders go, the rest waits and goes after the update', () async {
    final v1 = {...bootstrap}..remove('api_level');
    var level = <String, dynamic>{}; // v1: no api_level at all
    final posted = <String>[];
    final srv = FakeServer((req) {
      final p = req.url.path;
      if (p.endsWith('/bootstrap')) {
        return json({...v1, ...level});
      }
      if (req.method == 'POST') {
        final kind = p.split('/').last;
        // A v1 server has neither the endpoints nor the new visit fields.
        if (level.isEmpty && kind != 'orders') {
          return kind == 'visits'
              ? json({
                  'error': {'message': 'ورودی نامعتبر است'},
                }, 400)
              : json({
                  'error': {'message': 'مسیر یافت نشد'},
                }, 404);
        }
        posted.add(kind);
        final body = jsonDecode(req.body) as Map<String, dynamic>;
        return json({...body, 'status': 'pending', 'number': 1}, 201);
      }
      if (level.isEmpty && !p.endsWith('/orders')) {
        return json({
          'error': {'message': 'مسیر یافت نشد'},
        }, 404);
      }
      return json(<dynamic>[]);
    });
    // An app updated over an older one: catalogue and ETag kept, no level yet.
    await db.put('bootstrap', jsonEncode(v1));
    await db.put('bootstrap_etag', '"1"');
    final api = ApiClient(
      MemoryTokenStore()..session = session(),
      client: srv.client,
    );
    await api.restore();
    final s = AppState(api: api, db: db, device: FakeDevice());
    await s.reload();
    await s.setGps(true);
    final c = s.catalog!.customers.single;
    final item = s.catalog!.items.single;
    await s.placeOrder(c, [DraftLine(item, 'pcs', Decimal.one)]);
    await s.addCollection({
      'customer_id': 'c1',
      'method': 'cash',
      'amount': '5',
    });
    await settle(s);
    await s.syncNow();
    // The level was learnt (the ETag was not used for that), the order went, nothing failed.
    expect(
      srv.calls.any(
        (r) =>
            r.url.path.endsWith('/bootstrap') &&
            !r.headers.containsKey('If-None-Match'),
      ),
      isTrue,
    );
    expect(s.serverOld, isTrue);
    expect(posted, ['orders']);
    expect(s.failed, 0);
    expect(s.pending, 2); // the order's visit and the collection

    // The server is updated: the held entries go out by themselves.
    level = {'api_level': 2};
    await s.syncNow();
    expect(s.serverOld, isFalse);
    expect(posted, ['orders', 'visits', 'collections']);
    expect((s.pending, s.failed), (0, 0));
    s.dispose();
  });

  test(
    'the position goes with visits and collections only when allowed',
    () async {
      final srv = FakeServer((req) => throw http.ClientException('offline'));
      final api = ApiClient(
        MemoryTokenStore()..session = session(),
        client: srv.client,
      );
      await api.restore();
      final s = AppState(api: api, db: db, device: FakeDevice());
      await s.reload();
      await db.put('bootstrap', jsonEncode(bootstrap));
      await s.reload();
      final c = s.catalog!.customers.single;
      expect(c.located, isTrue);

      await s.setGps(true);
      await s.logVisit(c, 'stocked', null);
      await s.addCollection({
        'customer_id': 'c1',
        'method': 'cash',
        'amount': '5',
      });
      await settle(s);
      final visit = s.outbox.firstWhere((e) => e.kind == 'visit').payload;
      expect(
        (visit['outcome'], visit['latitude'], visit['accuracy_m']),
        ('stocked', '36.290100', 12),
      );
      expect(
        s.outbox.firstWhere((e) => e.kind == 'collection').payload['longitude'],
        '59.607000',
      );

      await s.setGps(false);
      await s.logVisit(c, 'closed', null);
      await settle(s);
      final last = s.outbox
          .where((e) => e.kind == 'visit')
          .map((e) => e.payload)
          .firstWhere((p) => p['outcome'] == 'closed');
      expect(last.containsKey('latitude'), isFalse);
      s.dispose();
    },
  );

  test('server answers are kept for reading offline', () async {
    var up = true;
    final srv = FakeServer((req) {
      if (!up) throw http.ClientException('offline');
      return json({'label': 'آبان 1405', 'current': {}});
    });
    final api = ApiClient(
      MemoryTokenStore()..session = session(),
      client: srv.client,
    );
    await api.restore();
    final s = AppState(api: api, db: db);
    final (first, fresh) = await s.report('month');
    expect((first!['label'], fresh), ('آبان 1405', true));
    up = false;
    final (again, fresh2) = await s.report('month');
    expect((again!['label'], fresh2), ('آبان 1405', false));
    final (never, _) = await s.report('day');
    expect(never, isNull);
  });

  test('a scanned barcode finds the item and its unit', () {
    final cat = Catalog.fromJson(bootstrap);
    expect(cat.byBarcode('6260000000017')!.$2, 'pcs');
    final (item, unit) = cat.byBarcode('6260000000024')!;
    expect(
      (item.id, unit, item.unit(unit).factor),
      ('milk', 'box', Decimal.fromInt(12)),
    );
    expect(cat.byBarcode('1001')!.$1.id, 'milk'); // the item code works too
    expect(cat.byBarcode('999'), isNull);
    // Arabic «ي» in the name still matches a Persian search.
    expect(cat.search('شیر').single.id, 'milk');
  });
}
