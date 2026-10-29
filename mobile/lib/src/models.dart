/// The offline catalogue as the server sent it (`/distribution/mobile/bootstrap`).
library;

import 'package:decimal/decimal.dart';

Decimal? _d(Object? v) => v == null ? null : Decimal.parse(v.toString());

class Customer {
  Customer.fromJson(Map<String, dynamic> j)
    : id = j['customer_id'] as String,
      code = j['code'] as String,
      name = j['name'] as String,
      phone = j['phone'] as String?,
      address = j['address'] as String?,
      visitWeekday = j['visit_weekday'] as int?,
      creditLimit = _d(j['credit_limit']),
      creditUnlimited = (j['credit_unlimited'] as bool?) ?? false,
      balance = Decimal.parse(j['balance'] as String),
      available = _d(j['available']),
      latitude = _d(j['latitude']),
      longitude = _d(j['longitude']);

  final String id;
  final String code;
  final String name;
  final String? phone;
  final String? address;
  final int? visitWeekday;
  final Decimal? creditLimit;

  /// Credit sales with no limit (then [creditLimit] and [available] are null).
  final bool creditUnlimited;
  final Decimal balance;
  final Decimal? available;

  /// Where the shop is, for navigation (ADR-0026); null until someone records it.
  final Decimal? latitude;
  final Decimal? longitude;

  bool get located => latitude != null && longitude != null;
}

class ItemUnit {
  ItemUnit.fromJson(Map<String, dynamic> j)
    : unitId = j['unit_id'] as String,
      name = j['name'] as String,
      factor = Decimal.parse(j['factor'] as String),
      price = _d(j['price']),
      allowsFraction = j['allows_fraction'] as bool;

  final String unitId;
  final String name;
  final Decimal factor;
  final Decimal? price;
  final bool allowsFraction;
}

class Item {
  Item.fromJson(Map<String, dynamic> j)
    : id = j['id'] as String,
      code = j['code'] as String,
      name = j['name'] as String,
      groupName = j['group_name'] as String?,
      baseUnitId = j['base_unit_id'] as String,
      units = (j['units'] as List)
          .map((u) => ItemUnit.fromJson(u as Map<String, dynamic>))
          .toList(),
      stock = _d(j['stock']),
      vatExempt = j['vat_exempt'] as bool,
      imageIds = ((j['image_ids'] as List?) ?? const [])
          .cast<String>()
          .toList(),
      barcodes = {
        for (final b in (j['barcodes'] as List?) ?? const [])
          (b as Map)['barcode'] as String: b['unit_id'] as String?,
      };

  final String id;
  final String code;
  final String name;
  final String? groupName;
  final String baseUnitId;
  final List<ItemUnit> units;
  final Decimal? stock;
  final bool vatExempt;

  /// Product photos, main first (ADR-0022).
  final List<String> imageIds;

  /// Barcode → unit (null = base unit), for the camera scanner.
  final Map<String, String?> barcodes;

  ItemUnit unit(String id) =>
      units.firstWhere((u) => u.unitId == id, orElse: () => units.first);
}

class Catalog {
  Catalog.fromJson(Map<String, dynamic> j)
    : visitorName = (j['visitor'] as Map)['name'] as String,
      visitorCode = (j['visitor'] as Map)['code'] as String,
      branchName = (j['visitor'] as Map)['branch_name'] as String,
      organization = (j['settings'] as Map)['organization_name'] as String,
      currency = (j['settings'] as Map)['display_currency'] as String,
      pricesIncludeVat = (j['settings'] as Map)['prices_include_vat'] as bool,
      generatedAt = DateTime.parse(j['generated_at'] as String),
      customers = (j['customers'] as List)
          .map((c) => Customer.fromJson(c as Map<String, dynamic>))
          .toList(),
      items = (j['items'] as List)
          .map((i) => Item.fromJson(i as Map<String, dynamic>))
          .toList();

