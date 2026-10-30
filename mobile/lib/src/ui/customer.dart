import 'package:flutter/material.dart';

import '../api.dart';
import '../format.dart';
import '../models.dart';
import '../state.dart';
import 'collection.dart';
import 'invoice.dart';
import 'order.dart';
import 'parts.dart';
import 'widgets.dart';

/// A customer: quick actions, the account, and every recent invoice whoever sold it
/// (view only, labelled by channel; ADR-0026).
class CustomerScreen extends StatefulWidget {
  const CustomerScreen({
    super.key,
    required this.state,
    required this.customer,
  });
  final AppState state;
  final Customer customer;

  @override
  State<CustomerScreen> createState() => _CustomerScreenState();
}

class _CustomerScreenState extends State<CustomerScreen> {
  late Future<(Map<String, dynamic>?, bool)> _account;
  late Future<(Map<String, dynamic>?, bool)> _history;

  AppState get _s => widget.state;
  Customer get _c =>
      _s.catalog?.customer(widget.customer.id) ?? widget.customer;

  @override
  void initState() {
    super.initState();
    _load();
  }

  void _load() {
    _account = _s.customerAccount(widget.customer.id);
    _history = _s.customerHistory(widget.customer.id);
  }

  void _say(String text) =>
      ScaffoldMessenger.of(context).showSnackBar(SnackBar(content: Text(text)));

  Future<void> _navigate() async {
    final c = _c;
    if (!c.located) {
      _say('مکان این مشتری ثبت نشده است؛ کنار مغازه «ثبت مکان» را بزنید');
      return;
    }
    final ok = await _s.device.openMap(
      c.latitude!.toDouble(),
      c.longitude!.toDouble(),
      c.name,
    );
    if (!ok) _say('برنامه‌ی نقشه روی گوشی پیدا نشد');
  }

