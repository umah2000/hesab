import 'dart:ui' as ui;

import 'package:decimal/decimal.dart';
import 'package:flutter/material.dart';
import 'package:flutter/rendering.dart';

import '../format.dart';
import '../models.dart';
import '../state.dart';
import 'glass.dart';
import 'order.dart';
import 'widgets.dart';

/// One of the visitor's orders: status with dates, the lines with the server's prices,
/// «تکرار» (same lines in a new order, priced again by the server) and a pre-invoice
/// image to send to the customer (ADR-0026).
class OrderDetailScreen extends StatelessWidget {
  const OrderDetailScreen({
    super.key,
    required this.state,
    required this.order,
  });
  final AppState state;
  final Map<String, dynamic> order;

  List<Map<String, dynamic>> get _lines =>
      ((order['lines'] as List?) ?? const []).cast<Map<String, dynamic>>();

  void _repeat(BuildContext context) {
    final cat = state.catalog;
    final customer = cat?.customer(order['customer_id'] as String);
    if (cat == null || customer == null) {
      ScaffoldMessenger.of(context).showSnackBar(
        const SnackBar(content: Text('این مشتری دیگر در فهرست شما نیست')),
      );
      return;
    }
    final lines = <DraftLine>[];
    var missing = 0;
    for (final l in _lines) {
      final item = cat.item(l['item_id'] as String);
      if (item == null) {
        missing++;
        continue;
      }
      final unit = item.units.any((u) => u.unitId == l['unit_id'])
          ? l['unit_id'] as String
          : item.baseUnitId;
      lines.add(DraftLine(item, unit, Decimal.parse(l['qty'] as String)));
    }
    if (missing > 0) {
      ScaffoldMessenger.of(context).showSnackBar(
        SnackBar(
          content: Text(
            '${faDigits(missing)} کالا دیگر فروخته نمی‌شود و حذف شد',
          ),
        ),
      );
    }
    Navigator.of(context).push(
      MaterialPageRoute(
        builder: (_) =>
            OrderScreen(state: state, customer: customer, initial: lines),
      ),
    );
  }

