import 'package:decimal/decimal.dart';
import 'package:flutter/material.dart';

import '../api.dart';
import '../format.dart';
import '../models.dart';
import '../state.dart';
import 'widgets.dart';

/// Writing an order. Offline the phone shows list prices only; the final price
/// (promotions, VAT) always comes from the server — on demand with «قیمت قطعی», and
/// in any case when the order arrives.
class OrderScreen extends StatefulWidget {
  const OrderScreen({
    super.key,
    required this.state,
    required this.customer,
    this.initial,
  });
  final AppState state;
  final Customer customer;
  final List<DraftLine>? initial;

  @override
  State<OrderScreen> createState() => _OrderScreenState();
}

class _OrderScreenState extends State<OrderScreen> {
  late final List<DraftLine> _lines = [...?widget.initial];
  final _note = TextEditingController();
  Map<String, dynamic>? _quote;
  String? _quoteError;
  bool _busy = false;

  Catalog get _cat => widget.state.catalog!;

  Decimal? get _listTotal {
    var t = Decimal.zero;
    for (final l in _lines) {
      final a = l.listAmount;
      if (a == null) return null;
      t += a;
    }
    return t;
  }

  void _changed() => setState(() {
    _quote = null;
    _quoteError = null;
  });

  Future<void> _addItem() async {
    final item = await showModalBottomSheet<Item>(
      context: context,
      isScrollControlled: true,
      showDragHandle: true,
      builder: (_) => _ItemPicker(catalog: _cat),
    );
    if (item == null) return;
    final existing = _lines.where(
      (l) => l.item.id == item.id && l.unitId == item.baseUnitId,
    );
    if (existing.isNotEmpty) {
      existing.first.qty += Decimal.one;
    } else {
      _lines.add(DraftLine(item, item.baseUnitId, Decimal.one));
    }
    _changed();
  }

  Future<void> _getQuote() async {
    setState(() {
      _busy = true;
      _quoteError = null;
    });
    try {
      final q = await widget.state.quote(widget.customer, _lines);
      setState(() => _quote = q);
    } on NetworkException {
      setState(
        () => _quoteError = 'بدون اینترنت قیمت قطعی در دسترس نیست؛ سفارش را ثبت کنید، سرور قیمت می‌گذارد.',
      );
    } on ApiException catch (e) {
      setState(() => _quoteError = e.message);
    } finally {
      if (mounted) setState(() => _busy = false);
    }
  }

  Future<void> _submit() async {
    final messenger = ScaffoldMessenger.of(context);
    final nav = Navigator.of(context);
    final quoted = _quote == null
        ? null
        : Decimal.parse(_quote!['grand_total'] as String);
    await widget.state.placeOrder(
      widget.customer,
      _lines,
      note: _note.text,
      serverTotal: quoted,
    );
    messenger.showSnackBar(
      SnackBar(
        content: Text(
          widget.state.online
              ? 'سفارش ثبت شد و برای بررسی ارسال می‌شود'
              : 'سفارش روی گوشی ثبت شد؛ با وصل شدن اینترنت ارسال می‌شود',
        ),
      ),
    );
    nav.pop();
  }

