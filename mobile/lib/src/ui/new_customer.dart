import 'package:flutter/material.dart';

import '../device.dart';
import '../format.dart';
import '../models.dart';
import '../state.dart';
import 'collection.dart';
import 'glass.dart';
import 'parts.dart';
import 'widgets.dart';

/// A shop the visitor found: a request the back office approves into a customer
/// assigned to this visitor (ADR-0026).
class NewCustomerScreen extends StatefulWidget {
  const NewCustomerScreen({super.key, required this.state});
  final AppState state;

  @override
  State<NewCustomerScreen> createState() => _NewCustomerScreenState();
}

class _NewCustomerScreenState extends State<NewCustomerScreen> {
  final _name = TextEditingController();
  final _owner = TextEditingController();
  final _mobile = TextEditingController();
  final _phone = TextEditingController();
  final _city = TextEditingController();
  final _address = TextEditingController();
  final _national = TextEditingController();
  final _economic = TextEditingController();
  final _note = TextEditingController();
  int? _weekday;
  GeoPoint? _at;
  bool _locating = false;
  String? _error;
  bool _busy = false;

  @override
  void dispose() {
    for (final c in [
      _name,
      _owner,
      _mobile,
      _phone,
      _city,
      _address,
      _national,
      _economic,
      _note,
    ]) {
      c.dispose();
    }
    super.dispose();
  }

  Future<void> _locate() async {
    setState(() => _locating = true);
    final p = await widget.state.device.position();
    if (!mounted) return;
    setState(() {
      _locating = false;
      _at = p;
      if (p == null) {
        _error = 'مکان گوشی در دسترس نیست؛ GPS و اجازه‌ی مکان را روشن کنید';
      }
    });
  }

