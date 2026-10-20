/// The phone's own database (SQLite through sqflite).
///
/// * `meta`: the offline catalogue and customers (bootstrap) with its ETag.
/// * `outbox`: orders and visits written on the phone. An entry leaves `pending` only
///   when the server has answered for it; it is never deleted while pending, so a
///   dead battery or a sign-out does not lose an order.
/// * `orders`: the visitor's orders as the server last reported them (status).
library;

import 'dart:convert';

import 'package:sqflite/sqflite.dart';

class OutboxEntry {
  OutboxEntry({
    required this.id,
    required this.userId,
    required this.kind,
    required this.payload,
    required this.createdAt,
    required this.status,
    this.result,
    this.error,
    this.attempts = 0,
  });

  final String id;
  final String userId;
  final String kind; // order | visit
  final Map<String, dynamic> payload;
  final DateTime createdAt;
  final String status; // pending | sent | failed
  final Map<String, dynamic>? result;
  final String? error;
  final int attempts;

  static OutboxEntry fromRow(Map<String, Object?> r) => OutboxEntry(
    id: r['id'] as String,
    userId: r['user_id'] as String,
    kind: r['kind'] as String,
    payload: jsonDecode(r['payload'] as String) as Map<String, dynamic>,
    createdAt: DateTime.parse(r['created_at'] as String),
    status: r['status'] as String,
    result: r['result'] == null
        ? null
        : jsonDecode(r['result'] as String) as Map<String, dynamic>,
    error: r['error'] as String?,
    attempts: (r['attempts'] as int?) ?? 0,
  );
}

class LocalDb {
  LocalDb(this.db);
  final Database db;

  static Future<LocalDb> open(DatabaseFactory factory, String path) async {
    final db = await factory.openDatabase(
      path,
      options: OpenDatabaseOptions(
        version: 1,
        onCreate: (db, _) async {
          await db.execute(
            'CREATE TABLE meta (key TEXT PRIMARY KEY, value TEXT NOT NULL)',
          );
          await db.execute('''
            CREATE TABLE outbox (
              id TEXT PRIMARY KEY, user_id TEXT NOT NULL, kind TEXT NOT NULL,
              payload TEXT NOT NULL, created_at TEXT NOT NULL,
              status TEXT NOT NULL DEFAULT 'pending', result TEXT, error TEXT,
              attempts INTEGER NOT NULL DEFAULT 0)''');
          await db.execute(
            'CREATE INDEX ix_outbox_status ON outbox (status, created_at)',
          );
          await db.execute('''
            CREATE TABLE orders (
              id TEXT PRIMARY KEY, user_id TEXT NOT NULL, json TEXT NOT NULL,
              received_at TEXT NOT NULL)''');
        },
      ),
    );
    return LocalDb(db);
  }

  Future<String?> get(String key) async {
    final r = await db.query('meta', where: 'key = ?', whereArgs: [key]);
    return r.isEmpty ? null : r.first['value'] as String;
  }

  Future<void> put(String key, String value) => db.insert('meta', {
    'key': key,
    'value': value,
  }, conflictAlgorithm: ConflictAlgorithm.replace);

  Future<void> addOutbox(
    String id,
    String userId,
    String kind,
    Map<String, dynamic> payload, {
    DateTime? at, // tests pass a fixed time
  }) => db.insert('outbox', {
    'id': id,
    'user_id': userId,
    'kind': kind,
    'payload': jsonEncode(payload),
    'created_at': (at ?? DateTime.now()).toUtc().toIso8601String(),
  });

  Future<List<OutboxEntry>> outbox({String? userId, String? status}) async {
    final where = <String>[];
    final args = <Object>[];
    if (userId != null) {
      where.add('user_id = ?');
      args.add(userId);
    }
    if (status != null) {
      where.add('status = ?');
      args.add(status);
    }
    final rows = await db.query(
      'outbox',
      where: where.isEmpty ? null : where.join(' AND '),
      whereArgs: args,
      orderBy: 'created_at',
    );
    return rows.map(OutboxEntry.fromRow).toList();
  }

  Future<void> markSent(String id, Map<String, dynamic> result) => db.update(
    'outbox',
    {'status': 'sent', 'result': jsonEncode(result), 'error': null},
    where: 'id = ?',
    whereArgs: [id],
  );

  Future<void> markFailed(String id, String error) => db.update(
    'outbox',
    {'status': 'failed', 'error': error},
    where: 'id = ?',
    whereArgs: [id],
  );

  Future<void> retry(String id) => db.update(
    'outbox',
    {'status': 'pending', 'error': null},
    where: 'id = ?',
    whereArgs: [id],
  );

  Future<void> discard(String id) => db.delete(
    'outbox',
    where: "id = ? AND status = 'failed'",
    whereArgs: [id],
  );

  Future<void> bumpAttempts(String id) => db.rawUpdate(
    'UPDATE outbox SET attempts = attempts + 1 WHERE id = ?',
    [id],
  );

  Future<void> saveOrders(String userId, List<dynamic> orders) async {
    await db.transaction((tx) async {
      await tx.delete('orders', where: 'user_id = ?', whereArgs: [userId]);
      for (final o in orders.cast<Map<String, dynamic>>()) {
        await tx.insert('orders', {
          'id': o['id'],
          'user_id': userId,
          'json': jsonEncode(o),
          'received_at': o['received_at'],
        });
      }
    });
  }

  Future<List<Map<String, dynamic>>> orders(String userId) async {
    final rows = await db.query(
      'orders',
      where: 'user_id = ?',
      whereArgs: [userId],
      orderBy: 'received_at DESC',
    );
    return rows
        .map((r) => jsonDecode(r['json'] as String) as Map<String, dynamic>)
        .toList();
  }
}
