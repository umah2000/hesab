import 'package:flutter/material.dart';

import '../format.dart';
import '../models.dart';
import '../state.dart';
import 'glass.dart';
import 'jalali_picker.dart';
import 'parts.dart';
import 'widgets.dart';

/// Money taken from a customer: cash, cheque or card-to-card. A request until the
/// accountant approves it; until then the customer's balance does not change (ADR-0026).
class CollectionScreen extends StatefulWidget {
  const CollectionScreen({super.key, required this.state, this.customer});
  final AppState state;
  final Customer? customer;

  @override
  State<CollectionScreen> createState() => _CollectionScreenState();
}

class _CollectionScreenState extends State<CollectionScreen> {
  String _method = 'cash';
  Customer? _customer;
  final _amount = TextEditingController();
  final _note = TextEditingController();
  final _reference = TextEditingController();
  final _number = TextEditingController();
  final _sayad = TextEditingController();
  final _bank = TextEditingController();
  final _drawer = TextEditingController();
  DateTime? _due;
  String? _error;
  bool _busy = false;

  AppState get _s => widget.state;

  @override
  void initState() {
    super.initState();
    _customer = widget.customer;
  }

  @override
  void dispose() {
    for (final c in [
      _amount,
      _note,
      _reference,
      _number,
      _sayad,
      _bank,
      _drawer,
    ]) {
      c.dispose();
    }
    super.dispose();
  }

  Future<void> _save() async {
    final cur = _s.catalog?.currency ?? 'IRT';
    final rials = rialsFromInput(_amount.text, cur);
    String? err;
    if (_customer == null) err = 'مشتری را انتخاب کنید';
    if (rials == null) err ??= 'مبلغ را درست وارد کنید';
    if (_method == 'cheque' && (_number.text.trim().isEmpty || _due == null)) {
      err ??= 'شماره و تاریخ سررسید چک را وارد کنید';
    }
    final sayad = enDigits(_sayad.text.trim());
    if (_method == 'cheque' &&
        sayad.isNotEmpty &&
        !RegExp(r'^\d{16}$').hasMatch(sayad)) {
      err ??= 'شناسه‌ی صیادی ۱۶ رقم است';
    }
    if (_method == 'transfer' && _reference.text.trim().isEmpty) {
      err ??= 'شماره‌ی پیگیری کارت‌به‌کارت را وارد کنید';
    }
    if (err != null) {
      setState(() => _error = err);
      return;
    }
    setState(() {
      _busy = true;
      _error = null;
    });
    final messenger = ScaffoldMessenger.of(context);
    final nav = Navigator.of(context);
    await _s.addCollection({
      'customer_id': _customer!.id,
      'method': _method,
      'amount': rials.toString(),
      if (_note.text.trim().isNotEmpty) 'note': _note.text.trim(),
      if (_method == 'transfer') 'reference': enDigits(_reference.text.trim()),
      if (_method == 'cheque') ...{
        'cheque_number': enDigits(_number.text.trim()),
        if (sayad.isNotEmpty) 'cheque_sayad_id': sayad,
        if (_bank.text.trim().isNotEmpty) 'cheque_bank': _bank.text.trim(),
        if (_drawer.text.trim().isNotEmpty)
          'cheque_drawer': _drawer.text.trim(),
        'cheque_due_date': _due!.toIso8601String().substring(0, 10),
      },
    });
    messenger.showSnackBar(
      SnackBar(
        content: Text(
          _s.online
              ? 'وصول ثبت شد و برای تأیید حسابداری ارسال می‌شود'
              : 'وصول روی گوشی ثبت شد؛ با وصل شدن اینترنت ارسال می‌شود',
        ),
      ),
    );
    nav.pop();
  }

  Future<void> _pickCustomer() async {
    final cat = _s.catalog;
    if (cat == null) return;
    final picked = await showModalBottomSheet<Customer>(
      context: context,
      showDragHandle: true,
      builder: (_) => ListView(
        children: [
          for (final c in cat.customers)
            ListTile(
              title: Text(c.name),
              subtitle: Text(money(c.balance, cat.currency, unit: true)),
              onTap: () => Navigator.pop(context, c),
            ),
        ],
      ),
    );
    if (picked != null) setState(() => _customer = picked);
  }

