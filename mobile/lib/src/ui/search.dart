import 'package:flutter/material.dart';

import '../format.dart';
import '../models.dart';
import '../state.dart';
import 'customer.dart';
import 'glass.dart';
import 'order_detail.dart';
import 'parts.dart';
import 'scan.dart';
import 'widgets.dart';

/// One search over what the phone keeps: customers, items and orders (also by an item
/// in them). Works without a connection (ADR-0026).
class SearchScreen extends StatefulWidget {
  const SearchScreen({super.key, required this.state, this.initial = ''});
  final AppState state;
  final String initial;

  @override
  State<SearchScreen> createState() => _SearchScreenState();
}

class _SearchScreenState extends State<SearchScreen> {
  late final _q = TextEditingController(text: widget.initial);

  @override
  void dispose() {
    _q.dispose();
    super.dispose();
  }

  Future<void> _scan() async {
    final code = await scanBarcode(context);
    if (code != null) setState(() => _q.text = code);
  }

  @override
  Widget build(BuildContext context) {
    final s = widget.state;
    final cat = s.catalog;
    final key = searchKey(_q.text);
    final cur = cat?.currency ?? 'IRT';
    final customers = cat == null || key.isEmpty
        ? const <Customer>[]
        : cat.customers
              .where(
                (c) =>
                    searchKey(c.name).contains(key) ||
                    searchKey(c.code).contains(key) ||
                    searchKey(c.phone ?? '').contains(key),
              )
              .take(20)
              .toList();
    final scanned = cat?.byBarcode(_q.text);
    final items = cat == null || key.isEmpty
        ? const <Item>[]
        : {
            if (scanned != null) scanned.$1,
            ...cat.search(_q.text, limit: 20),
          }.toList();
    final orders = key.isEmpty
        ? const <Map<String, dynamic>>[]
        : s.orders
              .where((o) {
                final lines = (o['lines'] as List?) ?? const [];
                return searchKey('${o['number'] ?? ''}') == key ||
                    searchKey(o['customer_name'] as String? ?? '')
                        .contains(key) ||
                    lines.any(
                      (l) =>
                          searchKey((l as Map)['item_name'] as String? ?? '')
                              .contains(key),
                    );
              })
              .take(30)
              .toList();
    return Scaffold(
      appBar: PreferredSize(
        preferredSize: const Size.fromHeight(76),
        child: SafeArea(
          bottom: false,
          child: Padding(
            padding: const EdgeInsets.fromLTRB(8, 8, 14, 4),
            child: Row(
              children: [
                const BackButton(),
                Expanded(
                  child: TextField(
                    controller: _q,
                    autofocus: widget.initial.isEmpty,
                    onChanged: (_) => setState(() {}),
                    decoration: InputDecoration(
                      hintText: 'نام مشتری، کالا، بارکد یا شماره‌ی سفارش',
                      prefixIcon: const Icon(Icons.search_rounded),
                      suffixIcon: IconButton(
                        tooltip: 'اسکن بارکد',
                        onPressed: _scan,
                        icon: const Icon(Icons.qr_code_scanner_rounded),
                      ),
                      isDense: true,
                    ),
                  ),
                ),
              ],
            ),
          ),
        ),
      ),
      body: key.isEmpty
          ? const EmptyView(
              icon: Icons.manage_search_rounded,
              title: 'چه چیزی را پیدا کنیم؟',
              detail: 'مشتری، کالا (نام، کد یا بارکد) یا سفارش. بدون اینترنت هم کار می‌کند.',
            )
          : customers.isEmpty && items.isEmpty && orders.isEmpty
          ? const EmptyView(
              icon: Icons.search_off_rounded,
              title: 'چیزی پیدا نشد',
            )
          : ListView(
              padding: const EdgeInsets.fromLTRB(16, 4, 16, 24),
              children: [
                if (items.isNotEmpty) ...[
                  SectionTitle('کالاها', trailing: faDigits(items.length)),
                  for (final i in items)
                    _ItemRow(state: s, item: i, currency: cur),
                ],
                if (customers.isNotEmpty) ...[
                  SectionTitle('مشتریان', trailing: faDigits(customers.length)),
                  for (final c in customers)
                    _Row(
                      title: c.name,
                      subtitle: [
                        faDigits(c.code),
                        if (c.address != null) c.address!,
                      ].join(' · '),
                      trailing: money(c.balance, cur, unit: true),
                      onTap: () => Navigator.of(context).push(
                        MaterialPageRoute(
                          builder: (_) => CustomerScreen(state: s, customer: c),
                        ),
                      ),
                    ),
                ],
                if (orders.isNotEmpty) ...[
                  SectionTitle('سفارش‌ها', trailing: faDigits(orders.length)),
                  for (final o in orders)
                    _Row(
                      title:
                          'سفارش ${faDigits(o['number'] ?? '')} · ${o['customer_name']}',
                      subtitle: jalaliDateTime(
                        DateTime.parse(o['ordered_at'] as String),
                      ),
                      trailingWidget: StatusChip(o['status'] as String),
                      onTap: () => Navigator.of(context).push(
                        MaterialPageRoute(
                          builder: (_) => OrderDetailScreen(state: s, order: o),
                        ),
                      ),
                    ),
                ],
              ],
            ),
    );
  }
}

