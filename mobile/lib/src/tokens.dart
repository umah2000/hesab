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

/// What the visitor typed in «تنظیمات اتصال». The password is kept only when they
/// chose to be remembered, so the app signs in again by itself when the session ends.
class ConnectionSettings {
  const ConnectionSettings({
    required this.host,
    this.port,
    required this.username,
    this.password,
    this.remember = true,
  });

  final String host;
  final int? port;
  final String username;
  final String? password;
  final bool remember;

  bool get canSignIn =>
      host.isNotEmpty && username.isNotEmpty && (password ?? '').isNotEmpty;

  /// `erp.shop.ir : 8443` for showing; the default HTTPS port is left out.
  String get label => port == null ? host : '$host : $port';

  ConnectionSettings withoutPassword() => ConnectionSettings(
    host: host,
    port: port,
    username: username,
    remember: remember,
  );
}

abstract class TokenStore {
  Future<Session?> load();
  Future<void> save(Session s);
  Future<void> clear();

  Future<ConnectionSettings?> loadSettings();
  Future<void> saveSettings(ConnectionSettings c);

  /// Signing out forgets the password; the address and user name stay.
  Future<void> forgetPassword();
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
  Future<ConnectionSettings?> loadSettings() async {
    final all = await _s.readAll();
    final host = all['cfg_host'];
    if (host == null) {
      // Installs from before the settings sheet kept only the last address.
      final last = Uri.tryParse(all['last_server'] ?? '');
      if (last == null || last.host.isEmpty) return null;
      return ConnectionSettings(
        host: last.host,
        port: last.hasPort ? last.port : null,
        username: all['username'] ?? '',
      );
    }
    return ConnectionSettings(
      host: host,
      port: int.tryParse(all['cfg_port'] ?? ''),
      username: all['cfg_user'] ?? '',
      password: all['cfg_pass'],
      remember: all['cfg_remember'] != '0',
    );
  }

  @override
  Future<void> saveSettings(ConnectionSettings c) async {
    await _s.write(key: 'cfg_host', value: c.host);
    if (c.port == null) {
      await _s.delete(key: 'cfg_port');
    } else {
      await _s.write(key: 'cfg_port', value: '${c.port}');
    }
    await _s.write(key: 'cfg_user', value: c.username);
    await _s.write(key: 'cfg_remember', value: c.remember ? '1' : '0');
    final pass = c.remember ? c.password : null;
    if (pass == null || pass.isEmpty) {
      await _s.delete(key: 'cfg_pass');
    } else {
      await _s.write(key: 'cfg_pass', value: pass);
    }
  }

  @override
  Future<void> forgetPassword() => _s.delete(key: 'cfg_pass');
}

/// For tests and the screenshot harness.
class MemoryTokenStore implements TokenStore {
  Session? session;
  ConnectionSettings? settings;

  @override
  Future<Session?> load() async => session;

  @override
  Future<void> save(Session s) async => session = s;

  @override
  Future<void> clear() async => session = null;

  @override
  Future<ConnectionSettings?> loadSettings() async => settings;

  @override
  Future<void> saveSettings(ConnectionSettings c) async =>
      settings = c.remember ? c : c.withoutPassword();

  @override
  Future<void> forgetPassword() async => settings = settings?.withoutPassword();
}
