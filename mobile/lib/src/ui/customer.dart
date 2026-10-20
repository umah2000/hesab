import 'package:flutter/material.dart';

import '../format.dart';
import '../models.dart';
import '../state.dart';
import 'order.dart';
import 'widgets.dart';

class CustomerScreen extends StatelessWidget {
  const CustomerScreen({
    super.key,
    required this.state,
    required this.customer,
  });
  final AppState state;
  final Customer customer;

  @override
  Widget build(BuildContext context) {
    final c = customer;
    final cur = state.catalog?.currency ?? 'IRT';
    return Scaffold(
      appBar: AppBar(title: Text(c.name)),
      body: ListView(
        padding: const EdgeInsets.all(16),
        children: [
          Card(
            child: Padding(
              padding: const EdgeInsets.all(16),
              child: Column(
                children: [
                  LabelValue('کد', faDigits(c.code)),
                  if (c.phone != null) LabelValue('تلفن', faDigits(c.phone!)),
                  if (c.address != null) LabelValue('نشانی', c.address!),
                  LabelValue(
                    'روز بازدید',
                    c.visitWeekday == null
                        ? 'بدون روز ثابت'
                        : weekdayNames[c.visitWeekday!],
                  ),
                  const Divider(height: 24),
                  LabelValue(
                    'مانده بدهی',
                    money(c.balance, cur, unit: true),
                    bold: true,
                  ),
                  LabelValue(
                    'سقف اعتبار',
                    c.creditLimit == null
                        ? 'فروش نسیه تعریف نشده'
                        : money(c.creditLimit!, cur, unit: true),
                  ),
                  if (c.available != null)
                    LabelValue(
                      'اعتبار باقی‌مانده',
                      money(c.available!, cur, unit: true),
                      bold: true,
                    ),
                ],
              ),
            ),
          ),
          const SizedBox(height: 8),
          Text(
            'مانده و اعتبار مربوط به آخرین هماهنگی با سرور است.',
            style: TextStyle(
              fontSize: 12,
              color: Theme.of(context).colorScheme.outline,
            ),
          ),
          const SizedBox(height: 20),
          FilledButton.icon(
            style: FilledButton.styleFrom(
              minimumSize: const Size.fromHeight(52),
            ),
            onPressed: () => Navigator.of(context).push(
              MaterialPageRoute(
                builder: (_) => OrderScreen(state: state, customer: c),
              ),
            ),
            icon: const Icon(Icons.add_shopping_cart_rounded),
            label: const Text('سفارش جدید'),
          ),
          const SizedBox(height: 10),
          OutlinedButton.icon(
            style: OutlinedButton.styleFrom(
              minimumSize: const Size.fromHeight(48),
            ),
            onPressed: () => _visit(context),
            icon: const Icon(Icons.event_available_rounded),
            label: const Text('ثبت بازدید بدون سفارش'),
          ),
        ],
      ),
    );
  }

  Future<void> _visit(BuildContext context) async {
    var outcome = 'no_order';
    final note = TextEditingController();
    final ok = await showDialog<bool>(
      context: context,
      builder: (c) => StatefulBuilder(
        builder: (c, set) => AlertDialog(
          title: const Text('نتیجه‌ی بازدید'),
          content: Column(
            mainAxisSize: MainAxisSize.min,
            children: [
              RadioGroup<String>(
                groupValue: outcome,
                onChanged: (v) => set(() => outcome = v!),
                child: Column(
                  children: [
                    for (final o in ['no_order', 'closed', 'absent'])
                      RadioListTile<String>(
                        value: o,
                        title: Text(visitOutcomeLabel[o]!),
                      ),
                  ],
                ),
              ),
              TextField(
                controller: note,
                decoration: const InputDecoration(labelText: 'توضیح'),
              ),
            ],
          ),
          actions: [
            TextButton(
              onPressed: () => Navigator.pop(c, false),
              child: const Text('انصراف'),
            ),
            FilledButton(
              onPressed: () => Navigator.pop(c, true),
              child: const Text('ثبت'),
            ),
          ],
        ),
      ),
    );
    if (ok != true) return;
    await state.logVisit(customer, outcome, note.text);
    if (context.mounted) {
      ScaffoldMessenger.of(context)
          .showSnackBar(const SnackBar(content: Text('بازدید ثبت شد')));
    }
  }
}
