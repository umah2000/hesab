/// What the app asks of the phone itself (ADR-0026): its position, a map app, the share
/// sheet and system notifications. Behind an interface so tests and the screenshot
/// harness run without plugins.
library;

import 'dart:io';

import 'package:flutter/foundation.dart';
import 'package:flutter_local_notifications/flutter_local_notifications.dart';
import 'package:geolocator/geolocator.dart';
import 'package:path_provider/path_provider.dart';
import 'package:share_plus/share_plus.dart';
import 'package:url_launcher/url_launcher.dart';

class GeoPoint {
  const GeoPoint(this.latitude, this.longitude, [this.accuracy]);
  final double latitude;
  final double longitude;
  final double? accuracy;

  /// Six decimals (about 10 cm), as the server stores it.
  String get lat => latitude.toStringAsFixed(6);
  String get lon => longitude.toStringAsFixed(6);
}

abstract class DeviceServices {
  /// The phone's position, or null when location is off or the visitor said no.
  Future<GeoPoint?> position();

  /// Opens the map app (Neshan, Balad, Google Maps…) at a place; false if none.
  Future<bool> openMap(double latitude, double longitude, String label);

  Future<void> shareImage(Uint8List png, String fileName, String text);

  Future<void> notify(int id, String title, String? body);
}

class PhoneServices implements DeviceServices {
  final _notifications = FlutterLocalNotificationsPlugin();
  bool _ready = false;

  Future<void> _init() async {
    if (_ready) return;
    await _notifications.initialize(
      settings: const InitializationSettings(
        android: AndroidInitializationSettings('@mipmap/ic_launcher'),
      ),
    );
    await _notifications
        .resolvePlatformSpecificImplementation<
          AndroidFlutterLocalNotificationsPlugin
        >()
        ?.requestNotificationsPermission();
    _ready = true;
  }

  @override
  Future<GeoPoint?> position() async {
    try {
      if (!await Geolocator.isLocationServiceEnabled()) return null;
      var perm = await Geolocator.checkPermission();
      if (perm == LocationPermission.denied) {
        perm = await Geolocator.requestPermission();
      }
      if (perm == LocationPermission.denied ||
          perm == LocationPermission.deniedForever) {
        return null;
      }
      final p = await Geolocator.getCurrentPosition(
        locationSettings: const LocationSettings(
          accuracy: LocationAccuracy.high,
          timeLimit: Duration(seconds: 15),
        ),
      );
      return GeoPoint(p.latitude, p.longitude, p.accuracy);
    } catch (e) {
      debugPrint('position unavailable: $e');
      return null;
    }
  }

  @override
  Future<bool> openMap(double latitude, double longitude, String label) async {
    final lat = latitude.toStringAsFixed(6), lon = longitude.toStringAsFixed(6);
    final geo = Uri.parse(
      'geo:$lat,$lon?q=$lat,$lon(${Uri.encodeComponent(label)})',
    );
    if (await launchUrl(geo, mode: LaunchMode.externalApplication)) {
      return true;
    }
    return launchUrl(
      Uri.parse(
        'https://www.openstreetmap.org/?mlat=$lat&mlon=$lon#map=17/$lat/$lon',
      ),
      mode: LaunchMode.externalApplication,
    );
  }

  @override
  Future<void> shareImage(Uint8List png, String fileName, String text) async {
    final dir = await getTemporaryDirectory();
    final file = File('${dir.path}/$fileName');
    await file.writeAsBytes(png, flush: true);
    await SharePlus.instance.share(
      ShareParams(
        files: [XFile(file.path, mimeType: 'image/png')],
        text: text,
      ),
    );
  }

  @override
  Future<void> notify(int id, String title, String? body) async {
    try {
      await _init();
      await _notifications.show(
        id: id,
        title: title,
        body: body,
        notificationDetails: const NotificationDetails(
          android: AndroidNotificationDetails(
            'visitor_updates',
            'وضعیت سفارش‌ها و وصول‌ها',
            channelDescription:
                'تأیید، رد، فاکتور و تحویل سفارش؛ تصمیم وصول و مشتری جدید',
            importance: Importance.defaultImportance,
          ),
        ),
      );
    } catch (e) {
      debugPrint('notification not shown: $e');
    }
  }
}

/// For tests and screenshots: records what was asked.
class FakeDevice implements DeviceServices {
  GeoPoint? here = const GeoPoint(36.2901, 59.607, 12);
  final opened = <String>[];
  final shared = <String>[];
  final shown = <String>[];

  @override
  Future<GeoPoint?> position() async => here;

  @override
  Future<bool> openMap(double latitude, double longitude, String label) async {
    opened.add(label);
    return true;
  }

  @override
  Future<void> shareImage(Uint8List png, String fileName, String text) async =>
      shared.add(fileName);

  @override
  Future<void> notify(int id, String title, String? body) async =>
      shown.add(title);
}