  final String visitorName;
  final String visitorCode;
  final String branchName;
  final String organization;
  final String currency;
  final bool pricesIncludeVat;
  final DateTime generatedAt;
  final List<Customer> customers;
  final List<Item> items;

  Customer? customer(String id) {
    for (final c in customers) {
      if (c.id == id) return c;
    }
    return null;
  }

  Item? item(String id) {
    for (final i in items) {
      if (i.id == id) return i;
    }
    return null;
  }

  /// The item (and unit) a scanned barcode or typed code belongs to.
  (Item, String)? byBarcode(String code) {
    final c = code.trim();
    if (c.isEmpty) return null;
    for (final i in items) {
      if (i.barcodes.containsKey(c)) return (i, i.barcodes[c] ?? i.baseUnitId);
    }
    for (final i in items) {
      if (i.code == c) return (i, i.baseUnitId);
    }
    return null;
  }

  List<Item> search(String text, {int limit = 30}) {
    final q = searchKey(text);
    if (q.isEmpty) return items.take(limit).toList();
    return items
        .where(
          (i) =>
              searchKey(i.name).contains(q) ||
              searchKey(i.code).startsWith(q) ||
              i.barcodes.keys.any((b) => b == text.trim()),
        )
        .take(limit)
        .toList();
  }
}

/// A line the visitor is writing (not priced: the server prices the order).
class DraftLine {
  DraftLine(this.item, this.unitId, this.qty);
  final Item item;
  String unitId;
  Decimal qty;

  ItemUnit get unit => item.unit(unitId);

  /// List price × quantity: an estimate before discounts and VAT.
  Decimal? get listAmount {
    final p = unit.price;
    return p == null ? null : (p * qty).round();
  }

  Map<String, dynamic> toJson() => {
    'item_id': item.id,
    'unit_id': unitId,
    'qty': qty.toStringAsFixed(3),
  };
}

const orderStatusLabel = {
  'submitted': 'در انتظار بررسی',
  'approved': 'تأیید شد',
  'rejected': 'رد شد',
  'invoiced': 'فاکتور شد',
  'delivered': 'تحویل شد',
  'cancelled': 'لغو شد',
  'pending': 'در صف ارسال',
  'failed': 'ارسال نشد',
};

const visitOutcomeLabel = {
  'order': 'سفارش گرفت',
  'no_order': 'نیاز نداشت',
  'closed': 'مغازه بسته بود',
  'absent': 'مسئول خرید نبود',
  'stocked': 'موجودی داشت',
  'price': 'قیمت یا شرایط',
  'credit': 'اعتبار کافی نبود',
};

/// Reasons a visitor can give for a visit without an order.
const noOrderOutcomes = [
  'no_order',
  'stocked',
  'price',
  'credit',
  'closed',
  'absent',
];

const collectionMethodLabel = {
  'cash': 'نقد',
  'cheque': 'چک',
  'transfer': 'کارت‌به‌کارت',
};

const requestStatusLabel = {
  'pending': 'در انتظار تأیید',
  'approved': 'تأیید شد',
  'rejected': 'رد شد',
};

/// Persian letters and digits made comparable (ي/ك → ی/ک, digits to Latin, no ZWNJ).
String searchKey(String s) {
  const fa = '۰۱۲۳۴۵۶۷۸۹';
  const ar = '٠١٢٣٤٥٦٧٨٩';
  final b = StringBuffer();
  for (final ch in s.toLowerCase().runes) {
    var c = String.fromCharCode(ch);
    final i = fa.indexOf(c);
    final j = ar.indexOf(c);
    if (i >= 0) c = '$i';
    if (j >= 0) c = '$j';
    if (c == 'ي') c = 'ی';
    if (c == 'ك') c = 'ک';
    if (c == '\u200c' || c == ' ') continue;
    b.write(c);
  }
  return b.toString();
}