  @override
  Widget build(BuildContext context) {
    final cur = _cat.currency;
    final outline = Theme.of(context).colorScheme.outline;
    final list = _listTotal;
    return Scaffold(
      appBar: AppBar(title: Text('سفارش ${widget.customer.name}')),
      floatingActionButton: FloatingActionButton.extended(
        onPressed: _addItem,
        icon: const Icon(Icons.add_rounded),
        label: const Text('افزودن کالا'),
      ),
      body: _lines.isEmpty
          ? const EmptyView(
              icon: Icons.shopping_basket_rounded,
              title: 'کالایی اضافه نشده',
              detail: 'با «افزودن کالا» از فهرست کالاها انتخاب کنید.',
            )
          : ListView(
              padding: const EdgeInsets.fromLTRB(16, 12, 16, 96),
              children: [
                for (final (i, l) in _lines.indexed) ...[
                  _LineCard(
                    line: l,
                    currency: cur,
                    onChanged: _changed,
                    onRemove: () {
                      _lines.removeAt(i);
                      _changed();
                    },
                  ),
                  const SizedBox(height: 8),
                ],
                const SizedBox(height: 4),
                Card(
                  child: Padding(
                    padding: const EdgeInsets.all(14),
                    child: Column(
                      crossAxisAlignment: CrossAxisAlignment.stretch,
                      children: [
                        LabelValue(
                          'جمع به قیمت فهرست',
                          list == null
                              ? 'قیمت برخی کالاها روی گوشی نیست'
                              : money(list, cur, unit: true),
                        ),
                        Text(
                          'بدون تخفیف و ${_cat.pricesIncludeVat ? 'با' : 'بدون'} مالیات؛ مبلغ قطعی را سرور تعیین می‌کند.',
                          style: TextStyle(fontSize: 12, color: outline),
                        ),
                        if (_quote != null) ...[
                          const Divider(height: 20),
                          LabelValue(
                            'جمع',
                            money(dec(_quote!['subtotal'] as String), cur),
                          ),
                          LabelValue(
                            'تخفیف',
                            money(
                              dec(_quote!['discount_total'] as String),
                              cur,
                            ),
                          ),
                          LabelValue(
                            'مالیات',
                            money(dec(_quote!['tax_total'] as String), cur),
                          ),
                          LabelValue(
                            'مبلغ قطعی',
                            money(
                              dec(_quote!['grand_total'] as String),
                              cur,
                              unit: true,
                            ),
                            bold: true,
                          ),
                          if (_quote!['available_after'] != null)
                            LabelValue(
                              'اعتبار پس از این سفارش',
                              money(
                                dec(_quote!['available_after'] as String),
                                cur,
                                unit: true,
                              ),
                            ),
                          if (_quote!['available_after'] != null &&
                              dec(_quote!['available_after'] as String) <
                                  Decimal.zero)
                            const Padding(
                              padding: EdgeInsets.only(top: 6),
                              child: Row(
                                children: [
                                  Icon(
                                    Icons.error_rounded,
                                    size: 16,
                                    color: Color(0xFFB91C1C),
                                  ),
                                  SizedBox(width: 4),
                                  Expanded(
                                    child: Text(
                                      'سقف اعتبار مشتری کافی نیست؛ این سفارش بدون افزایش سقف تأیید نمی‌شود.',
                                      style: TextStyle(fontSize: 12),
                                    ),
                                  ),
                                ],
                              ),
                            ),
                          for (final w in (_quote!['warnings'] as List))
                            Padding(
                              padding: const EdgeInsets.only(top: 4),
                              child: Row(
                                children: [
                                  const Icon(
                                    Icons.warning_amber_rounded,
                                    size: 16,
                                    color: Color(0xFFB45309),
                                  ),
                                  const SizedBox(width: 4),
                                  Expanded(
                                    child: Text(
                                      w as String,
                                      style: const TextStyle(fontSize: 12),
                                    ),
                                  ),
                                ],
                              ),
                            ),
                        ],
                        if (_quoteError != null) ...[
                          const SizedBox(height: 8),
                          Text(
                            _quoteError!,
                            style: const TextStyle(fontSize: 12),
                          ),
                        ],
                        const SizedBox(height: 8),
                        OutlinedButton.icon(
                          onPressed: _busy ? null : _getQuote,
                          icon: const Icon(Icons.price_check_rounded),
                          label: const Text('قیمت قطعی از سرور'),
                        ),
                      ],
                    ),
                  ),
                ),
                const SizedBox(height: 12),
                TextField(
                  controller: _note,
                  maxLength: 300,
                  decoration: const InputDecoration(
                    labelText: 'توضیح سفارش (مثلاً زمان تحویل)',
                    counterText: '',
                  ),
                ),
                const SizedBox(height: 8),
                FilledButton.icon(
                  style: FilledButton.styleFrom(
                    minimumSize: const Size.fromHeight(52),
                  ),
                  onPressed: _busy ? null : _submit,
                  icon: const Icon(Icons.send_rounded),
                  label: const Text('ثبت سفارش'),
                ),
              ],
            ),
    );
  }
}

class _LineCard extends StatelessWidget {
  const _LineCard({
    required this.line,
    required this.currency,
    required this.onChanged,
    required this.onRemove,
  });
  final DraftLine line;
  final String currency;
  final VoidCallback onChanged;
  final VoidCallback onRemove;

