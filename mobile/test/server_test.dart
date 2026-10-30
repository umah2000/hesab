/// The app's data layer against a real NEXTCAM server, with a real outage in the middle.
///
///   NEXTCAM_TEST_SERVER=http://127.0.0.1:5000 NEXTCAM_TEST_USER=… NEXTCAM_TEST_PASSWORD=…
///   flutter test --tags server
///
/// Skipped without those variables (no credentials are kept in the repository).
@Tags(['server'])
library;

import 'dart:convert';
import 'dart:io';

import 'package:decimal/decimal.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:http/http.dart' as http;
import 'package:nextcam_visitor/src/api.dart';
import 'package:nextcam_visitor/src/db.dart';
import 'package:nextcam_visitor/src/device.dart';
import 'package:nextcam_visitor/src/models.dart';
import 'package:nextcam_visitor/src/state.dart';
import 'package:nextcam_visitor/src/sync.dart';
import 'package:nextcam_visitor/src/tokens.dart';
import 'package:sqflite_common_ffi/sqflite_ffi.dart';
import 'package:uuid/uuid.dart';

final env = Platform.environment;
final server = env['NEXTCAM_TEST_SERVER'];

Session withServer(Session s, String server) => Session(
  server: server,
  userId: s.userId,
  username: s.username,
  fullName: s.fullName,
  access: s.access,
  accessExpiresAt: s.accessExpiresAt,
  refresh: s.refresh,
  refreshExpiresAt: s.refreshExpiresAt,
);