  Future<void> _locate() async {
    final here = await _s.device.position();
    if (!mounted) return;
    if (here == null) {
      _say('مکان گوشی در دسترس نیست؛ GPS و اجازه‌ی مکان را روشن کنید');
      return;
    }
    final ok = await showDialog<bool>(
      context: context,
      builder: (c) => AlertDialog(
        title: const Text('ثبت مکان مغازه'),
        content: Text(
          'مکان فعلی شما (${faDigits(here.lat)}، ${faDigits(here.lon)}) به‌عنوان مکان «${_c.name}» ثبت شود؟',
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
    );
    if (ok != true) return;
    try {
      await _s.setCustomerLocation(_c, here);
      _say('مکان مغازه ثبت شد');
    } on NetworkException {
      _say('ثبت مکان به اینترنت نیاز دارد');
    } on ApiException catch (e) {
      _say(e.message);
    }
  }

  @override
  Widget build(BuildContext context) {
    final c = _c;
    final cur = _s.catalog?.currency ?? 'IRT';
    final soft = Theme.of(context).colorScheme.onSurfaceVariant;
    return Scaffold(
      appBar: AppBar(title: Text(c.name)),
      body: RefreshIndicator(
        onRefresh: () async {
          setState(_load);
          await Future.wait([_account, _history]);
        },
        child: ListView(
          padding: const EdgeInsets.fromLTRB(16, 8, 16, 24),
          children: [
            Row(
              children: [
                _Action(
                  icon: Icons.add_shopping_cart_rounded,
                  label: 'سفارش',
                  onTap: () => Navigator.of(context).push(
                    MaterialPageRoute(
                      builder: (_) => OrderScreen(state: _s, customer: c),
                    ),
                  ),
                ),
                _Action(
                  icon: Icons.payments_rounded,
                  label: 'وصول',
                  onTap: () => Navigator.of(context).push(
                    MaterialPageRoute(
                      builder: (_) => CollectionScreen(state: _s, customer: c),
                    ),
                  ),
                ),
                _Action(
                  icon: Icons.directions_rounded,
                  label: 'مسیریابی',
                  onTap: _navigate,
                ),
                _Action(
                  icon: Icons.add_location_alt_rounded,
                  label: 'ثبت مکان',
                  onTap: _locate,
                ),
              ],
            ),
            const SizedBox(height: 10),
            Card(
              child: Padding(
                padding: const EdgeInsets.all(14),
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
                  ],
                ),
              ),
            ),
            const SizedBox(height: 8),
            FutureBuilder(
              future: _account,
              builder: (context, snap) =>
                  _AccountCard(customer: c, currency: cur, data: snap.data),
            ),
            FutureBuilder(
              future: _history,
              builder: (context, snap) {
                if (snap.hasError) {
                  final e = snap.error;
                  return Padding(
                    padding: const EdgeInsets.all(12),
                    child: Text(
                      e is ApiException ? e.message : 'سابقه‌ی خرید دریافت نشد',
                    ),
                  );
                }
                if (!snap.hasData) {
                  return const Padding(
                    padding: EdgeInsets.all(24),
                    child: Center(child: CircularProgressIndicator()),
                  );
                }
                final (h, fresh) = snap.data!;
                if (h == null) {
                  return const Padding(
                    padding: EdgeInsets.all(12),
                    child: Text(
                      'سابقه‌ی خرید با اتصال به اینترنت نمایش داده می‌شود.',
                    ),
                  );
                }
                final invoices = (h['invoices'] as List)
                    .cast<Map<String, dynamic>>();
                final freq = (h['frequent_items'] as List)
                    .cast<Map<String, dynamic>>();
                return Column(
                  crossAxisAlignment: CrossAxisAlignment.stretch,
                  children: [
                    const SectionTitle('خریدهای اخیر', trailing: 'فقط نمایش'),
                    OfflineNote(fresh: fresh),
                    if (invoices.isEmpty)
                      Text(
                        'در شش ماه اخیر فاکتوری ندارد.',
                        style: TextStyle(color: soft),
                      ),
                    for (final i in invoices.take(15))
                      Padding(
                        padding: const EdgeInsets.only(bottom: 8),
                        child: Card(
                          clipBehavior: Clip.antiAlias,
                          child: InkWell(
                            onTap: () => Navigator.of(context).push(
                              MaterialPageRoute(
                                builder: (_) => InvoiceScreen(
                                  state: _s,
                                  invoiceId: i['id'] as String,
                                  title:
                                      'فاکتور ${faDigits(i['number'] ?? '')}',
                                ),
                              ),
                            ),
                            child: Padding(
                              padding: const EdgeInsets.all(12),
                              child: Row(
                                children: [
                                  Expanded(
                                    child: Column(
                                      crossAxisAlignment:
                                          CrossAxisAlignment.start,
                                      children: [
                                        Text(
                                          '${i['kind'] == 'return' ? 'برگشت' : 'فاکتور'} ${faDigits(i['number'] ?? '')} · ${jalaliDay(i['document_date'] as String)}',
                                          style: const TextStyle(
                                            fontWeight: FontWeight.w700,
                                          ),
                                        ),
                                        Text(
                                          '${faDigits(i['line_count'])} قلم',
                                          style: TextStyle(
                                            fontSize: 12,
                                            color: soft,
                                          ),
                                        ),
                                      ],
                                    ),
                                  ),
                                  Column(
                                    crossAxisAlignment: CrossAxisAlignment.end,
                                    children: [
                                      ChannelPill(
                                        channel: i['channel'] as String,
                                        visitorName:
                                            i['visitor_name'] as String?,
                                      ),
                                      const SizedBox(height: 4),
                                      Text(
                                        money(
                                          dec(i['grand_total'] as String),
                                          cur,
                                        ),
                                        style: const TextStyle(
                                          fontWeight: FontWeight.w800,
                                        ),
                                      ),
                                    ],
                                  ),
                                ],
                              ),
                            ),
                          ),
                        ),
                      ),
                    if (freq.isNotEmpty) ...[
                      const SectionTitle('پرتکرارها'),
                      Card(
                        child: Padding(
                          padding: const EdgeInsets.all(12),
                          child: Text(
                            freq
                                .map(
                                  (f) =>
                                      '${f['item_name']} (${faDigits(f['times'])} بار)',
                                )
                                .join(' · '),
                            style: const TextStyle(fontSize: 13),
                          ),
                        ),
                      ),
                    ],
                  ],
                );
              },
            ),
            const SizedBox(height: 14),
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
          title: const Text('چرا سفارش نگرفتید؟'),
          content: SingleChildScrollView(
            child: Column(
              mainAxisSize: MainAxisSize.min,
              children: [
                RadioGroup<String>(
                  groupValue: outcome,
                  onChanged: (v) => set(() => outcome = v!),
                  child: Column(
                    children: [
                      for (final o in noOrderOutcomes)
                        RadioListTile<String>(
                          value: o,
                          dense: true,
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
    await _s.logVisit(_c, outcome, note.text);
    if (context.mounted) {
      ScaffoldMessenger.of(context)
          .showSnackBar(const SnackBar(content: Text('بازدید ثبت شد')));
    }
  }
}

class _Action extends StatelessWidget {
  const _Action({required this.icon, required this.label, required this.onTap});
  final IconData icon;
  final String label;
  final VoidCallback onTap;

  @override
  Widget build(BuildContext context) {
    final p = Theme.of(context).colorScheme.primary;
    return Expanded(
      child: Padding(
        padding: const EdgeInsets.symmetric(horizontal: 3),
        child: Card(
          clipBehavior: Clip.antiAlias,
          child: InkWell(
            onTap: onTap,
            child: Padding(
              padding: const EdgeInsets.symmetric(vertical: 10),
              child: Column(
                children: [
                  Icon(icon, color: p),
                  const SizedBox(height: 4),
                  Text(
                    label,
                    style: TextStyle(
                      fontSize: 11.5,
                      fontWeight: FontWeight.w700,
                      color: p,
                    ),
                  ),
                ],
              ),
            ),
          ),
        ),
      ),
    );
  }
}

class _AccountCard extends StatelessWidget {
  const _AccountCard({
    required this.customer,
    required this.currency,
    required this.data,
  });
  final Customer customer;
  final String currency;
  final (Map<String, dynamic>?, bool)? data;

  @override
  Widget build(BuildContext context) {
    final a = data?.$1;
    final c = customer;
    final balance = a == null ? c.balance : dec(a['balance'] as String);
    final limit = a == null
        ? c.creditLimit
        : (a['credit_limit'] == null ? null : dec(a['credit_limit'] as String));
    final unlimited = a == null
        ? c.creditUnlimited
        : a['credit_unlimited'] as bool;
    final available = a == null
        ? c.available
        : (a['available'] == null ? null : dec(a['available'] as String));
    final cheques = ((a?['open_cheques'] as List?) ?? const [])
        .cast<Map<String, dynamic>>();
    final pending = a == null ? null : dec(a['pending_collections'] as String);
    return Card(
      child: Padding(
        padding: const EdgeInsets.all(14),
        child: Column(
          children: [
            if (data != null && !data!.$2) const OfflineNote(fresh: false),
            LabelValue(
              'مانده‌ی حساب',
              money(balance, currency, unit: true),
              bold: true,
            ),
            LabelValue(
              'سقف اعتبار',
              unlimited
                  ? 'نامحدود'
                  : limit == null
                  ? 'فروش نسیه تعریف نشده'
                  : money(limit, currency, unit: true),
            ),
            if (available != null)
              LabelValue(
                'اعتبار باقی‌مانده',
                money(available, currency, unit: true),
              ),
            if (pending != null && pending > dec('0'))
              LabelValue(
                'وصول در انتظار تأیید',
                money(pending, currency, unit: true),
              ),
            for (final ch in cheques)
              LabelValue(
                'چک ${faDigits(ch['number'])}',
                '${money(dec(ch['amount'] as String), currency)} · سررسید ${jalaliDay(ch['due_date'] as String)}',
              ),
          ],
        ),
      ),
    );
  }
}