  @override
  Widget build(BuildContext context) {
    final cur = _s.catalog?.currency ?? 'IRT';
    final c = _customer;
    final mine = _s.collections;
    final queued = _s.outbox
        .where((e) => e.kind == 'collection' && e.status != 'sent')
        .toList();
    return Scaffold(
      appBar: AppBar(
        title: Text(c == null ? 'وصول وجه' : 'وصول وجه · ${c.name}'),
      ),
      body: ListView(
        padding: const EdgeInsets.fromLTRB(16, 8, 16, 24),
        children: [
          SegmentedButton<String>(
            segments: [
              for (final m in collectionMethodLabel.entries)
                ButtonSegment(value: m.key, label: Text(m.value)),
            ],
            selected: {_method},
            onSelectionChanged: (v) => setState(() => _method = v.first),
          ),
          const SizedBox(height: 12),
          Card(
            child: Padding(
              padding: const EdgeInsets.all(14),
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.stretch,
                children: [
                  if (widget.customer == null) ...[
                    OutlinedButton.icon(
                      onPressed: _pickCustomer,
                      icon: const Icon(Icons.person_search_rounded),
                      label: Text(c?.name ?? 'انتخاب مشتری'),
                    ),
                    const SizedBox(height: 10),
                  ],
                  TextField(
                    controller: _amount,
                    keyboardType: const TextInputType.numberWithOptions(
                      decimal: true,
                    ),
                    textDirection: TextDirection.ltr,
                    decoration: InputDecoration(
                      labelText: 'مبلغ (${cur == 'IRT' ? 'تومان' : 'ریال'})',
                      helperText: c == null
                          ? null
                          : 'مانده‌ی مشتری: ${money(c.balance, cur, unit: true)}',
                    ),
                  ),
                  if (_method == 'transfer') ...[
                    const SizedBox(height: 10),
                    TextField(
                      controller: _reference,
                      textDirection: TextDirection.ltr,
                      decoration: const InputDecoration(
                        labelText: 'شماره‌ی پیگیری',
                      ),
                    ),
                  ],
                  if (_method == 'cheque') ...[
                    const SizedBox(height: 10),
                    TextField(
                      controller: _number,
                      keyboardType: TextInputType.number,
                      textDirection: TextDirection.ltr,
                      decoration: const InputDecoration(
                        labelText: 'شماره‌ی چک',
                      ),
                    ),
                    const SizedBox(height: 10),
                    TextField(
                      controller: _sayad,
                      keyboardType: TextInputType.number,
                      textDirection: TextDirection.ltr,
                      decoration: const InputDecoration(
                        labelText: 'شناسه‌ی صیادی (۱۶ رقم، اختیاری)',
                      ),
                    ),
                    const SizedBox(height: 10),
                    TextField(
                      controller: _bank,
                      decoration: const InputDecoration(labelText: 'بانک'),
                    ),
                    const SizedBox(height: 10),
                    TextField(
                      controller: _drawer,
                      decoration: const InputDecoration(labelText: 'صادرکننده'),
                    ),
                    const SizedBox(height: 10),
                    OutlinedButton.icon(
                      onPressed: () async {
                        final d = await pickJalaliDate(
                          context,
                          initial:
                              _due ??
                              DateTime.now().add(const Duration(days: 30)),
                        );
                        if (d != null) setState(() => _due = d);
                      },
                      icon: const Icon(Icons.event_rounded),
                      label: Text(
                        _due == null
                            ? 'تاریخ سررسید'
                            : 'سررسید ${jalaliDate(_due!)}',
                      ),
                    ),
                  ],
                  const SizedBox(height: 10),
                  TextField(
                    controller: _note,
                    decoration: const InputDecoration(
                      labelText: 'توضیح (مثلاً بابت فاکتور ۴۱)',
                    ),
                  ),
                  const SizedBox(height: 10),
                  Row(
                    children: [
                      Expanded(
                        child: Text(
                          'ثبت مکان هنگام وصول',
                          style: TextStyle(
                            fontSize: 13,
                            color: Theme.of(context)
                                .colorScheme
                                .onSurfaceVariant,
                          ),
                        ),
                      ),
                      Switch(
                        value: _s.gps,
                        onChanged: (v) =>
                            _s.setGps(v).then((_) => setState(() {})),
                      ),
                    ],
                  ),
                  if (_error != null)
                    Padding(
                      padding: const EdgeInsets.only(top: 6),
                      child: Text(
                        _error!,
                        style: TextStyle(
                          color: Theme.of(context).colorScheme.error,
                        ),
                      ),
                    ),
                ],
              ),
            ),
          ),
          const SizedBox(height: 12),
          BrandButton(label: 'ثبت وصول', busy: _busy, onPressed: _save),
          const SizedBox(height: 6),
          Text(
            'مبلغ تا تأیید حسابدار در مانده‌ی مشتری اثر ندارد.',
            textAlign: TextAlign.center,
            style: TextStyle(
              fontSize: 12,
              color: Theme.of(context).colorScheme.onSurfaceVariant,
            ),
          ),
          if (queued.isNotEmpty || mine.isNotEmpty)
            const SectionTitle('وصول‌های من'),
          for (final e in queued)
            _CollectionTile(
              title:
                  '${money(dec(e.payload['amount'] as String), cur)} · ${collectionMethodLabel[e.payload['method']]}',
              subtitle:
                  '${_s.catalog?.customer(e.payload['customer_id'] as String)?.name ?? ''} · ${jalaliDateTime(e.createdAt)}',
              pill: StatusChip(e.status),
            ),
          for (final m in mine.take(30))
            _CollectionTile(
              title:
                  '${money(dec(m['amount'] as String), cur)} · ${collectionMethodLabel[m['method']]}'
                  '${m['cheque_number'] != null ? ' ${faDigits(m['cheque_number'])}' : ''}',
              subtitle:
                  '${m['customer_name']} · ${jalaliDateTime(DateTime.parse(m['collected_at'] as String))}'
                  '${m['decision_note'] != null ? ' · ${m['decision_note']}' : ''}',
              pill: _RequestPill(
                status: m['status'] as String,
                extra: m['treasury_document_number'] == null
                    ? null
                    : 'سند ${faDigits(m['treasury_document_number'])}',
              ),
            ),
        ],
      ),
    );
  }
}

