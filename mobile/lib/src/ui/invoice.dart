import 'package:flutter/material.dart';

import '../api.dart';
import '../format.dart';
import '../state.dart';
import 'parts.dart';
import 'widgets.dart';

/// One final invoice of a customer, view only (whoever sold it; ADR-0026).
class InvoiceScreen extends StatefulWidget {
  const InvoiceScreen({
    super.key,
    required this.state,
    required this.invoiceId,
    required this.title,
  });
  final AppState state;
  final String invoiceId;
  final String title;

  @override
  State<InvoiceScreen> createState() => _InvoiceScreenState();
}

class _InvoiceScreenState extends State<InvoiceScreen> {
  late final Future<(Map<String, dynamic>?, bool)> _load = widget.state.invoice(
    widget.invoiceId,
  );

  @override
  Widget build(BuildContext context) {
    final cur = widget.state.catalog?.currency ?? 'IRT';
    return Scaffold(
      appBar: AppBar(title: Text(widget.title)),
      body: FutureBuilder(
        future: _load,
        builder: (context, snap) {
          if (snap.hasError) {
            final e = snap.error;
            return EmptyView(
              icon: Icons.error_outline_rounded,
              title: e is ApiException ? e.message : 'فاکتور دریافت نشد',
            );
          }
          if (!snap.hasData) {
            return const Center(child: CircularProgressIndicator());
          }
          final (inv, fresh) = snap.data!;
          if (inv == null) {
            return const EmptyView(
              icon: Icons.cloud_off_rounded,
              title: 'بدون اینترنت',
              detail: 'این فاکتور هنوز روی گوشی ذخیره نشده است.',
            );
          }
          final lines = (inv['lines'] as List).cast<Map<String, dynamic>>();
          final soft = Theme.of(context).colorScheme.onSurfaceVariant;
          return ListView(
            padding: const EdgeInsets.fromLTRB(16, 8, 16, 24),
            children: [
              OfflineNote(fresh: fresh),
              Card(
                child: Padding(
                  padding: const EdgeInsets.all(14),
                  child: Row(
                    children: [
                      Expanded(
                        child: Text(
                          '${inv['kind'] == 'return' ? 'برگشت از فروش' : 'فاکتور'} ${faDigits(inv['number'] ?? '')} · ${jalaliDay(inv['document_date'] as String)}',
                          style: const TextStyle(fontWeight: FontWeight.w700),
                        ),
                      ),
                      ChannelPill(
                        channel: inv['channel'] as String,
                        visitorName: inv['visitor_name'] as String?,
                      ),
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
                      for (final l in lines)
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
                                      '${qty(l['qty'] as String)} ${l['unit_name']} × ${money(dec(l['unit_price'] as String), cur)}',
                                      style: TextStyle(
                                        fontSize: 12,
                                        color: soft,
                                      ),
                                    ),
                                  ],
                                ),
                              ),
                              Text(
                                money(dec(l['line_total'] as String), cur),
                                style: const TextStyle(
                                  fontWeight: FontWeight.w700,
                                ),
                              ),
                            ],
                          ),
                        ),
                      const Divider(height: 20),
                      LabelValue(
                        'جمع',
                        money(dec(inv['subtotal'] as String), cur, unit: true),
                      ),
                      LabelValue(
                        'تخفیف',
                        money(
                          dec(inv['discount_total'] as String),
                          cur,
                          unit: true,
                        ),
                      ),
                      LabelValue(
                        'مالیات',
                        money(dec(inv['tax_total'] as String), cur, unit: true),
                      ),
                      LabelValue(
                        'مبلغ کل',
                        money(
                          dec(inv['grand_total'] as String),
                          cur,
                          unit: true,
                        ),
                        bold: true,
                      ),
                    ],
                  ),
                ),
              ),
              const SizedBox(height: 6),
              Text(
                'فقط برای مشاهده؛ فاکتور حضوری یا ویزیتور دیگر در گزارش شما حساب نمی‌شود.',
                textAlign: TextAlign.center,
                style: TextStyle(fontSize: 12, color: soft),
              ),
            ],
          );
        },
      ),
    );
  }
}
