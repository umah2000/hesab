import 'package:decimal/decimal.dart';
import 'package:flutter/material.dart';

import '../api.dart';
import '../format.dart';
import '../models.dart';
import '../state.dart';
import 'gallery.dart';
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
    final picked = await showModalBottomSheet<_Picked>(
      context: context,
      isScrollControlled: true,
      showDragHandle: true,
      builder: (_) => _ItemPicker(state: widget.state, catalog: _cat),
    );
    if (picked == null) return;
    final (item, unitId, qty) = picked;
    final existing = _lines.where(
      (l) => l.item.id == item.id && l.unitId == unitId,
    );
    if (existing.isNotEmpty) {
      existing.first.qty += qty;
    } else {
      _lines.add(DraftLine(item, unitId, qty));
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
                    state: widget.state,
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
                          if (_quote!['credit_unlimited'] == true)
                            const LabelValue('اعتبار مشتری', 'نامحدود'),
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
    required this.state,
    required this.line,
    required this.currency,
    required this.onChanged,
    required this.onRemove,
  });
  final AppState state;
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
                if (l.item.imageIds.isNotEmpty) ...[
                  InkWell(
                    borderRadius: BorderRadius.circular(10),
                    onTap: () => showGallery(context, state, l.item, currency),
                    child: ItemThumb(state: state, item: l.item, size: 44),
                  ),
                  const SizedBox(width: 10),
                ],
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

/// (item, unit, quantity) chosen in the picker.
typedef _Picked = (Item, String, Decimal);

/// Opens an item's photos full screen; with [canAdd] returns the chosen quantity.
Future<PickedQty?> showGallery(
  BuildContext context,
  AppState state,
  Item item,
  String currency, {
  bool canAdd = false,
}) => Navigator.of(context).push<PickedQty>(
  MaterialPageRoute(
    builder: (_) => ItemGalleryScreen(
      state: state,
      item: item,
      currency: currency,
      canAdd: canAdd,
    ),
  ),
);

class _ItemPicker extends StatefulWidget {
  const _ItemPicker({required this.state, required this.catalog});
  final AppState state;
  final Catalog catalog;

  @override
  State<_ItemPicker> createState() => _ItemPickerState();
}

class _ItemPickerState extends State<_ItemPicker> {
  String _q = '';
  // Photos first when the catalogue has any: the buyer chooses by looking.
  late bool _grid = widget.catalog.items.any((i) => i.imageIds.isNotEmpty);

  Future<void> _openPhotos(Item it) async {
    final nav = Navigator.of(context);
    final picked = await showGallery(
      context,
      widget.state,
      it,
      widget.catalog.currency,
      canAdd: true,
    );
    if (picked != null) nav.pop<_Picked>((it, picked.unitId, picked.qty));
  }

  void _addOne(Item it) =>
      Navigator.pop<_Picked>(context, (it, it.baseUnitId, Decimal.one));

  @override
  Widget build(BuildContext context) {
    final items = widget.catalog.search(_q, limit: _grid ? 60 : 30);
    final outline = Theme.of(context).colorScheme.outline;
    final cur = widget.catalog.currency;
    return SizedBox(
      height: MediaQuery.of(context).size.height * 0.85,
      child: Column(
        children: [
          Padding(
            padding: const EdgeInsets.fromLTRB(16, 0, 8, 8),
            child: Row(
              children: [
                Expanded(
                  child: TextField(
                    autofocus: !_grid,
                    onChanged: (v) => setState(() => _q = enDigits(v)),
                    decoration: const InputDecoration(
                      hintText: 'نام یا کد کالا',
                      prefixIcon: Icon(Icons.search_rounded),
                    ),
                  ),
                ),
                const SizedBox(width: 4),
                IconButton(
                  tooltip: _grid ? 'نمایش فهرستی' : 'نمایش با عکس',
                  onPressed: () => setState(() => _grid = !_grid),
                  icon: Icon(
                    _grid ? Icons.view_list_rounded : Icons.grid_view_rounded,
                  ),
                ),
              ],
            ),
          ),
          Expanded(
            child: _grid
                ? GridView.builder(
                    padding: const EdgeInsets.fromLTRB(12, 0, 12, 16),
                    gridDelegate:
                        const SliverGridDelegateWithMaxCrossAxisExtent(
                          maxCrossAxisExtent: 200,
                          mainAxisSpacing: 10,
                          crossAxisSpacing: 10,
                          childAspectRatio: 0.72,
                        ),
                    itemCount: items.length,
                    itemBuilder: (context, i) {
                      final it = items[i];
                      final base = it.unit(it.baseUnitId);
                      return Card(
                        clipBehavior: Clip.antiAlias,
                        margin: EdgeInsets.zero,
                        child: InkWell(
                          onTap: () => _openPhotos(it),
                          child: Column(
                            crossAxisAlignment: CrossAxisAlignment.stretch,
                            children: [
                              Expanded(
                                child: Photo(
                                  state: widget.state,
                                  id: it.imageIds.isEmpty
                                      ? null
                                      : it.imageIds.first,
                                ),
                              ),
                              Padding(
                                padding: const EdgeInsets.fromLTRB(
                                  10,
                                  8,
                                  10,
                                  2,
                                ),
                                child: Text(
                                  it.name,
                                  maxLines: 2,
                                  overflow: TextOverflow.ellipsis,
                                  style: const TextStyle(
                                    fontWeight: FontWeight.w700,
                                    fontSize: 13,
                                  ),
                                ),
                              ),
                              Padding(
                                padding: const EdgeInsets.fromLTRB(10, 0, 4, 4),
                                child: Row(
                                  children: [
                                    Expanded(
                                      child: Text(
                                        base.price == null
                                            ? '—'
                                            : money(base.price!, cur),
                                        style: TextStyle(
                                          fontSize: 12,
                                          color: outline,
                                        ),
                                      ),
                                    ),
                                    IconButton(
                                      tooltip: 'افزودن ${it.name}',
                                      visualDensity: VisualDensity.compact,
                                      onPressed: () => _addOne(it),
                                      icon: const Icon(
                                        Icons.add_circle_rounded,
                                      ),
                                    ),
                                  ],
                                ),
                              ),
                            ],
                          ),
                        ),
                      );
                    },
                  )
                : ListView.builder(
                    itemCount: items.length,
                    itemBuilder: (context, i) {
                      final it = items[i];
                      final base = it.unit(it.baseUnitId);
                      return ListTile(
                        leading: InkWell(
                          borderRadius: BorderRadius.circular(10),
                          onTap: () => _openPhotos(it),
                          child: ItemThumb(state: widget.state, item: it),
                        ),
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
                          base.price == null ? '—' : money(base.price!, cur),
                          style: const TextStyle(fontWeight: FontWeight.w700),
                        ),
                        onTap: () => _addOne(it),
                      );
                    },
                  ),
          ),
        ],
      ),
    );
  }
}