  @override
  Widget build(BuildContext context) {
    final cur = state.catalog?.currency ?? 'IRT';
    final o = order;
    final status = o['status'] as String;
    DateTime? at(String k) =>
        o[k] == null ? null : DateTime.parse(o[k] as String);
    final rejected = status == 'rejected' || status == 'cancelled';
    final steps = [
      ('ثبت', at('ordered_at'), true),
      (
        rejected ? (status == 'rejected' ? 'رد' : 'لغو') : 'تأیید',
        at('decided_at'),
        status != 'submitted',
      ),
      ('فاکتور', null, ['invoiced', 'delivered'].contains(status)),
      ('تحویل', at('delivered_at'), status == 'delivered'),
    ];
    return Scaffold(
      appBar: AppBar(
        title: Text(
          'سفارش ${faDigits(o['number'] ?? '')} · ${o['customer_name']}',
        ),
      ),
      body: ListView(
        padding: const EdgeInsets.fromLTRB(16, 8, 16, 24),
        children: [
          Card(
            child: Padding(
              padding: const EdgeInsets.all(14),
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  Row(
                    children: [
                      StatusChip(status),
                      const Spacer(),
                      if (o['invoice_number'] != null)
                        Text(
                          'فاکتور ${faDigits(o['invoice_number'])}',
                          style: const TextStyle(fontSize: 12),
                        ),
                    ],
                  ),
                  const SizedBox(height: 12),
                  Row(
                    children: [
                      for (final (label, date, done) in steps.sublist(
                        0,
                        rejected ? 2 : 4,
                      ))
                        Expanded(
                          child: Column(
                            children: [
                              Icon(
                                done
                                    ? Icons.check_circle_rounded
                                    : Icons.radio_button_unchecked_rounded,
                                size: 20,
                                color: done
                                    ? Theme.of(context).colorScheme.primary
                                    : Theme.of(context).colorScheme.outline,
                              ),
                              const SizedBox(height: 2),
                              Text(
                                label,
                                style: const TextStyle(
                                  fontSize: 11,
                                  fontWeight: FontWeight.w700,
                                ),
                              ),
                              Text(
                                date == null ? '' : jalaliDate(date),
                                style: TextStyle(
                                  fontSize: 10,
                                  color: Theme.of(context)
                                      .colorScheme
                                      .onSurfaceVariant,
                                ),
                              ),
                            ],
                          ),
                        ),
                    ],
                  ),
                  if (o['decision_note'] != null) ...[
                    const SizedBox(height: 8),
                    Text(
                      'توضیح: ${o['decision_note']}',
                      style: const TextStyle(fontSize: 12),
                    ),
                  ],
                ],
              ),
            ),
          ),
          const SizedBox(height: 8),
          Card(
            child: Padding(
              padding: const EdgeInsets.all(14),
              child: Column(
                children: [
                  for (final l in _lines)
                    Padding(
                      padding: const EdgeInsets.symmetric(vertical: 5),
                      child: Row(
                        children: [
                          Expanded(
                            child: Column(
                              crossAxisAlignment: CrossAxisAlignment.start,
                              children: [
                                Text(
                                  l['item_name'] as String,
                                  style: const TextStyle(
                                    fontWeight: FontWeight.w700,
                                  ),
                                ),
                                Text(
                                  '${qty(l['qty'] as String)} ${l['unit_name']} × ${money(dec(l['unit_price'] as String), cur)}'
                                  '${dec(l['promotion_discount'] as String? ?? '0') > Decimal.zero ? ' · تخفیف ${money(dec(l['promotion_discount'] as String), cur)}' : ''}',
                                  style: TextStyle(
                                    fontSize: 12,
                                    color: Theme.of(context)
                                        .colorScheme
                                        .onSurfaceVariant,
                                  ),
                                ),
                              ],
                            ),
                          ),
                          Text(
                            money(dec(l['line_total'] as String), cur),
                            style: const TextStyle(fontWeight: FontWeight.w700),
                          ),
                        ],
                      ),
                    ),
                  const Divider(height: 20),
                  LabelValue(
                    'جمع',
                    money(dec(o['subtotal'] as String), cur, unit: true),
                  ),
                  LabelValue(
                    'تخفیف',
                    money(dec(o['discount_total'] as String), cur, unit: true),
                  ),
                  LabelValue(
                    'مالیات',
                    money(dec(o['tax_total'] as String), cur, unit: true),
                  ),
                  LabelValue(
                    'مبلغ قابل پرداخت',
                    money(dec(o['grand_total'] as String), cur, unit: true),
                    bold: true,
                  ),
                ],
              ),
            ),
          ),
          const SizedBox(height: 12),
          Row(
            children: [
              Expanded(
                child: SizedBox(
                  height: 50,
                  child: OutlinedButton.icon(
                    onPressed: () => showPreInvoice(context, state, order),
                    icon: const Icon(Icons.ios_share_rounded),
                    label: const Text('ارسال برای مشتری'),
                  ),
                ),
              ),
              const SizedBox(width: 10),
              Expanded(
                child: BrandButton(
                  label: 'تکرار این سفارش',
                  onPressed: () => _repeat(context),
                ),
              ),
            ],
          ),
          const SizedBox(height: 8),
          Text(
            'در «تکرار»، قیمت روز را دوباره سرور حساب می‌کند.',
            textAlign: TextAlign.center,
            style: TextStyle(
              fontSize: 12,
              color: Theme.of(context).colorScheme.onSurfaceVariant,
            ),
          ),
        ],
      ),
    );
  }
}

