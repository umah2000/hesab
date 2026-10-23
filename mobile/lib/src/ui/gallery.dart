import 'package:decimal/decimal.dart';
import 'package:flutter/material.dart';

import '../format.dart';
import '../models.dart';
import '../state.dart';
import 'widgets.dart';

/// What the visitor chose on the photo screen.
typedef PickedQty = ({String unitId, Decimal qty});

/// An item's photos, full screen, for the buyer: swipe between photos, pinch to zoom.
/// With [canAdd] the visitor picks a unit and quantity and adds it to the order here.
class ItemGalleryScreen extends StatefulWidget {
  const ItemGalleryScreen({
    super.key,
    required this.state,
    required this.item,
    required this.currency,
    this.canAdd = false,
  });
  final AppState state;
  final Item item;
  final String currency;
  final bool canAdd;

  @override
  State<ItemGalleryScreen> createState() => _ItemGalleryScreenState();
}

class _ItemGalleryScreenState extends State<ItemGalleryScreen> {
  late String _unitId = widget.item.baseUnitId;
  Decimal _qty = Decimal.one;
  int _page = 0;

  ItemUnit get _unit => widget.item.unit(_unitId);
  Decimal get _step =>
      _unit.allowsFraction ? Decimal.parse('0.5') : Decimal.one;

  @override
  Widget build(BuildContext context) {
    final it = widget.item;
    final ids = it.imageIds;
    final price = _unit.price;
    return Scaffold(
      backgroundColor: Colors.black,
      appBar: AppBar(
        backgroundColor: Colors.black,
        foregroundColor: Colors.white,
        title: Text(it.name, maxLines: 1, overflow: TextOverflow.ellipsis),
      ),
      body: Column(
        children: [
          Expanded(
            child: ids.isEmpty
                ? const Center(
                    child: Column(
                      mainAxisSize: MainAxisSize.min,
                      children: [
                        Icon(
                          Icons.image_not_supported_outlined,
                          color: Colors.white54,
                          size: 56,
                        ),
                        SizedBox(height: 8),
                        Text(
                          'این کالا عکس ندارد',
                          style: TextStyle(color: Colors.white70),
                        ),
                      ],
                    ),
                  )
                : Stack(
                    children: [
                      PageView.builder(
                        itemCount: ids.length,
                        onPageChanged: (p) => setState(() => _page = p),
                        itemBuilder: (_, i) => InteractiveViewer(
                          maxScale: 5,
                          child: Center(
                            child: Photo(
                              state: widget.state,
                              id: ids[i],
                              large: true,
                              fit: BoxFit.contain,
                            ),
                          ),
                        ),
                      ),
                      if (ids.length > 1)
                        Positioned(
                          bottom: 12,
                          left: 0,
                          right: 0,
                          child: Semantics(
                            label:
                                'عکس ${faDigits(_page + 1)} از ${faDigits(ids.length)}',
                            child: Row(
                              mainAxisAlignment: MainAxisAlignment.center,
                              children: [
                                for (var i = 0; i < ids.length; i++)
                                  Container(
                                    width: i == _page ? 18 : 8,
                                    height: 8,
                                    margin: const EdgeInsets.symmetric(
                                      horizontal: 3,
                                    ),
                                    decoration: BoxDecoration(
                                      color: i == _page
                                          ? Colors.white
                                          : Colors.white38,
                                      borderRadius: BorderRadius.circular(4),
                                    ),
                                  ),
                              ],
                            ),
                          ),
                        ),
                    ],
                  ),
          ),
          Material(
            color: Theme.of(context).colorScheme.surface,
            borderRadius: const BorderRadius.vertical(top: Radius.circular(20)),
            child: SafeArea(
              top: false,
              child: Padding(
                padding: const EdgeInsets.fromLTRB(16, 14, 16, 12),
                child: Column(
                  mainAxisSize: MainAxisSize.min,
                  crossAxisAlignment: CrossAxisAlignment.stretch,
                  children: [
                    Row(
                      children: [
                        Expanded(
                          child: Text(
                            it.name,
                            style: const TextStyle(
                              fontWeight: FontWeight.w800,
                              fontSize: 16,
                            ),
                          ),
                        ),
                        Text(
                          price == null
                              ? 'بدون قیمت'
                              : '${money(price, widget.currency, unit: true)} / ${_unit.name}',
                          style: const TextStyle(fontWeight: FontWeight.w700),
                        ),
                      ],
                    ),
                    const SizedBox(height: 2),
                    Text(
                      [
                        faDigits(it.code),
                        if (it.groupName != null) it.groupName!,
                        if (it.stock != null)
                          'موجودی ${qty(it.stock.toString())} ${it.unit(it.baseUnitId).name}',
                      ].join(' · '),
                      style: TextStyle(
                        fontSize: 12,
                        color: Theme.of(context).colorScheme.outline,
                      ),
                    ),
                    if (widget.canAdd) ...[
                      const SizedBox(height: 10),
                      Row(
                        children: [
                          IconButton.filledTonal(
                            tooltip: 'کم',
                            onPressed: _qty > _step
                                ? () => setState(() => _qty -= _step)
                                : null,
                            icon: const Icon(Icons.remove_rounded),
                          ),
                          SizedBox(
                            width: 56,
                            child: Text(
                              qty(_qty.toString()),
                              textAlign: TextAlign.center,
                              style: const TextStyle(
                                fontSize: 18,
                                fontWeight: FontWeight.w800,
                              ),
                            ),
                          ),
                          IconButton.filledTonal(
                            tooltip: 'زیاد',
                            onPressed: () => setState(() => _qty += _step),
                            icon: const Icon(Icons.add_rounded),
                          ),
                          const SizedBox(width: 8),
                          if (it.units.length > 1)
                            DropdownButton<String>(
                              value: _unitId,
                              underline: const SizedBox(),
                              items: [
                                for (final u in it.units)
                                  DropdownMenuItem(
                                    value: u.unitId,
                                    child: Text(
                                      u.factor == Decimal.one
                                          ? u.name
                                          : '${u.name} ${faDigits(u.factor)}تایی',
                                    ),
                                  ),
                              ],
                              onChanged: (v) => setState(() {
                                _unitId = v!;
                                if (!_unit.allowsFraction) {
                                  _qty = _qty.ceil();
                                }
                              }),
                            )
                          else
                            Text(_unit.name),
                        ],
                      ),
                      const SizedBox(height: 10),
                      FilledButton.icon(
                        style: FilledButton.styleFrom(
                          minimumSize: const Size.fromHeight(50),
                        ),
                        onPressed: () => Navigator.pop<PickedQty>(context, (
                          unitId: _unitId,
                          qty: _qty,
                        )),
                        icon: const Icon(Icons.add_shopping_cart_rounded),
                        label: const Text('افزودن به سفارش'),
                      ),
                    ],
                  ],
                ),
              ),
            ),
          ),
        ],
      ),
    );
  }
}
