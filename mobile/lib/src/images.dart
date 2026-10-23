/// Product photos for the visitor (ADR-0022), usable without a connection.
///
/// * A photo id never changes content on the server, so a stored copy is never stale.
/// * Thumbnails of the whole catalogue are fetched while syncing; a large photo is
///   fetched the first time it is shown, or ahead of time with [prefetch] (large).
/// * Nothing here blocks an order: a missing photo is only a placeholder.
library;

import 'dart:typed_data';

import 'api.dart';
import 'db.dart';
import 'models.dart';

class ImageStore {
  ImageStore(this.api, this.db);
  final ApiClient api;
  final LocalDb db;

  // A few decoded-ready byte arrays, so scrolling back does not hit SQLite.
  final _memory = <String, Uint8List>{}; // insertion-ordered: LRU
  final _loading = <String, Future<Uint8List?>>{};
  static const _memoryLimit = 80;

  /// The photo from the phone, else from the server (then kept); null when neither.
  Future<Uint8List?> get(String id, {bool large = false}) {
    final key = '$id/${large ? 'large' : 'thumb'}';
    final hit = _memory.remove(key);
    if (hit != null) {
      _memory[key] = hit; // most recently used last
      return Future.value(hit);
    }
    // A block body: returning the removed future would make it wait on itself.
    return _loading[key] ??= _load(id, large, key).whenComplete(() {
      _loading.remove(key);
    });
  }

  Future<Uint8List?> _load(String id, bool large, String key) async {
    final size = large ? 'large' : 'thumb';
    var bytes = await db.image(id, size);
    if (bytes == null) {
      try {
        bytes = await api.image(id, large: large);
        await db.putImage(id, size, bytes);
      } on NetworkException {
        return null;
      } on ApiException {
        return null;
      }
    }
    _memory[key] = bytes;
    while (_memory.length > _memoryLimit) {
      _memory.remove(_memory.keys.first);
    }
    return bytes;
  }

  /// Fetches the photos of [items] the phone does not have yet; returns how many are
  /// on the phone at the end. Stops quietly when the connection drops.
  Future<int> prefetch(
    List<Item> items, {
    bool large = false,
    void Function(int done, int total)? progress,
  }) async {
    final size = large ? 'large' : 'thumb';
    final ids = [
      for (final i in items)
        for (final id in (large ? i.imageIds.take(1) : i.imageIds)) id,
    ];
    final have = await db.imageIds(size);
    final missing = ids.where((id) => !have.contains(id)).toList();
    var done = 0;
    for (final id in missing) {
      try {
        await db.putImage(id, size, await api.image(id, large: large));
      } on NetworkException {
        break;
      } on ApiException catch (e) {
        if (e.signedOut) rethrow;
      }
      done++;
      progress?.call(done, missing.length);
    }
    return (await db.imageIds(size)).intersection(ids.toSet()).length;
  }

  /// Forget photos that are no longer in the catalogue.
  Future<void> keepOnly(List<Item> items) async {
    final ids = {for (final i in items) ...i.imageIds};
    _memory.removeWhere((k, _) => !ids.contains(k.split('/').first));
    await db.keepImages(ids);
  }
}