/// A preview of the pre-invoice, then the share sheet with it as a PNG.
Future<void> showPreInvoice(
  BuildContext context,
  AppState state,
  Map<String, dynamic> order,
) {
  final key = GlobalKey();
  return showModalBottomSheet<void>(
    context: context,
    isScrollControlled: true,
    useSafeArea: true,
    builder: (sheet) => GlassPanel(
      strong: true,
      radius: const BorderRadius.vertical(top: Radius.circular(30)),
      padding: EdgeInsets.fromLTRB(
        16,
        16,
        16,
        16 + MediaQuery.paddingOf(sheet).bottom,
      ),
      child: Column(
        mainAxisSize: MainAxisSize.min,
        children: [
          Flexible(
            child: SingleChildScrollView(
              child: RepaintBoundary(
                key: key,
                child: PreInvoice(state: state, order: order),
              ),
            ),
          ),
          const SizedBox(height: 12),
          BrandButton(
            label: 'ارسال (واتس‌اپ، تلگرام، …)',
            onPressed: () async {
              final boundary =
                  key.currentContext!.findRenderObject()!
                      as RenderRepaintBoundary;
              final image = await boundary.toImage(pixelRatio: 3);
              final bytes = await image.toByteData(
                format: ui.ImageByteFormat.png,
              );
              if (bytes == null) return;
              await state.device.shareImage(
                bytes.buffer.asUint8List(),
                'pre-invoice-${order['number'] ?? 'draft'}.png',
                'پیش‌فاکتور ${state.catalog?.organization ?? ''}',
              );
            },
          ),
        ],
      ),
    ),
  );
}

/// The pre-invoice as the customer sees it: white paper, shop name, lines and totals.
class PreInvoice extends StatelessWidget {
  const PreInvoice({super.key, required this.state, required this.order});
  final AppState state;
  final Map<String, dynamic> order;

  @override
  Widget build(BuildContext context) {
    final cur = state.catalog?.currency ?? 'IRT';
    final lines = ((order['lines'] as List?) ?? const [])
        .cast<Map<String, dynamic>>();
    const ink = Color(0xFF1E1B3A);
    const soft = Color(0xFF5B5875);
    TextStyle st([
      double size = 12,
      FontWeight w = FontWeight.w400,
      Color c = ink,
    ]) => TextStyle(
      fontSize: size,
      fontWeight: w,
      color: c,
      fontFamily: 'Vazirmatn',
    );
    return Container(
      color: Colors.white,
      padding: const EdgeInsets.all(18),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.stretch,
        children: [
          Text(
            state.catalog?.organization ?? '',
            textAlign: TextAlign.center,
            style: st(17, FontWeight.w800),
          ),
          Text(
            'پیش‌فاکتور',
            textAlign: TextAlign.center,
            style: st(13, FontWeight.w700, soft),
          ),
          const SizedBox(height: 10),
          Text(
            'مشتری: ${order['customer_name']}',
            style: st(12, FontWeight.w700),
          ),
          Text(
            'سفارش ${faDigits(order['number'] ?? '')} · ${jalaliDateTime(DateTime.parse(order['ordered_at'] as String))}',
            style: st(11, FontWeight.w400, soft),
          ),
          Text(
            'ویزیتور: ${state.catalog?.visitorName ?? ''}',
            style: st(11, FontWeight.w400, soft),
          ),
          const Divider(color: Color(0xFFD6D7EE)),
          for (final l in lines)
            Padding(
              padding: const EdgeInsets.symmetric(vertical: 3),
              child: Row(
                children: [
                  Expanded(
                    child: Text(
                      '${l['item_name']} — ${qty(l['qty'] as String)} ${l['unit_name']}',
                      style: st(12),
                    ),
                  ),
                  Text(
                    money(dec(l['line_total'] as String), cur),
                    style: st(12, FontWeight.w700),
                  ),
                ],
              ),
            ),
          const Divider(color: Color(0xFFD6D7EE)),
          _row('جمع', money(dec(order['subtotal'] as String), cur), st()),
          _row(
            'تخفیف',
            money(dec(order['discount_total'] as String), cur),
            st(),
          ),
          _row('مالیات', money(dec(order['tax_total'] as String), cur), st()),
          _row(
            'قابل پرداخت',
            money(dec(order['grand_total'] as String), cur, unit: true),
            st(14, FontWeight.w800),
          ),
          const SizedBox(height: 8),
          Text(
            'قیمت‌ها با تأیید نهایی و صدور فاکتور قطعی می‌شوند.',
            textAlign: TextAlign.center,
            style: st(10, FontWeight.w400, soft),
          ),
        ],
      ),
    );
  }

  Widget _row(String label, String value, TextStyle style) => Padding(
    padding: const EdgeInsets.symmetric(vertical: 2),
    child: Row(
      children: [
        Expanded(child: Text(label, style: style)),
        Text(value, style: style),
      ],
    ),
  );
}