class _CollectionTile extends StatelessWidget {
  const _CollectionTile({
    required this.title,
    required this.subtitle,
    required this.pill,
  });
  final String title;
  final String subtitle;
  final Widget pill;

  @override
  Widget build(BuildContext context) => Padding(
    padding: const EdgeInsets.only(bottom: 8),
    child: Card(
      child: Padding(
        padding: const EdgeInsets.all(12),
        child: Row(
          children: [
            Expanded(
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  Text(
                    title,
                    style: const TextStyle(fontWeight: FontWeight.w700),
                  ),
                  Text(
                    subtitle,
                    style: TextStyle(
                      fontSize: 12,
                      color: Theme.of(context).colorScheme.onSurfaceVariant,
                    ),
                  ),
                ],
              ),
            ),
            pill,
          ],
        ),
      ),
    ),
  );
}

class _RequestPill extends StatelessWidget {
  const _RequestPill({required this.status, this.extra});
  final String status;
  final String? extra;

  @override
  Widget build(BuildContext context) {
    final label =
        '${requestStatusLabel[status] ?? status}${extra == null ? '' : ' · $extra'}';
    return switch (status) {
      'approved' => StatusPill(
        icon: Icons.check_rounded,
        label: label,
        color: StatusPill.ok,
      ),
      'rejected' => StatusPill(
        icon: Icons.close_rounded,
        label: label,
        color: StatusPill.danger,
      ),
      _ => StatusPill(
        icon: Icons.hourglass_top_rounded,
        label: label,
        color: StatusPill.warning,
      ),
    };
  }
}

/// The same pill for new-customer requests.
class RequestStatusPill extends StatelessWidget {
  const RequestStatusPill({super.key, required this.status});
  final String status;

  @override
  Widget build(BuildContext context) => _RequestPill(status: status);
}