  Future<void> _save() async {
    String digits(TextEditingController c) => enDigits(c.text.trim());
    String? err;
    if (_name.text.trim().length < 2) err = 'نام فروشگاه را وارد کنید';
    if (alreadyACustomer(widget.state.catalog, _name.text)) {
      err ??= 'مشتری‌ای با همین نام در فهرست شما هست';
    }
    final mobile = digits(_mobile);
    if (mobile.isNotEmpty && !RegExp(r'^09\d{9}$').hasMatch(mobile)) {
      err ??= 'موبایل باید ۱۱ رقم و با ۰۹ شروع شود';
    }
    final national = digits(_national);
    if (national.isNotEmpty && !RegExp(r'^\d{10,11}$').hasMatch(national)) {
      err ??= 'کد ملی ۱۰ رقم و شناسه‌ی ملی ۱۱ رقم است';
    }
    final economic = digits(_economic);
    if (economic.isNotEmpty && !RegExp(r'^\d{10,16}$').hasMatch(economic)) {
      err ??= 'کد اقتصادی ۱۰ تا ۱۶ رقم است';
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
    String? text(TextEditingController c) =>
        c.text.trim().isEmpty ? null : c.text.trim();
    await widget.state.addCustomerRequest({
      'name': _name.text.trim(),
      'owner_name': ?text(_owner),
      if (mobile.isNotEmpty) 'mobile': mobile,
      if (digits(_phone).isNotEmpty) 'phone': digits(_phone),
      'city': ?text(_city),
      'address': ?text(_address),
      if (national.isNotEmpty) 'national_id': national,
      if (economic.isNotEmpty) 'economic_code': economic,
      'visit_weekday': ?_weekday,
      'note': ?text(_note),
    }, at: _at);
    messenger.showSnackBar(
      const SnackBar(
        content: Text(
          'درخواست ثبت شد؛ پس از تأیید مدیر به فهرست مشتریان شما اضافه می‌شود',
        ),
      ),
    );
    nav.pop();
  }

  @override
  Widget build(BuildContext context) {
    final s = widget.state;
    final queued = s.outbox
        .where((e) => e.kind == 'customer_request' && e.status != 'sent')
        .toList();
    Widget field(
      TextEditingController c,
      String label, {
      bool ltr = false,
      TextInputType? type,
    }) => Padding(
      padding: const EdgeInsets.only(bottom: 10),
      child: TextField(
        controller: c,
        keyboardType: type,
        textDirection: ltr ? TextDirection.ltr : null,
        decoration: InputDecoration(labelText: label),
      ),
    );
    return Scaffold(
      appBar: AppBar(title: const Text('درخواست مشتری جدید')),
      body: ListView(
        padding: const EdgeInsets.fromLTRB(16, 8, 16, 24),
        children: [
          Card(
            child: Padding(
              padding: const EdgeInsets.all(14),
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.stretch,
                children: [
                  field(_name, 'نام فروشگاه'),
                  field(_owner, 'نام مالک'),
                  field(
                    _mobile,
                    'موبایل',
                    ltr: true,
                    type: TextInputType.phone,
                  ),
                  field(
                    _phone,
                    'تلفن ثابت (اختیاری)',
                    ltr: true,
                    type: TextInputType.phone,
                  ),
                  field(_city, 'شهر'),
                  field(_address, 'نشانی'),
                  field(
                    _national,
                    'کد یا شناسه‌ی ملی (اختیاری)',
                    ltr: true,
                    type: TextInputType.number,
                  ),
                  field(
                    _economic,
                    'کد اقتصادی (اختیاری)',
                    ltr: true,
                    type: TextInputType.number,
                  ),
                  DropdownButtonFormField<int?>(
                    initialValue: _weekday,
                    decoration: const InputDecoration(
                      labelText: 'روز بازدید پیشنهادی',
                    ),
                    items: [
                      const DropdownMenuItem(
                        value: null,
                        child: Text('بدون روز ثابت'),
                      ),
                      for (final (i, n) in weekdayNames.indexed)
                        DropdownMenuItem(value: i, child: Text(n)),
                    ],
                    onChanged: (v) => setState(() => _weekday = v),
                  ),
                  const SizedBox(height: 10),
                  field(_note, 'توضیح'),
                  Row(
                    children: [
                      Expanded(
                        child: _at == null
                            ? Text(
                                'مکان مغازه (برای مسیریابی)',
                                style: TextStyle(
                                  fontSize: 13,
                                  color: Theme.of(context)
                                      .colorScheme
                                      .onSurfaceVariant,
                                ),
                              )
                            : Align(
                                alignment: AlignmentDirectional.centerStart,
                                child: StatusPill(
                                  icon: Icons.place_rounded,
                                  label:
                                      'ثبت شد · ${faDigits(_at!.lat)}، ${faDigits(_at!.lon)}',
                                  color: StatusPill.ok,
                                ),
                              ),
                      ),
                      TextButton.icon(
                        onPressed: _locating ? null : _locate,
                        icon: _locating
                            ? const SizedBox.square(
                                dimension: 16,
                                child: CircularProgressIndicator(
                                  strokeWidth: 2,
                                ),
                              )
                            : const Icon(Icons.my_location_rounded),
                        label: Text(_at == null ? 'مکان فعلی' : 'دوباره'),
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
          BrandButton(label: 'ارسال برای تأیید', busy: _busy, onPressed: _save),
          if (queued.isNotEmpty || s.customerRequests.isNotEmpty)
            const SectionTitle('درخواست‌های من'),
          for (final e in queued)
            _Tile(
              name: e.payload['name'] as String,
              pill: StatusChip(e.status),
            ),
          for (final r in s.customerRequests.take(30))
            _Tile(
              name: r['name'] as String,
              detail: r['decision_note'] as String?,
              pill: RequestStatusPill(status: r['status'] as String),
            ),
        ],
      ),
    );
  }
}

class _Tile extends StatelessWidget {
  const _Tile({required this.name, required this.pill, this.detail});
  final String name;
  final String? detail;
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
                    name,
                    style: const TextStyle(fontWeight: FontWeight.w700),
                  ),
                  if (detail != null)
                    Text(
                      detail!,
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

/// Customers kept for the visitor, so a request can be checked against the list.
bool alreadyACustomer(Catalog? cat, String name) =>
    cat?.customers.any((c) => searchKey(c.name) == searchKey(name)) ?? false;
