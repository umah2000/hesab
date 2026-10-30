import 'package:decimal/decimal.dart';
import 'package:flutter/material.dart';

import '../api.dart';
import '../format.dart';
import '../models.dart';
import '../state.dart';
import 'parts.dart';
import 'widgets.dart';

/// The visitor's own report: today, this week (from Saturday) or this Jalali month,
/// with the previous period beside it. Only this visitor's orders are counted (ADR-0026).
class ReportTab extends StatefulWidget {
  const ReportTab({super.key, required this.state, this.today});
  final AppState state;

  /// Fixed day for tests and screenshots.
  final DateTime? today;

  @override
  State<ReportTab> createState() => _ReportTabState();
}

class _ReportTabState extends State<ReportTab> {
  String _period = 'month';
  late DateTime _day = widget.today ?? DateTime.now();
  late Future<(Map<String, dynamic>?, bool)> _load = _fetch();

  Future<(Map<String, dynamic>?, bool)> _fetch() {
    final now = widget.today ?? DateTime.now();
    final same = tehran(_day).difference(tehran(now)).inDays == 0;
    return widget.state.report(
      _period,
      date: same ? null : tehran(_day).toIso8601String().substring(0, 10),
    );
  }

  void _set(String period) => setState(() {
    _period = period;
    _day = widget.today ?? DateTime.now();
    _load = _fetch();
  });

  void _step(int dir) => setState(() {
    if (_period == 'month') {
      // By Jalali month (31, 30 or 29 days), landing mid-month.
      final (y, m, _) = toJalali(tehran(_day));
      var nm = m + dir, ny = y;
      if (nm < 1) (nm, ny) = (12, y - 1);
      if (nm > 12) (nm, ny) = (1, y + 1);
      _day = fromJalali(ny, nm, 15);
    } else {
      _day = _day.add(Duration(days: (_period == 'day' ? 1 : 7) * dir));
    }
    _load = _fetch();
  });

  @override
  Widget build(BuildContext context) {
    final cur = widget.state.catalog?.currency ?? 'IRT';
    return RefreshIndicator(
      onRefresh: () async {
        setState(() => _load = _fetch());
        await _load;
      },
      child: ListView(
        padding: const EdgeInsets.fromLTRB(16, 10, 16, 24),
        children: [
          SegmentedButton<String>(
            segments: const [
              ButtonSegment(value: 'day', label: Text('روز')),
              ButtonSegment(value: 'week', label: Text('هفته')),
              ButtonSegment(value: 'month', label: Text('ماه')),
            ],
            selected: {_period},
            onSelectionChanged: (v) => _set(v.first),
          ),
          const SizedBox(height: 6),
          FutureBuilder(
            future: _load,
            builder: (context, snap) {
              if (snap.hasError) {
                final e = snap.error;
                return EmptyView(
                  icon: Icons.error_outline_rounded,
                  title: e is ApiException ? e.message : 'گزارش دریافت نشد',
                );
              }
              if (!snap.hasData) {
                return const Padding(
                  padding: EdgeInsets.all(40),
                  child: Center(child: CircularProgressIndicator()),
                );
              }
              final (r, fresh) = snap.data!;
              if (r == null) {
                return const EmptyView(
                  icon: Icons.cloud_off_rounded,
                  title: 'بدون اینترنت',
                  detail: 'گزارش این دوره هنوز روی گوشی ذخیره نشده است.',
                );
              }
              return _Report(
                r: r,
                fresh: fresh,
                currency: cur,
                period: _period,
                onStep: _step,
              );
            },
          ),
        ],
      ),
    );
  }
}

class _Report extends StatelessWidget {
  const _Report({
    required this.r,
    required this.fresh,
    required this.currency,
    required this.period,
    required this.onStep,
  });
  final Map<String, dynamic> r;
  final bool fresh;
  final String currency;
  final String period;
  final void Function(int) onStep;