class _Row extends StatelessWidget {
  const _Row({
    required this.title,
    required this.subtitle,
    this.trailing,
    this.trailingWidget,
    this.onTap,
  });
  final String title;
  final String subtitle;
  final String? trailing;
  final Widget? trailingWidget;
  final VoidCallback? onTap;

  @override
  Widget build(BuildContext context) {
    final soft = Theme.of(context).colorScheme.onSurfaceVariant;
    return Padding(
      padding: const EdgeInsets.only(bottom: 8),
      child: Card(
        clipBehavior: Clip.antiAlias,
        child: InkWell(
          onTap: onTap,
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
                      const SizedBox(height: 2),
                      Text(
                        subtitle,
                        maxLines: 1,
                        overflow: TextOverflow.ellipsis,
                        style: TextStyle(fontSize: 12, color: soft),
                      ),
                    ],
                  ),
                ),
                const SizedBox(width: 8),
                ?trailingWidget,
                if (trailing != null)
                  Text(
                    trailing!,
                    style: const TextStyle(
                      fontWeight: FontWeight.w700,
                      fontSize: 12,
                    ),
                  ),
              ],
            ),
          ),
        ),
      ),
    );
  }
}

class _ItemRow extends StatelessWidget {
  const _ItemRow({
    required this.state,
    required this.item,
    required this.currency,
  });
  final AppState state;
  final Item item;
  final String currency;

  @override
  Widget build(BuildContext context) {
    final base = item.unit(item.baseUnitId);
    final soft = Theme.of(context).colorScheme.onSurfaceVariant;
    return Padding(
      padding: const EdgeInsets.only(bottom: 8),
      child: Card(
        child: Padding(
          padding: const EdgeInsets.all(10),
          child: Row(
            children: [
              ItemThumb(state: state, item: item, size: 48),
              const SizedBox(width: 10),
              Expanded(
                child: Column(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    Text(
                      item.name,
                      style: const TextStyle(fontWeight: FontWeight.w700),
                    ),
                    Text(
                      [
                        'کد ${faDigits(item.code)}',
                        if (item.stock != null)
                          'موجودی ${qty(item.stock.toString())}',
                        if (item.groupName != null) item.groupName!,
                      ].join(' · '),
                      maxLines: 1,
                      overflow: TextOverflow.ellipsis,
                      style: TextStyle(fontSize: 12, color: soft),
                    ),
                  ],
                ),
              ),
              Column(
                crossAxisAlignment: CrossAxisAlignment.end,
                children: [
                  Text(
                    base.price == null
                        ? '—'
                        : money(base.price!, currency, unit: true),
                    style: const TextStyle(
                      fontWeight: FontWeight.w800,
                      fontSize: 12,
                    ),
                  ),
                  Text(base.name, style: TextStyle(fontSize: 11, color: soft)),
                ],
              ),
            ],
          ),
        ),
      ),
    );
  }
}

/// The blur of the search field above glass pages.
class SearchBarButton extends StatelessWidget {
  const SearchBarButton({super.key, required this.onTap});
  final VoidCallback onTap;

  @override
  Widget build(BuildContext context) {
    final soft = Theme.of(context).colorScheme.onSurfaceVariant;
    return GlassPanel(
      radius: const BorderRadius.all(Radius.circular(18)),
      child: InkWell(
        onTap: onTap,
        child: Padding(
          padding: const EdgeInsets.symmetric(horizontal: 14, vertical: 13),
          child: Row(
            children: [
              Icon(Icons.search_rounded, color: soft),
              const SizedBox(width: 8),
              Expanded(
                child: Text(
                  'جست‌وجوی مشتری، کالا یا شماره‌ی سفارش',
                  style: TextStyle(color: soft),
                  overflow: TextOverflow.ellipsis,
                ),
              ),
            ],
          ),
        ),
      ),
    );
  }
}
