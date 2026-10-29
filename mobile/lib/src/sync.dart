/// Sends what the visitor wrote on the phone, in order, and refreshes the catalogue.
///
/// * Each order, visit, collection and new-customer request carries its own id, so sending it again after a lost answer
///   returns the same record from the server, never a second one.
/// * No answer (offline) → stop and try again later; the entry stays `pending`.
/// * The server refused it (e.g. the customer is no longer assigned) → `failed`, with
///   the server's reason, for the visitor to see; the rest of the queue continues.
/// * Only the signed-in visitor's entries are sent.
library;

import 'dart:convert';

import 'api.dart';
import 'db.dart';

class SyncResult {
  SyncResult({required this.sent, required this.failed, required this.online});
  final int sent;
  final int failed;
  final bool online;
}

class SyncService {
  SyncService(this.api, this.db);
  final ApiClient api;
  final LocalDb db;

  Future<SyncResult> push() async {
    final user = api.session?.userId;
    if (user == null) return SyncResult(sent: 0, failed: 0, online: false);
    var sent = 0, failed = 0;
    for (final e in await db.outbox(userId: user, status: 'pending')) {
      try {
        await db.bumpAttempts(e.id);
        final result = switch (e.kind) {
          'order' => await api.submitOrder(e.payload),
          'collection' => await api.submitCollection(e.payload),
          'customer_request' => await api.submitCustomerRequest(e.payload),
          _ => await api.submitVisit(e.payload),
        };
        await db.markSent(e.id, result);
        sent++;
      } on NetworkException {
        return SyncResult(sent: sent, failed: failed, online: false);
      } on ApiException catch (e2) {
        if (e2.signedOut) rethrow; // sign in again; the queue waits
        if (e2.status >= 500) {
          return SyncResult(sent: sent, failed: failed, online: true);
        }
        await db.markFailed(e.id, e2.message);
        failed++;
      }
    }
    return SyncResult(sent: sent, failed: failed, online: true);
  }

  /// Fetch the catalogue and customers; returns true when they changed.
  Future<bool> pull() async {
    final etag = await db.get('bootstrap_etag');
    final r = await api.bootstrap(etag);
    if (r.status == 304) return false;
    await db.put('bootstrap', jsonEncode(r.body));
    if (r.etag != null) await db.put('bootstrap_etag', r.etag!);
    await db.put('bootstrap_at', DateTime.now().toUtc().toIso8601String());
    return true;
  }

  Future<void> pullOrders() async {
    final user = api.session?.userId;
    if (user == null) return;
    await db.saveOrders(user, await api.myOrders());
  }

  /// What the visitor reads offline later: collections, new-customer requests,
  /// notifications (ADR-0026). Kept per user in the phone's key-value table.
  Future<void> pullField() async {
    final user = api.session?.userId;
    if (user == null) return;
    try {
      await db.put('collections:$user', jsonEncode(await api.myCollections()));
      await db.put(
        'customer_requests:$user',
        jsonEncode(await api.myCustomerRequests()),
      );
      await db.put(
        'notifications:$user',
        jsonEncode(await api.notifications()),
      );
    } on ApiException catch (e) {
      // A server not updated yet has none of these: the rest of the app still works.
      if (e.status != 404) rethrow;
    }
  }

  /// Everything, in the safe order: send first, then read the server's view.
  Future<SyncResult> run() async {
    final pushed = await push();
    if (!pushed.online) return pushed;
    try {
      await pull();
      await pullOrders();
      await pullField();
      await db.put('synced_at', DateTime.now().toUtc().toIso8601String());
    } on NetworkException {
      return SyncResult(
        sent: pushed.sent,
        failed: pushed.failed,
        online: false,
      );
    }
    return pushed;
  }
}