  @override
  Widget build(BuildContext context) {
    final cur = (r['current'] as Map).cast<String, dynamic>();
    final prev = (r['previous'] as Map).cast<String, dynamic>();
    Decimal d(Map<String, dynamic> m, String k) => dec(m[k] as String);
    num n(Map<String, dynamic> m, String k) => m[k] as num;
    final prevName = switch (period) {
      'day' => 'دیروز',
      'week' => 'هفته‌ی قبل',
      _ => 'ماه قبل',
    };
    final target = r['target'] == null ? null : dec(r['target'] as String);
    final progress = r['target_progress'] == null
        ? Decimal.zero
        : dec(r['target_progress'] as String);
    final topC = (r['top_customers'] as List).cast<Map<String, dynamic>>();
    final topI = (r['top_items'] as List).cast<Map<String, dynamic>>();
    final reasons = (cur['no_order_reasons'] as Map).cast<String, dynamic>();
    final soft = Theme.of(context).colorScheme.onSurfaceVariant;
    double frac(Decimal a, Decimal b) =>
        b == Decimal.zero ? 0 : (a / b).toDouble();
    final maxC = topC.isEmpty
        ? Decimal.one
        : dec(topC.first['amount'] as String);
    final maxI = topI.isEmpty
        ? Decimal.one
        : dec(topI.first['amount'] as String);
    return Column(
      crossAxisAlignment: CrossAxisAlignment.stretch,
      children: [
        Row(
          children: [
            IconButton(
              tooltip: 'دوره‌ی قبل',
              onPressed: () => onStep(-1),
              icon: const Icon(Icons.chevron_right_rounded),
            ),
            Expanded(
              child: Text(
                faDigits(r['label'] as String),
                textAlign: TextAlign.center,
                style: const TextStyle(
                  fontWeight: FontWeight.w800,
                  fontSize: 15,
                ),
              ),
            ),
            IconButton(
              tooltip: 'دوره‌ی بعد',
              onPressed: () => onStep(1),
              icon: const Icon(Icons.chevron_left_rounded),
            ),
          ],
        ),
        OfflineNote(fresh: fresh),
        GridView.count(
          crossAxisCount: 2,
          shrinkWrap: true,
          physics: const NeverScrollableScrollPhysics(),
          mainAxisSpacing: 8,
          crossAxisSpacing: 8,
          childAspectRatio: 1.75,
          children: [
            Kpi(
              label: 'مبلغ سفارش‌ها',
              value: money(d(cur, 'ordered_amount'), currency),
              change: Change(
                now: d(cur, 'ordered_amount').toDouble(),
                before: d(prev, 'ordered_amount').toDouble(),
                suffix: ' نسبت به $prevName',
              ),
            ),
            Kpi(
              label: 'مبلغ فاکتورشده',
              value: money(d(cur, 'invoiced_amount'), currency),
              change: Change(
                now: d(cur, 'invoiced_amount').toDouble(),
                before: d(prev, 'invoiced_amount').toDouble(),
              ),
            ),
            Kpi(
              label: 'سفارش / فاکتور',
              value:
                  '${faDigits(n(cur, 'ordered_count'))} / ${faDigits(n(cur, 'invoiced_count'))}',
              change: Text(
                '${faDigits(n(cur, 'rejected_count'))} رد · ${faDigits(n(cur, 'pending_count'))} در انتظار',
                style: TextStyle(fontSize: 11, color: soft),
              ),
            ),
            Kpi(
              label: 'مشتری خریدار',
              value: faDigits(n(cur, 'customers')),
              change: Change(
                now: n(cur, 'customers'),
                before: n(prev, 'customers'),
              ),
            ),
          ],
        ),
        const SizedBox(height: 8),
        Card(
          child: Padding(
            padding: const EdgeInsets.all(14),
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.stretch,
              children: [
                Row(
                  children: [
                    const Expanded(
                      child: Text(
                        'هدف ماه',
                        style: TextStyle(fontWeight: FontWeight.w800),
                      ),
                    ),
                    if (target != null && target > Decimal.zero)
                      Text(
                        '${faDigits((frac(progress, target) * 100).round())}٪',
                        style: TextStyle(
                          fontWeight: FontWeight.w800,
                          color: Theme.of(context).colorScheme.primary,
                        ),
                      ),
                  ],
                ),
                const SizedBox(height: 6),
                if (target == null)
                  Text(
                    'مدیر هنوز هدفی برای این ماه تعیین نکرده است.',
                    style: TextStyle(fontSize: 12, color: soft),
                  )
                else ...[
                  ClipRRect(
                    borderRadius: BorderRadius.circular(6),
                    child: LinearProgressIndicator(
                      value: frac(progress, target).clamp(0, 1),
                      minHeight: 10,
                    ),
                  ),
                  const SizedBox(height: 4),
                  Text(
                    '${money(progress, currency)} از ${money(target, currency, unit: true)} (فاکتورشده)',
                    style: TextStyle(fontSize: 12, color: soft),
                  ),
                ],
                const SizedBox(height: 4),
                Text(
                  'میانگین هر سفارش ${money(d(cur, 'average_order'), currency, unit: true)} · ${faDigits(n(cur, 'visits'))} بازدید',
                  style: TextStyle(fontSize: 12, color: soft),
                ),
              ],
            ),
          ),
        ),
        if (topC.isNotEmpty) ...[
          const SectionTitle('مشتریان برتر'),
          Card(
            child: Padding(
              padding: const EdgeInsets.all(12),
              child: Column(
                children: [
                  for (final c in topC)
                    ShareBar(
                      label: c['name'] as String,
                      fraction: frac(dec(c['amount'] as String), maxC),
                      value: money(dec(c['amount'] as String), currency),
                    ),
                ],
              ),
            ),
          ),
        ],
        if (topI.isNotEmpty) ...[
          const SectionTitle('کالاهای پرفروش'),
          Card(
            child: Padding(
              padding: const EdgeInsets.all(12),
              child: Column(
                children: [
                  for (final i in topI)
                    ShareBar(
                      label: i['name'] as String,
                      fraction: frac(dec(i['amount'] as String), maxI),
                      value: money(dec(i['amount'] as String), currency),
                    ),
                ],
              ),
            ),
          ),
        ],
        if (reasons.isNotEmpty) ...[
          SectionTitle(
            'بازدید بدون سفارش',
            trailing: faDigits(
              reasons.values.fold<num>(0, (a, b) => a + (b as num)),
            ),
          ),
          Card(
            child: Padding(
              padding: const EdgeInsets.all(12),
              child: Text(
                reasons.entries
                    .map(
                      (e) =>
                          '${visitOutcomeLabel[e.key] ?? e.key} ${faDigits(e.value)}',
                    )
                    .join(' · '),
                style: const TextStyle(fontSize: 13),
              ),
            ),
          ),
        ],
        const SizedBox(height: 8),
        Text(
          'فقط سفارش‌های خودتان حساب می‌شود؛ خرید حضوری و سفارش ویزیتور دیگر در این گزارش نیست.',
          textAlign: TextAlign.center,
          style: TextStyle(fontSize: 11, color: soft),
        ),
      ],
    );
  }
}
