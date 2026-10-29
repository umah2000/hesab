import 'dart:async';

import 'package:flutter/material.dart';

import '../format.dart';
import '../state.dart';
import 'glass.dart';
import 'widgets.dart';

/// Decisions on the visitor's orders, collections and requests, and new targets
/// (ADR-0026). They arrive with every sync; opening this screen marks them read.
class NotificationsScreen extends StatefulWidget {
  const NotificationsScreen({super.key, required this.state});
  final AppState state;

  @override
  State<NotificationsScreen> createState() => _NotificationsScreenState();
}

class _NotificationsScreenState extends State<NotificationsScreen> {
  Timer? _read;

  @override
  void initState() {
    super.initState();
    // A moment later, so the visitor still sees which ones were new.
    _read = Timer(
      const Duration(seconds: 2),
      widget.state.readAllNotifications,
    );
  }

  @override
  void dispose() {
    _read?.cancel();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      appBar: AppBar(title: const Text('اعلان‌ها')),
      body: ListenableBuilder(
        listenable: widget.state,
        builder: (context, _) {
          final list = widget.state.notifications;
          if (list.isEmpty) {
            return const EmptyView(
              icon: Icons.notifications_none_rounded,
              title: 'اعلانی نیست',
              detail:
                  'تأیید یا رد سفارش‌ها و وصول‌ها این‌جا نمایش داده می‌شود.',
            );
          }
          return RefreshIndicator(
            onRefresh: widget.state.syncNow,
            child: ListView(
              padding: const EdgeInsets.fromLTRB(16, 8, 16, 24),
              children: [for (final n in list) _NotificationTile(n: n)],
            ),
          );
        },
      ),
    );
  }
}

class _NotificationTile extends StatelessWidget {
  const _NotificationTile({required this.n});
  final Map<String, dynamic> n;

  @override
  Widget build(BuildContext context) {
    final kind = n['kind'] as String;
    final (IconData icon, Color color) = switch (kind) {
      'order_approved' ||
      'customer_approved' ||
      'collection_approved' => (Icons.check_rounded, StatusPill.ok),
      'order_rejected' ||
      'customer_rejected' ||
      'collection_rejected' => (Icons.close_rounded, StatusPill.danger),
      'order_invoiced' => (Icons.receipt_long_rounded, const Color(0xFF4F46E5)),
      'order_delivered' => (Icons.local_shipping_rounded, StatusPill.ok),
      'target_set' => (Icons.flag_rounded, StatusPill.warning),
      _ => (Icons.notifications_rounded, const Color(0xFF6B7280)),
    };
    final unread = n['read_at'] == null;
    final soft = Theme.of(context).colorScheme.onSurfaceVariant;
    return Padding(
      padding: const EdgeInsets.only(bottom: 8),
      child: Card(
        child: Padding(
          padding: const EdgeInsets.all(12),
          child: Row(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              Container(
                width: 36,
                height: 36,
                decoration: BoxDecoration(
                  color: color.withValues(alpha: .14),
                  borderRadius: BorderRadius.circular(12),
                ),
                child: Icon(icon, color: color, size: 20),
              ),
              const SizedBox(width: 10),
              Expanded(
                child: Column(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    Text(
                      n['title'] as String,
                      style: TextStyle(
                        fontWeight: unread ? FontWeight.w800 : FontWeight.w600,
                      ),
                    ),
                    if (n['body'] != null)
                      Text(
                        n['body'] as String,
                        style: TextStyle(fontSize: 12, color: soft),
                      ),
                    Text(
                      jalaliDateTime(DateTime.parse(n['created_at'] as String)),
                      style: TextStyle(fontSize: 11, color: soft),
                    ),
                  ],
                ),
              ),
              if (unread)
                const StatusPill(
                  icon: Icons.fiber_new_rounded,
                  label: 'تازه',
                  color: Color(0xFF4F46E5),
                ),
            ],
          ),
        ),
      ),
    );
  }
}
