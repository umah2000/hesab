/// Where the session lives on the phone (ADR-0004): Android Keystore via
/// flutter_secure_storage. Nothing here is ever logged.
library;

import 'package:flutter_secure_storage/flutter_secure_storage.dart';

class Session {
  const Session({
    required this.server,
    required this.userId,
    required this.username,
    required this.fullName,
    required this.access,
    required this.accessExpiresAt,
    required this.refresh,
    required this.refreshExpiresAt,
  });

  final String server;
  final String userId;
  final String username;
  final String fullName;
  final String access;
  final DateTime accessExpiresAt;
  final String refresh;
  final DateTime refreshExpiresAt;

  Map<String, String> toMap() => {
    'server': server,
    'user_id': userId,
    'username': username,
    'full_name': fullName,
    'access': access,
    'access_expires_at': accessExpiresAt.toIso8601String(),
    'refresh': refresh,
    'refresh_expires_at': refreshExpiresAt.toIso8601String(),
  };

  static Session? fromMap(Map<String, String> m) {
    try {
      return Session(
        server: m['server']!,
        userId: m['user_id']!,
        username: m['username']!,
        fullName: m['full_name'] ?? '',
        access: m['access']!,
        accessExpiresAt: DateTime.parse(m['access_expires_at']!),
        refresh: m['refresh']!,
        refreshExpiresAt: DateTime.parse(m['refresh_expires_at']!),
      );
    } catch (_) {
      return null;
    }
  }
}

abstract class TokenStore {
  Future<Session?> load();
  Future<void> save(Session s);
  Future<void> clear();

  /// The last server address typed in (kept after sign-out, it is not a secret).
  Future<String?> lastServer();
}

class SecureTokenStore implements TokenStore {
  SecureTokenStore([FlutterSecureStorage? storage])
    : _s = storage ?? const FlutterSecureStorage(aOptions: AndroidOptions());

  final FlutterSecureStorage _s;
  static const _keys = [
    'server',
    'user_id',
    'username',
    'full_name',
    'access',
    'access_expires_at',
    'refresh',
    'refresh_expires_at',
  ];

  @override
  Future<Session?> load() async {
    final all = await _s.readAll();
    if (!_keys.every(all.containsKey)) return null;
    return Session.fromMap(all);
  }

  @override
  Future<void> save(Session s) async {
    for (final e in s.toMap().entries) {
      await _s.write(key: e.key, value: e.value);
    }
    await _s.write(key: 'last_server', value: s.server);
  }

  @override
  Future<void> clear() async {
    for (final k in _keys) {
      await _s.delete(key: k);
    }
  }

  @override
  Future<String?> lastServer() => _s.read(key: 'last_server');
}

/// For tests and the screenshot harness.
class MemoryTokenStore implements TokenStore {
  Session? session;
  String? last;

  @override
  Future<Session?> load() async => session;

  @override
  Future<void> save(Session s) async {
    session = s;
    last = s.server;
  }

  @override
  Future<void> clear() async => session = null;

  @override
  Future<String?> lastServer() async => last;
}