void main() {
  sqfliteFfiInit();

  test(
    'sign in, work offline through an outage, send once, rotate tokens',
    () async {
      final store = MemoryTokenStore();
      final api = ApiClient(store, client: http.Client());
      final db = await LocalDb.open(databaseFactoryFfi, inMemoryDatabasePath);
      final sync = SyncService(api, db);

      final s = await api.login(
        server!,
        env['NEXTCAM_TEST_USER']!,
        env['NEXTCAM_TEST_PASSWORD']!,
        'test-vm',
      );
      expect(s.access, startsWith('ncm_a_'));
      final first = await sync.run();
      expect(first.online, isTrue);
      final cat = Catalog.fromJson(
        jsonDecode((await db.get('bootstrap'))!) as Map<String, dynamic>,
      );
      expect(cat.customers, isNotEmpty);
      final item = cat.items.firstWhere((i) => i.units.first.price != null);
      expect(
        await sync.pull(),
        isFalse,
        reason: 'unchanged catalogue answers 304',
      );

      // The server goes away (nothing listens on port 9): the order waits on the phone.
      final real = api.session!;
      api.session = withServer(real, 'http://127.0.0.1:9');
      final id = const Uuid().v4();
      final order = {
        'id': id,
        'customer_id': cat.customers.first.id,
        'lines': [
          {'item_id': item.id, 'qty': '3.000'},
        ],
        'ordered_at': DateTime.now().toUtc().toIso8601String(),
        'note': 'آزمون قطع ارتباط',
      };
      await db.addOutbox(id, real.userId, 'order', order);
      final visit = const Uuid().v4();
      await db.addOutbox(visit, real.userId, 'visit', {
        'id': visit,
        'customer_id': cat.customers.first.id,
        'visited_at': DateTime.now().toUtc().toIso8601String(),
        'outcome': 'order',
        'order_id': id,
      });
      final offline = await sync.push();
      expect(offline.online, isFalse);
      expect((await db.outbox(status: 'pending')).length, 2);

      // Back online: sent in order, priced by the server.
      api.session = real;
      final back = await sync.run();
      expect((back.sent, back.failed, back.online), (2, 0, true));
      final sent = (await db.outbox(status: 'sent'))
          .firstWhere((e) => e.id == id);
      final number = sent.result!['number'] as int;
      expect(sent.result!['status'], 'submitted');
      expect(sent.result!['grand_total'], isNotNull);

      // The answer was lost and the phone sends again: the same order, not a second one.
      final again = await api.submitOrder(order);
      expect((again['id'], again['number']), (id, number));
      final mine = await db.orders(real.userId);
      expect(mine.where((o) => o['id'] == id).single['status'], 'submitted');

      // An expired access token is renewed; the old refresh token is then worthless.
      final oldRefresh = api.session!.refresh;
      api.session = Session(
        server: real.server,
        userId: real.userId,
        username: real.username,
        fullName: real.fullName,
        access: real.access,
        accessExpiresAt: DateTime.now().toUtc().subtract(
          const Duration(minutes: 1),
        ),
        refresh: api.session!.refresh,
        refreshExpiresAt: real.refreshExpiresAt,
      );
      expect(await api.myOrders(), isNotEmpty);
      expect(api.session!.refresh, isNot(oldRefresh));
      final reuse = await http.post(
        Uri.parse('$server/api/v1/auth/mobile/refresh'),
        headers: {'Content-Type': 'application/json'},
        body: jsonEncode({'refresh_token': oldRefresh}),
      );
      expect(reuse.statusCode, 401);
      // …and the reuse closed the whole session, as a stolen token should.
      await expectLater(api.myOrders(), throwsA(isA<ApiException>()));
      expect(store.session, isNull);
      await db.db.close();
    },
    skip: server == null ? 'NEXTCAM_TEST_SERVER not set' : false,
  );

  // ADR-0026: everything the v2 screens queue is accepted by the real server, with the
  // position a real phone gives (fractional accuracy) and the new visit outcomes.
  test(
    'v2: visits with position, collections, new customers and reads',
    () async {
      final db = await LocalDb.open(databaseFactoryFfi, inMemoryDatabasePath);
      final api = ApiClient(MemoryTokenStore(), client: http.Client());
      await api.login(
        server!,
        env['NEXTCAM_TEST_USER']!,
        env['NEXTCAM_TEST_PASSWORD']!,
        'test-vm',
      );
      final device = FakeDevice()
        ..here = const GeoPoint(36.29013, 59.60702, 8.4);
      final s = AppState(api: api, db: db, device: device);
      await s.syncNow();
      await s.setGps(true);
      final c = s.catalog!.customers.first;
      final item = s.catalog!.items.firstWhere(
        (i) => i.units.first.price != null,
      );

      await s.placeOrder(c, [
        DraftLine(item, item.units.first.unitId, Decimal.fromInt(2)),
      ]);
      await s.logVisit(c, 'stocked', 'آزمون');
      await s.addCollection({
        'customer_id': c.id,
        'method': 'cash',
        'amount': '250000',
      });
      await s.addCustomerRequest({
        'name': 'فروشگاه آزمون ${DateTime.now().millisecondsSinceEpoch}',
        'mobile': '09123456789',
        'visit_weekday': 2,
      }, at: device.here);
      await s.setCustomerLocation(c, device.here!);
      while (s.syncing) {
        await Future<void>.delayed(const Duration(milliseconds: 50));
      }
      await s.syncNow();

      final failed = s.outbox.where((e) => e.status == 'failed').toList();
      expect(failed.map((e) => '${e.kind}: ${e.error}'), isEmpty);
      expect(s.pending, 0);
      expect(s.collections, isNotEmpty);
      expect(s.customerRequests, isNotEmpty);

      final (history, _) = await s.customerHistory(c.id);
      expect(history, isNotNull);
      final (account, _) = await s.customerAccount(c.id);
      expect(account, isNotNull);
      for (final period in ['day', 'week', 'month']) {
        final (r, fresh) = await s.report(period);
        expect((r!['current']['ordered_count'] as num) >= 1, isTrue);
        expect(fresh, isTrue);
      }
      s.dispose();
      await db.db.close();
    },
    skip: server == null ? 'NEXTCAM_TEST_SERVER not set' : false,
  );
}
