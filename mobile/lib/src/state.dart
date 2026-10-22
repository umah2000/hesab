/// App state: session, offline catalogue, queue and orders (one ChangeNotifier).
library;

import 'dart:async';
import 'dart:convert';

import 'package:decimal/decimal.dart';
import 'package:flutter/foundation.dart';
import 'package:uuid/uuid.dart';

import 'api.dart';
import 'db.dart';
import 'images.dart';
import 'models.dart';
import 'sync.dart';
import 'tokens.dart';

class AppState extends ChangeNotifier {
  AppState({required this.api, required this.db, this.deviceName = 'Android'})
    : sync = SyncService(api, db),
      images = ImageStore(api, db) {
    api.onSignedOut = () {
      signedOut = true;
      notifyListeners();
    };
  }

  final ApiClient api;
  final LocalDb db;
  final SyncService sync;
  final ImageStore images;
  final String deviceName;
  static const _uuid = Uuid();

  Catalog? catalog;
  List<Map<String, dynamic>> orders = [];
  List<OutboxEntry> outbox = [];
  bool online = false;
  bool syncing = false;
  bool signedOut = false;
  DateTime? syncedAt;
  String? syncError;
  Timer? _timer;

  Session? get session => api.session;
  bool get signedIn => api.session != null;
  int get pending => outbox.where((e) => e.status == 'pending').length;
  int get failed => outbox.where((e) => e.status == 'failed').length;

  Future<void> start() async {
    await api.restore();
    await reload();
    if (signedIn) unawaited(syncNow());
    _timer ??= Timer.periodic(const Duration(minutes: 1), (_) {
      if (signedIn) syncNow();
    });
  }

  @override
  void dispose() {
    _timer?.cancel();
    super.dispose();
  }

  Future<void> reload() async {
    final raw = await db.get('bootstrap');
    catalog = raw == null
        ? null
        : Catalog.fromJson(jsonDecode(raw) as Map<String, dynamic>);
    final user = api.session?.userId;
    outbox = user == null ? [] : await db.outbox(userId: user);
    orders = user == null ? [] : await db.orders(user);
    final at = await db.get('synced_at');
    syncedAt = at == null ? null : DateTime.parse(at);
    notifyListeners();
  }

  Future<void> login(String server, String username, String password) async {
    await api.login(server, username, password, deviceName);
    signedOut = false;
    await reload();
    await syncNow();
  }

  /// Signing out keeps the queue: it is sent when the same visitor signs in again.
  Future<void> logout() async {
    await api.logout();
    await reload();
  }

  Future<void> syncNow() async {
    if (syncing || !signedIn) return;
    syncing = true;
    syncError = null;
    notifyListeners();
    try {
      final r = await sync.run();
      online = r.online;
      if (r.online) unawaited(_refreshImages());
    } on ApiException catch (e) {
      online = true;
      syncError = e.message;
    } on NetworkException {
      online = false;
    } finally {
      syncing = false;
      await reload();
    }
  }

  /// After a sync: forget removed photos, fetch thumbnails the phone does not have.
  Future<void> _refreshImages() async {
    final items = catalog?.items;
    if (items == null) return;
    try {
      await images.keepOnly(items);
      if (await images.prefetch(items) > 0) notifyListeners();
    } on ApiException {
      // Photos are optional; the next sync tries again.
    }
  }

  /// Large main photos of the whole catalogue, for showing them without a connection.
  Future<int> downloadPhotos(
    void Function(int done, int total) progress,
  ) async {
    final items = catalog?.items ?? const <Item>[];
    await images.prefetch(items, progress: progress);
    return images.prefetch(items, large: true, progress: progress);
  }

  /// Queue an order (and its visit); it is sent now if there is a connection.
  /// [serverTotal] is the server quote the visitor saw, if any.
  Future<String> placeOrder(
    Customer customer,
    List<DraftLine> lines, {
    String? note,
    Decimal? serverTotal,
  }) async {
    final user = api.session!.userId;
    final id = _uuid.v4();
    final now = DateTime.now().toUtc().toIso8601String();
    await db.addOutbox(id, user, 'order', {
      'id': id,
      'customer_id': customer.id,
      'lines': lines.map((l) => l.toJson()).toList(),
      'ordered_at': now,
      if (note != null && note.trim().isNotEmpty) 'note': note.trim(),
      if (serverTotal != null) 'client_total': serverTotal.toString(),
    });
    final visit = _uuid.v4();
    await db.addOutbox(visit, user, 'visit', {
      'id': visit,
      'customer_id': customer.id,
      'visited_at': now,
      'outcome': 'order',
      'order_id': id,
    });
    await reload();
    unawaited(syncNow());
    return id;
  }

  Future<void> logVisit(Customer customer, String outcome, String? note) async {
    final user = api.session!.userId;
    final id = _uuid.v4();
    await db.addOutbox(id, user, 'visit', {
      'id': id,
      'customer_id': customer.id,
      'visited_at': DateTime.now().toUtc().toIso8601String(),
      'outcome': outcome,
      if (note != null && note.trim().isNotEmpty) 'note': note.trim(),
    });
    await reload();
    unawaited(syncNow());
  }

  Future<Map<String, dynamic>> quote(
    Customer customer,
    List<DraftLine> lines,
  ) => api.quote({
    'customer_id': customer.id,
    'lines': lines.map((l) => l.toJson()).toList(),
  });

  Future<void> cancelOrder(String id) async {
    await api.cancelOrder(id);
    await sync.pullOrders();
    await reload();
  }

  Future<void> retry(String id) async {
    await db.retry(id);
    await reload();
    unawaited(syncNow());
  }

  Future<void> discard(String id) async {
    await db.discard(id);
    await reload();
  }
}
