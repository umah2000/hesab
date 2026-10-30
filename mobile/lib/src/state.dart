/// App state: session, offline catalogue, queue and orders (one ChangeNotifier).
library;

import 'dart:async';
import 'dart:convert';

import 'package:decimal/decimal.dart';
import 'package:flutter/foundation.dart';
import 'package:uuid/uuid.dart';

import 'api.dart';
import 'db.dart';
import 'device.dart';
import 'images.dart';
import 'models.dart';
import 'sync.dart';
import 'tokens.dart';

class AppState extends ChangeNotifier {
  AppState({
    required this.api,
    required this.db,
    this.deviceName = 'Android',
    DeviceServices? device,
  }) : device = device ?? FakeDevice(),
       sync = SyncService(api, db),
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

  /// The phone's position, map app, share sheet and notifications.
  final DeviceServices device;
  static const _uuid = Uuid();

  Catalog? catalog;
  List<Map<String, dynamic>> orders = [];

  /// From the last sync (ADR-0026); read from the phone when offline.
  List<Map<String, dynamic>> collections = [];
  List<Map<String, dynamic>> customerRequests = [];
  List<Map<String, dynamic>> notifications = [];

  /// The visitor allowed the app to record where visits and collections happen.
  bool gps = false;
  List<OutboxEntry> outbox = [];
  bool online = false;
  bool syncing = false;
  bool signedOut = false;

  /// What «تنظیمات اتصال» holds (address, port, user; the password if remembered).
  ConnectionSettings? settings;

  /// «حالت سبک»: no blur, for slow phones (kept on the phone).
  final liteMode = ValueNotifier<bool>(false);
  bool get lite => liteMode.value;
  DateTime? syncedAt;
  String? syncError;
  Timer? _timer;

  Session? get session => api.session;
  bool get signedIn => api.session != null;
  int get pending => outbox.where((e) => e.status == 'pending').length;

  /// The server lacks the v2 endpoints: visits, collections and requests wait (ADR-0026).
  bool serverOld = false;
  int get failed => outbox.where((e) => e.status == 'failed').length;
  int get unread => notifications.where((n) => n['read_at'] == null).length;

  Future<void> start() async {
    await api.restore();
    settings = await api.store.loadSettings();
    liteMode.value = await db.get('lite') == '1';
    // Signed out while offline (or an old session): the saved password signs in again.
    final c = settings;
    if (!signedIn && c != null && c.canSignIn) {
      try {
        await login(c);
      } on ApiException {
        // Shown on the sign-in screen when the visitor tries themself.
      } on NetworkException {
        // Offline: the sign-in screen; the queue stays on the phone.
      }
    }
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
    collections = await _list('collections', user);
    customerRequests = await _list('customer_requests', user);
    notifications = await _list('notifications', user);
    gps = await db.get('gps') == '1';
    serverOld = await sync.serverIsOld();
    notifyListeners();
  }

  Future<List<Map<String, dynamic>>> _list(String key, String? user) async {
    if (user == null) return [];
    final raw = await db.get('$key:$user');
    if (raw == null) return [];
    return (jsonDecode(raw) as List).cast<Map<String, dynamic>>();
  }

  /// The server address for [c]; release builds accept HTTPS only (mobile data).
  String serverOf(ConnectionSettings c) =>
      normalizeServer(c.host, allowHttp: kDebugMode, port: c.port);

  /// Is the server in [c] answering? For «آزمایش اتصال».
  Future<void> testConnection(ConnectionSettings c) => api.ping(serverOf(c));

  /// Sign in with [c] and keep it (the password only if [ConnectionSettings.remember]).
  Future<void> login(ConnectionSettings c) async {
    final server = serverOf(c);
    await api.login(server, c.username.trim(), c.password ?? '', deviceName);
    await api.store.saveSettings(c);
    settings = await api.store.loadSettings();
    signedOut = false;
    await reload();
    await syncNow();
  }

  /// Signing out keeps the queue: it is sent when the same visitor signs in again.
  Future<void> logout() async {
    await api.logout();
    await api.store.forgetPassword();
    settings = await api.store.loadSettings();
    await reload();
  }

  Future<void> setLite(bool on) async {
    liteMode.value = on;
    await db.put('lite', on ? '1' : '0');
  }