  @override
  Widget build(BuildContext context) {
    final l = line;
    final amount = l.listAmount;
    final step = l.unit.allowsFraction ? Decimal.parse('0.5') : Decimal.one;
    return Card(
      child: Padding(
        padding: const EdgeInsets.fromLTRB(14, 10, 6, 10),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Row(
              children: [
                Expanded(
                  child: Text(
                    l.item.name,
                    style: const TextStyle(fontWeight: FontWeight.w700),
                  ),
                ),
                IconButton(
                  tooltip: 'حذف',
                  onPressed: onRemove,
                  icon: const Icon(Icons.delete_outline_rounded),
                ),
              ],
            ),
            Row(
              children: [
                IconButton.filledTonal(
                  tooltip: 'کم',
                  onPressed: l.qty > step
                      ? () {
                          l.qty -= step;
                          onChanged();
                        }
                      : null,
                  icon: const Icon(Icons.remove_rounded),
                ),
                SizedBox(
                  width: 56,
                  child: Text(
                    qty(l.qty.toString()),
                    textAlign: TextAlign.center,
                    style: const TextStyle(
                      fontSize: 18,
                      fontWeight: FontWeight.w800,
                    ),
                  ),
                ),
                IconButton.filledTonal(
                  tooltip: 'زیاد',
                  onPressed: () {
                    l.qty += step;
                    onChanged();
                  },
                  icon: const Icon(Icons.add_rounded),
                ),
                const SizedBox(width: 8),
                if (l.item.units.length > 1)
                  DropdownButton<String>(
                    value: l.unitId,
                    underline: const SizedBox(),
                    items: [
                      for (final u in l.item.units)
                        DropdownMenuItem(
                          value: u.unitId,
                          child: Text(
                            u.factor == Decimal.one
                                ? u.name
                                : '${u.name} ${faDigits(u.factor)}تایی',
                          ),
                        ),
                    ],
                    onChanged: (v) {
                      l.unitId = v!;
                      onChanged();
                    },
                  )
                else
                  Text(l.unit.name),
                const Spacer(),
                Padding(
                  padding: const EdgeInsetsDirectional.only(end: 8),
                  child: Text(amount == null ? '—' : money(amount, currency)),
                ),
              ],
            ),
          ],
        ),
      ),
    );
  }
}

class _ItemPicker extends StatefulWidget {
  const _ItemPicker({required this.catalog});
  final Catalog catalog;

  @override
  State<_ItemPicker> createState() => _ItemPickerState();
}

class _ItemPickerState extends State<_ItemPicker> {
  String _q = '';

  @override
  Widget build(BuildContext context) {
    final items = widget.catalog.search(_q);
    final outline = Theme.of(context).colorScheme.outline;
    return SizedBox(
      height: MediaQuery.of(context).size.height * 0.8,
      child: Column(
        children: [
          Padding(
            padding: const EdgeInsets.fromLTRB(16, 0, 16, 8),
            child: TextField(
              autofocus: true,
              onChanged: (v) => setState(() => _q = enDigits(v)),
              decoration: const InputDecoration(
                hintText: 'نام یا کد کالا',
                prefixIcon: Icon(Icons.search_rounded),
              ),
            ),
          ),
          Expanded(
            child: ListView.builder(
              itemCount: items.length,
              itemBuilder: (context, i) {
                final it = items[i];
                final base = it.unit(it.baseUnitId);
                return ListTile(
                  title: Text(it.name),
                  subtitle: Text(
                    [
                      faDigits(it.code),
                      if (it.groupName != null) it.groupName!,
                      if (it.stock != null)
                        'موجودی ${qty(it.stock.toString())} ${base.name}',
                    ].join(' · '),
                    style: TextStyle(color: outline),
                  ),
                  trailing: Text(
                    base.price == null
                        ? '—'
                        : money(base.price!, widget.catalog.currency),
                    style: const TextStyle(fontWeight: FontWeight.w700),
                  ),
                  onTap: () => Navigator.pop(context, it),
                );
              },
            ),
          ),
        ],
      ),
    );
  }
}
