/// Sends what the visitor wrote on the phone, in order, and refreshes the catalogue.
///
/// * Each order, visit, collection and new-customer request carries its own id, so sending it again after a lost answer
///   returns the same record from the server, never a second one.
/// * No answer (offline) → stop and try again later; the entry stays `pending`.
/// * The server refused it (e.g. the customer is no longer assigned) → `failed`, with
///   the server's reason, for the visitor to see; the rest of the queue continues.
/// * Only the signed-in visitor's entries are sent.
/// * A server not yet updated to v2 (no `api_level` in bootstrap, or 404 on a v2 endpoint)
///   cannot take visits with position, collections or new customers: those stay
///   `pending` (held) instead of failing, and go out once the server is updated.
library;

import 'dart:convert';

import 'api.dart';
import 'db.dart';

class SyncResult {
  SyncResult({
    required this.sent,
    required this.failed,
    required this.online,
    this.held = 0,
  });
  final int sent;
  final int failed;
  final bool online;

  /// Kept in the queue for an updated server.
  final int held;
}

/// What a v1 server accepts; everything else waits for the update.
const _v1Kinds = {'order'};

class SyncService {
  SyncService(this.api, this.db);
  final ApiClient api;
  final LocalDb db;

  Future<SyncResult> push() async {
    final user = api.session?.userId;
    if (user == null) return SyncResult(sent: 0, failed: 0, online: false);
    var sent = 0, failed = 0, held = 0;
    var old = await serverIsOld();
    for (final e in await db.outbox(userId: user, status: 'pending')) {
      if (old && !_v1Kinds.contains(e.kind)) {
        held++;
        continue;
      }
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
        return SyncResult(
          sent: sent,
          failed: failed,
          online: false,
          held: held,
        );
      } on ApiException catch (e2) {
        if (e2.signedOut) rethrow; // sign in again; the queue waits
        if (e2.status >= 500) {
          return SyncResult(
            sent: sent,
            failed: failed,
            online: true,
            held: held,
          );
        }
        if (e2.status == 404 && !_v1Kinds.contains(e.kind)) {
          // The endpoint itself is missing: an old server, not a bad entry.
          await db.put(_levelKey, '1');
          old = true;
          held++;
          continue;
        }
        await db.markFailed(e.id, e2.message);
        failed++;
      }
    }
    return SyncResult(sent: sent, failed: failed, online: true, held: held);
  }

  static const _levelKey = 'server_api_level';

  /// True once this server is known not to have the v2 endpoints (ADR-0026).
  Future<bool> serverIsOld() async =>
      (int.tryParse(await db.get(_levelKey) ?? '') ?? 2) < 2;

  /// Fetch the catalogue and customers; returns true when they changed.
  Future<bool> pull() async {
    // An app updated over an older one has a catalogue but no level yet: fetch it whole.
    final etag = await db.get(_levelKey) == null
        ? null
        : await db.get('bootstrap_etag');
    final r = await api.bootstrap(etag);
    if (r.status == 304) return false;
    await db.put('bootstrap', jsonEncode(r.body));
    final level = (r.body as Map<String, dynamic>)['api_level'];
    await db.put(_levelKey, '${level is num ? level.toInt() : 1}');
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
    if (await db.get(_levelKey) == null && api.session != null) {
      // First contact: learn what the server takes before sending anything.
      try {
        await pull();
      } on NetworkException {
        return SyncResult(sent: 0, failed: 0, online: false);
      }
    }
    var pushed = await push();
    if (!pushed.online) return pushed;
    try {
      await pull();
      if (pushed.held > 0 && !await serverIsOld()) {
        // The server was updated meanwhile: what was held goes now.
        final again = await push();
        pushed = SyncResult(
          sent: pushed.sent + again.sent,
          failed: pushed.failed + again.failed,
          online: again.online,
          held: again.held,
        );
      }
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
