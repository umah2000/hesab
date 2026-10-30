/// Small pieces shared by the v2 screens (ADR-0026).
library;

import 'package:flutter/material.dart';

import '../format.dart';
import '../state.dart';
import 'glass.dart';

class SectionTitle extends StatelessWidget {
  const SectionTitle(this.title, {super.key, this.trailing});
  final String title;
  final String? trailing;

  @override
  Widget build(BuildContext context) {
    final soft = Theme.of(context).colorScheme.onSurfaceVariant;
    return Padding(
      padding: const EdgeInsets.fromLTRB(4, 14, 4, 6),
      child: Row(
        children: [
          Expanded(
            child: Text(
              title,
              style: TextStyle(
                fontWeight: FontWeight.w800,
                fontSize: 13,
                color: soft,
              ),
            ),
          ),
          if (trailing != null)
            Text(trailing!, style: TextStyle(fontSize: 12, color: soft)),
        ],
      ),
    );
  }
}

/// A figure with its label, for the report.
class Kpi extends StatelessWidget {
  const Kpi({super.key, required this.label, required this.value, this.change});
  final String label;
  final String value;
  final Widget? change;

  @override
  Widget build(BuildContext context) {
    final soft = Theme.of(context).colorScheme.onSurfaceVariant;
    return Card(
      child: Padding(
        padding: const EdgeInsets.all(12),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Text(label, style: TextStyle(fontSize: 11, color: soft)),
            const SizedBox(height: 2),
            FittedBox(
              fit: BoxFit.scaleDown,
              alignment: AlignmentDirectional.centerStart,
              child: Text(
                value,
                style: const TextStyle(
                  fontSize: 17,
                  fontWeight: FontWeight.w800,
                ),
              ),
            ),
            if (change != null) ...[const SizedBox(height: 2), change!],
          ],
        ),
      ),
    );
  }
}

/// «▲ ۱۲٪ نسبت به …» — text and arrow, never colour alone.
class Change extends StatelessWidget {
  const Change({
    super.key,
    required this.now,
    required this.before,
    this.suffix = '',
  });
  final num now;
  final num before;
  final String suffix;

  @override
  Widget build(BuildContext context) {
    if (before == 0) {
      return Text(
        now == 0 ? 'بدون تغییر' : 'دوره‌ی قبل صفر بود',
        style: TextStyle(
          fontSize: 11,
          color: Theme.of(context).colorScheme.onSurfaceVariant,
        ),
      );
    }
    final pct = ((now - before) / before * 100).round();
    final up = pct >= 0;
    final color = up ? StatusPill.ok : StatusPill.danger;
    return Text(
      '${up ? '▲' : '▼'} ${faDigits(pct.abs())}٪$suffix',
      style: TextStyle(fontSize: 11, fontWeight: FontWeight.w700, color: color),
    );
  }
}

/// A horizontal bar for «top» lists (RTL: fills from the start side).
class ShareBar extends StatelessWidget {
  const ShareBar({
    super.key,
    required this.label,
    required this.fraction,
    required this.value,
  });
  final String label;
  final double fraction;
  final String value;

  @override
  Widget build(BuildContext context) {
    final t = Theme.of(context);
    return Padding(
      padding: const EdgeInsets.symmetric(vertical: 4),
      child: Row(
        children: [
          SizedBox(
            width: 110,
            child: Text(
              label,
              maxLines: 1,
              overflow: TextOverflow.ellipsis,
              style: const TextStyle(fontSize: 12),
            ),
          ),
          Expanded(
            child: ClipRRect(
              borderRadius: BorderRadius.circular(4),
              child: LinearProgressIndicator(
                value: fraction.clamp(0, 1),
                minHeight: 8,
                backgroundColor: t.colorScheme.primary.withValues(alpha: .1),
              ),
            ),
          ),
          const SizedBox(width: 8),
          Text(
            value,
            style: const TextStyle(fontSize: 11, fontWeight: FontWeight.w700),
          ),
        ],
      ),
    );
  }
}

/// «آخرین داده‌ی ذخیره‌شده» when the screen shows what the phone kept.
class OfflineNote extends StatelessWidget {
  const OfflineNote({super.key, required this.fresh});
  final bool fresh;

  @override
  Widget build(BuildContext context) {
    if (fresh) return const SizedBox.shrink();
    return const Padding(
      padding: EdgeInsets.only(bottom: 8),
      child: Align(
        alignment: AlignmentDirectional.centerStart,
        child: StatusPill(
          icon: Icons.cloud_off_rounded,
          label: 'بدون اینترنت: آخرین داده‌ی ذخیره‌شده',
          color: StatusPill.warning,
        ),
      ),
    );
  }
}

/// The server has not been updated to v2 (ADR-0026): its work waits in the queue.
class ServerOutdatedNote extends StatelessWidget {
  const ServerOutdatedNote({super.key, required this.state});
  final AppState state;

  @override
  Widget build(BuildContext context) {
    if (!state.serverOld) return const SizedBox.shrink();
    return Padding(
      padding: const EdgeInsets.only(bottom: 10),
      child: Card(
        color: StatusPill.warning.withValues(alpha: .10),
        child: const Padding(
          padding: EdgeInsets.all(12),
          child: Row(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              Icon(Icons.system_update_rounded, color: StatusPill.warning),
              SizedBox(width: 10),
              Expanded(
                child: Text(
                  'نسخه‌ی سرور قدیمی است. سفارش‌ها ارسال می‌شوند، ولی بازدید، وصول و مشتری جدید '
                  'تا به‌روزرسانی سرور در صف می‌مانند و بعد خودکار ارسال می‌شوند.',
                  style: TextStyle(fontSize: 13, height: 1.6),
                ),
              ),
            ],
          ),
        ),
      ),
    );
  }
}

/// Where an invoice came from: this visitor, another visitor, or the shop.
class ChannelPill extends StatelessWidget {
  const ChannelPill({super.key, required this.channel, this.visitorName});
  final String channel;
  final String? visitorName;

  @override
  Widget build(BuildContext context) {
    return switch (channel) {
      'mine' => const StatusPill(
        icon: Icons.star_rounded,
        label: 'سفارش خودتان',
        color: Color(0xFF4F46E5),
      ),
      'visitor' => StatusPill(
        icon: Icons.person_rounded,
        label: 'ویزیتور: ${visitorName ?? ''}',
        color: const Color(0xFF4B5563),
      ),
      _ => const StatusPill(
        icon: Icons.storefront_rounded,
        label: 'حضوری',
        color: Color(0xFF0E7490),
      ),
    };
  }
}