  Future<void> syncNow() async {
    if (syncing || !signedIn) return;
    syncing = true;
    syncError = null;
    notifyListeners();
    try {
      final r = await sync.run();
      online = r.online;
      if (r.online) await _announce();
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

  /// New unread notifications become phone notifications, each only once.
  Future<void> _announce() async {
    final user = api.session?.userId;
    if (user == null) return;
    final fresh = await _list('notifications', user);
    final key = 'notified:$user';
    final raw = await db.get(key);
    final seen = raw == null
        ? null
        : (jsonDecode(raw) as List).cast<String>().toSet();
    final ids = <String>{};
    for (final n in fresh) {
      final id = n['id'] as String;
      ids.add(id);
      // The first sync after sign-in does not replay old ones.
      if (seen != null && !seen.contains(id) && n['read_at'] == null) {
        await device.notify(
          id.hashCode & 0x7fffffff,
          n['title'] as String,
          n['body'] as String?,
        );
      }
    }
    await db.put(key, jsonEncode(ids.toList()));
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
    final here = await currentPosition();
    await db.addOutbox(visit, user, 'visit', {
      'id': visit,
      'customer_id': customer.id,
      'visited_at': now,
      'outcome': 'order',
      'order_id': id,
      ...?_where(here, accuracy: true),
    });
    await reload();
    unawaited(syncNow());
    return id;
  }

  Future<void> logVisit(Customer customer, String outcome, String? note) async {
    final user = api.session!.userId;
    final id = _uuid.v4();
    final here = await currentPosition();
    await db.addOutbox(id, user, 'visit', {
      'id': id,
      'customer_id': customer.id,
      'visited_at': DateTime.now().toUtc().toIso8601String(),
      'outcome': outcome,
      if (note != null && note.trim().isNotEmpty) 'note': note.trim(),
      ...?_where(here, accuracy: true),
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

  // --- visitor app v2 (ADR-0026) -------------------------------------------------

  Future<void> setGps(bool on) async {
    gps = on;
    await db.put('gps', on ? '1' : '0');
    if (on) await device.position(); // asks Android for the permission now
    notifyListeners();
  }

  /// The phone's position, only when the visitor allowed it.
  Future<GeoPoint?> currentPosition() =>
      gps ? device.position() : Future.value(null);

  Map<String, dynamic>? _where(GeoPoint? p, {bool accuracy = false}) =>
      p == null
      ? null
      : {
          'latitude': p.lat,
          'longitude': p.lon,
          if (accuracy && p.accuracy != null) 'accuracy_m': p.accuracy!.round(),
        };

  /// Queue a collection (cash, cheque, card-to-card); the treasury approves it.
  Future<String> addCollection(Map<String, dynamic> fields) async {
    final user = api.session!.userId;
    final id = _uuid.v4();
    final here = await currentPosition();
    await db.addOutbox(id, user, 'collection', {
      'id': id,
      'collected_at': DateTime.now().toUtc().toIso8601String(),
      ...fields,
      ...?_where(here),
    });
    await reload();
    unawaited(syncNow());
    return id;
  }

  /// Queue a new-customer request for the back office to approve.
  Future<String> addCustomerRequest(
    Map<String, dynamic> fields, {
    GeoPoint? at,
  }) async {
    final user = api.session!.userId;
    final id = _uuid.v4();
    await db.addOutbox(id, user, 'customer_request', {
      'id': id,
      ...fields,
      ...?_where(at),
    });
    await reload();
    unawaited(syncNow());
    return id;
  }

  /// Record where the shop is (online only; the next sync brings it to the list).
  Future<void> setCustomerLocation(Customer c, GeoPoint p) async {
    await api.setCustomerLocation(c.id, p.lat, p.lon);
    unawaited(syncNow());
  }

  /// A server answer kept on the phone, so the last copy shows without a connection.
  /// Returns (data, fetched now?); null data when never fetched and offline.
  Future<(Map<String, dynamic>?, bool)> cached(
    String key,
    Future<Map<String, dynamic>> Function() fetch,
  ) async {
    final user = api.session?.userId ?? '';
    try {
      final fresh = await fetch();
      await db.put('cache:$user:$key', jsonEncode(fresh));
      return (fresh, true);
    } on NetworkException {
      final raw = await db.get('cache:$user:$key');
      return (
        raw == null ? null : jsonDecode(raw) as Map<String, dynamic>,
        false,
      );
    }
  }

  Future<(Map<String, dynamic>?, bool)> customerHistory(String id) =>
      cached('history:$id', () => api.customerHistory(id));

  Future<(Map<String, dynamic>?, bool)> customerAccount(String id) =>
      cached('account:$id', () => api.customerAccount(id));

  Future<(Map<String, dynamic>?, bool)> invoice(String id) =>
      cached('invoice:$id', () => api.invoice(id));

  Future<(Map<String, dynamic>?, bool)> report(String period, {String? date}) =>
      cached(
        'report:$period:${date ?? 'now'}',
        () => api.report(period, date: date),
      );

  Future<void> readAllNotifications() async {
    final user = api.session?.userId;
    if (user == null || unread == 0) return;
    final now = DateTime.now().toUtc().toIso8601String();
    notifications = [
      for (final n in notifications) {...n, 'read_at': n['read_at'] ?? now},
    ];
    await db.put('notifications:$user', jsonEncode(notifications));
    notifyListeners();
    try {
      await api.markNotificationsRead();
    } on NetworkException {
      // Marked on the phone; the server keeps them unread until the next time.
    }
  }
}
