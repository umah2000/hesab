import 'dart:typed_data';

import 'package:flutter/material.dart';

import '../format.dart';
import '../models.dart';
import '../state.dart';

/// A status is always text + icon, never colour alone.
class StatusChip extends StatelessWidget {
  const StatusChip(this.status, {super.key});
  final String status;

  @override
  Widget build(BuildContext context) {
    final (IconData icon, Color color) = switch (status) {
      'submitted' => (Icons.hourglass_top_rounded, const Color(0xFFB45309)),
      'approved' => (Icons.verified_rounded, const Color(0xFF2563EB)),
      'invoiced' => (Icons.receipt_long_rounded, const Color(0xFF4F46E5)),
      'delivered' => (Icons.local_shipping_rounded, const Color(0xFF15803D)),
      'rejected' || 'failed' => (Icons.error_rounded, const Color(0xFFB91C1C)),
      'cancelled' => (Icons.block_rounded, const Color(0xFF6B7280)),
      _ => (Icons.cloud_upload_rounded, const Color(0xFF6B7280)),
    };
    return Container(
      padding: const EdgeInsets.symmetric(horizontal: 8, vertical: 3),
      decoration: BoxDecoration(
        color: color.withValues(alpha: 0.1),
        borderRadius: BorderRadius.circular(99),
      ),
      child: Row(
        mainAxisSize: MainAxisSize.min,
        children: [
          Icon(icon, size: 14, color: color),
          const SizedBox(width: 4),
          Text(
            orderStatusLabel[status] ?? status,
            style: TextStyle(
              color: color,
              fontSize: 12,
              fontWeight: FontWeight.w600,
            ),
          ),
        ],
      ),
    );
  }
}

class SyncBadge extends StatelessWidget {
  const SyncBadge({super.key, required this.state});
  final AppState state;

  @override
  Widget build(BuildContext context) {
    final offline = !state.online;
    final label = state.syncing
        ? 'در حال ارسال…'
        : offline
        ? 'آفلاین'
        : state.pending > 0
        ? '${faDigits(state.pending)} در صف'
        : 'به‌روز';
    final color = offline ? const Color(0xFFB45309) : const Color(0xFF15803D);
    return Semantics(
      label: 'وضعیت ارتباط: $label',
      child: Container(
        padding: const EdgeInsets.symmetric(horizontal: 10, vertical: 4),
        decoration: BoxDecoration(
          color: color.withValues(alpha: 0.12),
          borderRadius: BorderRadius.circular(99),
        ),
        child: Row(
          mainAxisSize: MainAxisSize.min,
          children: [
            Icon(
              state.syncing
                  ? Icons.sync_rounded
                  : offline
                  ? Icons.cloud_off_rounded
                  : Icons.cloud_done_rounded,
              size: 16,
              color: color,
            ),
            const SizedBox(width: 6),
            Text(
              label,
              style: TextStyle(
                color: color,
                fontWeight: FontWeight.w600,
                fontSize: 12,
              ),
            ),
          ],
        ),
      ),
    );
  }
}

class EmptyView extends StatelessWidget {
  const EmptyView({
    super.key,
    required this.icon,
    required this.title,
    this.detail,
  });
  final IconData icon;
  final String title;
  final String? detail;

  @override
  Widget build(BuildContext context) {
    return Center(
      child: Padding(
        padding: const EdgeInsets.all(32),
        child: Column(
          mainAxisSize: MainAxisSize.min,
          children: [
            Icon(icon, size: 48, color: Theme.of(context).colorScheme.outline),
            const SizedBox(height: 12),
            Text(title, style: Theme.of(context).textTheme.titleMedium),
            if (detail != null) ...[
              const SizedBox(height: 6),
              Text(
                detail!,
                textAlign: TextAlign.center,
                style: TextStyle(color: Theme.of(context).colorScheme.outline),
              ),
            ],
          ],
        ),
      ),
    );
  }
}

class LabelValue extends StatelessWidget {
  const LabelValue(this.label, this.value, {super.key, this.bold = false});
  final String label;
  final String value;
  final bool bold;

  @override
  Widget build(BuildContext context) {
    return Padding(
      padding: const EdgeInsets.symmetric(vertical: 3),
      child: Row(
        children: [
          Expanded(
            child: Text(
              label,
              style: TextStyle(color: Theme.of(context).colorScheme.outline),
            ),
          ),
          Text(
            value,
            style: TextStyle(
              fontWeight: bold ? FontWeight.w800 : FontWeight.w500,
            ),
          ),
        ],
      ),
    );
  }
}

/// One product photo from the phone's store (or the server, then kept). Shows a
/// placeholder while loading and when there is none, so a list never waits on photos.
class Photo extends StatefulWidget {
  const Photo({
    super.key,
    required this.state,
    required this.id,
    this.large = false,
    this.fit = BoxFit.cover,
  });
  final AppState state;
  final String? id;
  final bool large;
  final BoxFit fit;

  @override
  State<Photo> createState() => _PhotoState();
}

class _PhotoState extends State<Photo> {
  Future<Uint8List?>? _bytes;

  @override
  void initState() {
    super.initState();
    _load();
  }

  @override
  void didUpdateWidget(Photo old) {
    super.didUpdateWidget(old);
    if (old.id != widget.id || old.large != widget.large) _load();
  }

  void _load() => _bytes = widget.id == null
      ? null
      : widget.state.images.get(widget.id!, large: widget.large);

  @override
  Widget build(BuildContext context) {
    final placeholder = ColoredBox(
      color: Theme.of(context).colorScheme.surfaceContainerHighest,
      child: Center(
        child: Icon(
          widget.id == null
              ? Icons.image_not_supported_outlined
              : Icons.image_outlined,
          color: Theme.of(context).colorScheme.outline,
        ),
      ),
    );
    if (_bytes == null) return placeholder;
    return FutureBuilder<Uint8List?>(
      future: _bytes,
      builder: (context, snap) {
        final b = snap.data;
        if (b == null) return placeholder;
        return Image.memory(
          b,
          fit: widget.fit,
          gaplessPlayback: true,
          errorBuilder: (_, _, _) => placeholder,
        );
      },
    );
  }
}

/// The main photo of an item as a small rounded square.
class ItemThumb extends StatelessWidget {
  const ItemThumb({
    super.key,
    required this.state,
    required this.item,
    this.size = 48,
  });
  final AppState state;
  final Item item;
  final double size;

  @override
  Widget build(BuildContext context) => ClipRRect(
    borderRadius: BorderRadius.circular(10),
    child: SizedBox.square(
      dimension: size,
      child: Photo(
        state: state,
        id: item.imageIds.isEmpty ? null : item.imageIds.first,
      ),
    ),
  );
}
