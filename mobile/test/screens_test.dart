/// Every screen rendered at phone size with the real Persian font: fails on any layout
/// overflow, and writes the screenshots used in the docs (test/goldens).
@Tags(['screens'])
library;

import 'dart:convert';
import 'dart:io';

import 'package:decimal/decimal.dart';
import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'package:flutter_localizations/flutter_localizations.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:http/http.dart' as http;
import 'package:http/testing.dart';
import 'package:nextcam_visitor/src/api.dart';
import 'package:nextcam_visitor/src/db.dart';
import 'package:nextcam_visitor/src/models.dart';
import 'package:nextcam_visitor/src/state.dart';
import 'package:nextcam_visitor/src/tokens.dart';
import 'package:nextcam_visitor/src/ui/app.dart';
import 'package:nextcam_visitor/src/ui/collection.dart';
import 'package:nextcam_visitor/src/ui/customer.dart';
import 'package:nextcam_visitor/src/ui/gallery.dart';
import 'package:nextcam_visitor/src/ui/home.dart';
import 'package:nextcam_visitor/src/ui/login.dart';
import 'package:nextcam_visitor/src/ui/new_customer.dart';
import 'package:nextcam_visitor/src/ui/notifications.dart';
import 'package:nextcam_visitor/src/ui/order_detail.dart';
import 'package:nextcam_visitor/src/ui/order.dart';
import 'package:nextcam_visitor/src/ui/search.dart';
import 'package:sqflite_common_ffi/sqflite_ffi.dart';

final now = DateTime.utc(2026, 10, 17, 6, 30); // Saturday morning in Tehran

Map<String, dynamic> unit(
  String id,
  String name,
  String factor,
  String? price, [
  bool fr = false,
]) => {
  'unit_id': id,
  'name': name,
  'factor': factor,
  'price': price,
  'allows_fraction': fr,
};

final bootstrap = {
  'version': 'v1',
  'api_level': 2,
  'generated_at': now.toIso8601String(),
  'visitor': {
    'id': 'v1',
    'code': 'V01',
    'name': 'رضا کریمی',
    'branch_name': 'شعبه مرکزی',
  },
  'settings': {
    'organization_name': 'سوپرمارکت نمونه',
    'display_currency': 'IRT',
    'prices_include_vat': false,
    'default_vat_rate': '10',
  },
  'customers': [
    for (final (i, c) in [
      ('رستوران آفتاب', 'خیابان آزادی، پلاک ۱۲', 0, '3150000', '10000000'),
      ('بقالی محله', 'کوچه سرو، پلاک ۴', 0, '0', null),
      ('کافه نارنج', 'بلوار کشاورز، پلاک ۸۸', 0, '820000', '5000000'),
      ('فروشگاه بهار', 'میدان انقلاب', 2, '1200000', '3000000'),
    ].indexed)
      {
        'customer_id': 'c$i',
        'code': 'C${i + 1}',
        'name': c.$1,
        'phone': '0912000000$i',
        'address': c.$2,
        'visit_weekday': c.$3,
        'credit_limit': c.$5,
        'balance': c.$4,
        'available': c.$5 == null
            ? null
            : (Decimal.parse(c.$5!) - Decimal.parse(c.$4)).toString(),
      },
  ],
  'items': [
    {
      'id': 'milk',
      'code': '1001',
      'name': 'شیر پرچرب ۱ لیتری',
      'group_name': 'لبنیات',
      'base_unit_id': 'pcs',
      'units': [
        unit('pcs', 'عدد', '1', '110000'),
        unit('box', 'کارتن', '12', '1320000'),
      ],
      'stock': '240.000',
      'vat_exempt': false,
      'image_ids': ['pm1', 'pm2'],
    },
    {
      'id': 'water',
      'code': '1003',
      'name': 'آب معدنی ۱٫۵ لیتری',
      'group_name': 'نوشیدنی',
      'base_unit_id': 'pcs',
      'units': [
        unit('pcs', 'عدد', '1', '15000'),
        unit('pack', 'بسته', '6', '90000'),
      ],
      'stock': '600.000',
      'vat_exempt': false,
      'image_ids': ['pw1'],
    },
    {
      'id': 'rice',
      'code': '2001',
      'name': 'برنج ایرانی',
      'group_name': 'خواربار',
      'base_unit_id': 'kg',
      'units': [unit('kg', 'کیلوگرم', '1', '1450000', true)],
      'stock': '85.500',
      'vat_exempt': true,
    },
  ],
};

final orders = [
  {
    'id': 'o3',
    'number': 3,
    'status': 'submitted',
    'customer_name': 'کافه نارنج',
    'ordered_at': now.subtract(const Duration(minutes: 40)).toIso8601String(),
    'received_at': now.toIso8601String(),
    'grand_total': '2310000.0000',
    'invoice_number': null,
    'decision_note': null,
  },
  {
    'id': 'o2',
    'number': 2,
    'status': 'delivered',
    'customer_id': 'c0',
    'customer_name': 'رستوران آفتاب',
    'decided_at': now.subtract(const Duration(days: 2)).toIso8601String(),
    'delivered_at': now.subtract(const Duration(days: 1)).toIso8601String(),
    'subtotal': '3460000.0000',
    'discount_total': '50000.0000',
    'tax_total': '0.0000',
    'lines': [
      {
        'item_id': 'milk',
        'item_name': 'شیر پرچرب ۱ لیتری',
        'unit_id': 'box',
        'unit_name': 'کارتن',
        'qty': '2.000',
        'unit_price': '1320000.0000',
        'promotion_discount': '0.0000',
        'tax': '0.0000',
        'line_total': '2640000.0000',
      },
      {
        'item_id': 'water',
        'item_name': 'آب معدنی ۱٫۵ لیتری',
        'unit_id': 'pack',
        'unit_name': 'بسته',
        'qty': '10.000',
        'unit_price': '90000.0000',
        'promotion_discount': '50000.0000',
        'tax': '0.0000',
        'line_total': '850000.0000',
      },
    ],
    'ordered_at': now.subtract(const Duration(days: 2)).toIso8601String(),
    'received_at': now.toIso8601String(),
    'grand_total': '3410000.0000',
    'invoice_number': 41,
    'decision_note': null,
  },
  {
    'id': 'o1',
    'number': 1,
    'status': 'rejected',
    'customer_name': 'فروشگاه بهار',
    'ordered_at': now.subtract(const Duration(days: 5)).toIso8601String(),
    'received_at': now.toIso8601String(),
    'grand_total': '5200000.0000',
    'invoice_number': null,
    'decision_note': 'سقف اعتبار کافی نیست',
  },
];

Map<String, dynamic> figures(
  String ordered,
  int count,
  String invoiced,
  int inv,
  int customers,
) => {
  'ordered_amount': ordered,
  'ordered_count': count,
  'invoiced_amount': invoiced,
  'invoiced_count': inv,
  'customers': customers,
  'average_order': count == 0
      ? '0'
      : (Decimal.parse(ordered) / Decimal.fromInt(count))
            .toDecimal(scaleOnInfinitePrecision: 0)
            .toString(),
  'rejected_count': 1,
  'pending_count': 2,
  'visits': 21,
  'no_order_reasons': {'closed': 3, 'stocked': 2, 'price': 1},
};

final reportBody = {
  'period': 'month',
  'start': '2026-10-23',
  'end': '2026-11-21',
  'label': 'آبان 1405',
  'current': figures('148200000', 12, '126400000', 10, 9),
  'previous': figures('132300000', 11, '117000000', 9, 10),
  'top_customers': [
    {'id': 'c0', 'name': 'رستوران آفتاب', 'amount': '62000000', 'count': 5},
    {'id': 'c2', 'name': 'کافه نارنج', 'amount': '41000000', 'count': 4},
    {'id': 'c1', 'name': 'بقالی محله', 'amount': '23000000', 'count': 2},
  ],
  'top_items': [
    {
      'id': 'milk',
      'name': 'شیر پرچرب ۱ لیتری',
      'amount': '58000000',
      'count': 9,
    },
    {'id': 'rice', 'name': 'برنج ایرانی', 'amount': '39000000', 'count': 6},
    {
      'id': 'water',
      'name': 'آب معدنی ۱٫۵ لیتری',
      'amount': '17000000',
      'count': 7,
    },
  ],
  'target': '200000000',
  'target_progress': '126400000',
};

final historyBody = {
  'invoices': [
    {
      'id': 'i58',
      'number': 58,
      'kind': 'sale',
      'document_date': '2026-10-24',
      'grand_total': '4200000',
      'line_count': 7,
      'channel': 'shop',
      'visitor_name': null,
    },
    {
      'id': 'i51',
      'number': 51,
      'kind': 'sale',
      'document_date': '2026-10-20',
      'grand_total': '2100000',
      'line_count': 4,
      'channel': 'visitor',
      'visitor_name': 'مریم احمدی',
    },
    {
      'id': 'i41',
      'number': 41,
      'kind': 'sale',
      'document_date': '2026-10-15',
      'grand_total': '3410000',
      'line_count': 2,
      'channel': 'mine',
      'visitor_name': null,
    },
  ],
  'frequent_items': [
    {
      'item_id': 'milk',
      'item_name': 'شیر پرچرب ۱ لیتری',
      'times': 9,
      'last_date': '2026-10-24',
    },
    {
      'item_id': 'water',
      'item_name': 'آب معدنی ۱٫۵ لیتری',
      'times': 7,
      'last_date': '2026-10-20',
    },
  ],
};

final accountBody = {
  'balance': '3150000',
  'credit_limit': '10000000',
  'credit_unlimited': false,
  'available': '6850000',
  'open_cheques': [
    {
      'number': '452100',
      'amount': '1500000',
      'due_date': '2026-11-11',
      'status': 'in_hand',
      'bank_name': 'ملت',
    },
  ],
  'pending_collections': '1000000',
  'statement': <dynamic>[],
};

final notificationsBody = [
  {
    'id': 'n1',
    'kind': 'order_approved',
    'title': 'سفارش ۳ تأیید شد',
    'body': 'کافه نارنج',
    'ref_type': 'order',
    'ref_id': 'o3',
    'created_at': now.subtract(const Duration(minutes: 10)).toIso8601String(),
    'read_at': null,
  },
  {
    'id': 'n2',
    'kind': 'order_rejected',
    'title': 'سفارش ۱ رد شد',
    'body': 'فروشگاه بهار · علت: سقف اعتبار کافی نیست',
    'ref_type': 'order',
    'ref_id': 'o1',
    'created_at': now.subtract(const Duration(days: 1)).toIso8601String(),
    'read_at': null,
  },
  {
    'id': 'n3',
    'kind': 'collection_approved',
    'title': 'وصول ۱۵۰٬۰۰۰ تومان ثبت شد',
    'body': 'سند دریافت ۷۸۱',
    'ref_type': 'collection',
    'ref_id': 'k1',
    'created_at': now.subtract(const Duration(days: 1)).toIso8601String(),
    'read_at': now.toIso8601String(),
  },
  {
    'id': 'n4',
    'kind': 'target_set',
    'title': 'هدف آبان ۱۴۰۵ تعیین شد',
    'body': '۲۰۰٬۰۰۰٬۰۰۰ تومان',
    'ref_type': 'target',
    'ref_id': 't1',
    'created_at': now.subtract(const Duration(days: 2)).toIso8601String(),
    'read_at': now.toIso8601String(),
  },
];

final collectionsBody = [
  {
    'id': 'k1',
    'customer_id': 'c0',
    'customer_name': 'رستوران آفتاب',
    'method': 'cheque',
    'amount': '1500000',
    'collected_at': now.subtract(const Duration(days: 1)).toIso8601String(),
    'cheque_number': '452100',
    'status': 'approved',
    'decision_note': null,
    'treasury_document_number': 781,
  },
  {
    'id': 'k2',
    'customer_id': 'c0',
    'customer_name': 'رستوران آفتاب',
    'method': 'cash',
    'amount': '1000000',
    'collected_at': now.toIso8601String(),
    'cheque_number': null,
    'status': 'pending',
    'decision_note': null,
    'treasury_document_number': null,
  },
];

Future<void> loadFonts() async {
  final vazir = FontLoader('Vazirmatn');
  for (final w in ['Regular', 'Medium', 'Bold', 'ExtraBold']) {
    vazir.addFont(rootBundle.load('assets/fonts/Vazirmatn-$w.ttf'));
  }
  await vazir.load();
  final root = Platform.environment['FLUTTER_ROOT'] ?? '/opt/flutter';
  final icons = File(
    '$root/bin/cache/artifacts/material_fonts/MaterialIcons-Regular.otf',
  );
  if (icons.existsSync()) {
    final loader = FontLoader('MaterialIcons')
      ..addFont(Future.value(ByteData.sublistView(icons.readAsBytesSync())));
    await loader.load();
  }
}

Session session() => Session(
  server: 'https://erp.example.ir',
  userId: 'u1',
  username: 'visitor1',
  fullName: 'رضا کریمی',
  access: 'a',
  accessExpiresAt: DateTime.now().toUtc().add(const Duration(minutes: 10)),
  refresh: 'r',
  refreshExpiresAt: DateTime.now().toUtc().add(const Duration(days: 20)),
);

// Consistent with the cart in the order test: milk 2 boxes 2 640 000, water 5 packs
// 450 000 (promotion −110 000), rice 2.5 kg 3 625 000 (VAT-exempt); VAT 10 % exclusive.
final quoteBody = {
  'lines': [],
  'subtotal': '6715000.0000',
  'discount_total': '110000.0000',
  'tax_total': '298000.0000',
  'grand_total': '6903000.0000',
  'warnings': [],
  'credit_limit': '10000000.0000',
  'balance': '3150000.0000',
  'available_after': '-53000.0000',
};

Future<AppState> makeState(WidgetTester tester, {bool online = true}) async {
  late AppState state;
  await tester.runAsync(() async {
    final db = await LocalDb.open(databaseFactoryFfi, inMemoryDatabasePath);
    await db.put('bootstrap', jsonEncode(bootstrap));
    await db.put('synced_at', now.toIso8601String());
    for (final (id, file) in [
      ('pm1', 'milk'),
      ('pm2', 'milk-box'),
      ('pw1', 'water'),
    ]) {
      final bytes = File('test/fixtures/$file.jpg').readAsBytesSync();
      await db.putImage(id, 'thumb', bytes);
      await db.putImage(id, 'large', bytes);
    }
    await db.saveOrders('u1', orders);
    final store = MemoryTokenStore()
      ..session = session()
      ..settings = const ConnectionSettings(
        host: 'erp.example.ir',
        port: 8443,
        username: 'visitor1',
        password: 'Visitor-Pass-1',
      );
    final client = MockClient((req) async {
      http.Response ok(Object body) => http.Response(
        jsonEncode(body),
        200,
        headers: {'content-type': 'application/json; charset=utf-8'},
      );
      final p = req.url.path;
      if (p.endsWith('/quote')) return ok(quoteBody);
      if (p.endsWith('/report')) return ok(reportBody);
      if (p.endsWith('/history')) return ok(historyBody);
      if (p.endsWith('/account')) return ok(accountBody);
      throw http.ClientException('offline');
    });
    final api = ApiClient(store, client: client);
    await api.restore();
    state = AppState(api: api, db: db);
    state.settings = await store.loadSettings();
    if (!online) {
      await db.addOutbox('p1', 'u1', 'order', {
        'id': 'p1',
        'customer_id': 'c0',
        'lines': [
          {'item_id': 'milk', 'qty': '24'},
          {'item_id': 'water', 'qty': '10'},
        ],
      }, at: now);
      await db.addOutbox('p2', 'u1', 'visit', {
        'id': 'p2',
        'customer_id': 'c1',
        'outcome': 'closed',
      }, at: now);
      await db.addOutbox('p3', 'u1', 'order', {
        'id': 'p3',
        'customer_id': 'c3',
        'lines': [
          {'item_id': 'rice', 'qty': '5'},
        ],
      }, at: now);
      await db.markFailed('p3', 'این مشتری به شما تخصیص داده نشده است');
    }
    await db.put('notifications:u1', jsonEncode(notificationsBody));
    await db.put('collections:u1', jsonEncode(collectionsBody));
    await state.reload();
    state.online = online;
  });
  return state;
}

Widget frame(Widget child, {Brightness brightness = Brightness.light}) =>
    MaterialApp(
      debugShowCheckedModeBanner: false,
      locale: const Locale('fa', 'IR'),
      supportedLocales: const [Locale('fa', 'IR')],
      localizationsDelegates: GlobalMaterialLocalizations.delegates,
      theme: visitorTheme(brightness: brightness),
      home: child,
    );

/// Real shadows for the pictures; Flutter checks the flag is restored by the test's end.
void screenTest(String name, Future<void> Function(WidgetTester) body) {
  testWidgets(name, (tester) async {
    try {
      await body(tester);
    } finally {
      debugDisableShadows = true;
    }
  });
}

void main() {
  sqfliteFfiInit();

  setUp(() async {
    TestWidgetsFlutterBinding.ensureInitialized();
    // A phone has no keyboard focus ring.
    FocusManager.instance.highlightStrategy =
        FocusHighlightStrategy.alwaysTouch;
  });

  /// Lets the photos load from the phone's store and decode before a screenshot.
  Future<void> settleImages(WidgetTester tester) async {
    await tester.runAsync(
      () => Future<void>.delayed(const Duration(milliseconds: 150)),
    );
    await tester.pump();
    await tester.runAsync(() async {
      for (final e in find.byType(Image).evaluate()) {
        await precacheImage((e.widget as Image).image, e);
      }
    });
    await tester.pump(const Duration(milliseconds: 300));
  }

  Future<void> shot(
    WidgetTester tester,
    Widget w,
    String? name, {
    Brightness brightness = Brightness.light,
  }) async {
    tester.view.physicalSize = const Size(1080, 2340);
    tester.view.devicePixelRatio = 2.75;
    FocusManager.instance.highlightStrategy =
        FocusHighlightStrategy.alwaysTouch;
    // Tests draw shadows as solid outlines unless told otherwise.
    debugDisableShadows = false;
    addTearDown(tester.view.reset);
    await tester.pumpWidget(frame(w, brightness: brightness));
    await tester.pump(const Duration(milliseconds: 300));
    await settleImages(tester);
    if (name == null) return;
    await expectLater(
      find.byType(MaterialApp),
      matchesGoldenFile('goldens/$name.png'),
    );
  }

  screenTest('login', (tester) async {
    await loadFonts();
    final state = await makeState(tester);
    await shot(tester, LoginScreen(state: state), '103-app-login');
    expect(find.text('erp.example.ir : 8443'), findsOneWidget);
    expect(find.text('ذخیره شده'), findsOneWidget);
  });

  screenTest('connection settings', (tester) async {
    await loadFonts();
    final state = await makeState(tester);
    await shot(tester, LoginScreen(state: state), null);
    await tester.tap(find.text('تنظیمات اتصال'));
    for (var i = 0; i < 4; i++) {
      await tester.pump(const Duration(milliseconds: 200));
    }
    expect(find.text('ذخیره و ورود'), findsOneWidget);
    expect(find.text('8443'), findsOneWidget);
    await expectLater(
      find.byType(MaterialApp),
      matchesGoldenFile('goldens/122-app-connection-settings.png'),
    );
  });

  screenTest('first start: nothing set yet', (tester) async {
    await loadFonts();
    final state = await makeState(tester);
    state.settings = null;
    await shot(tester, LoginScreen(state: state), null);
    expect(find.text('تنظیم نشده'), findsOneWidget);
  });

  screenTest('dark mode', (tester) async {
    await loadFonts();
    final state = await makeState(tester);
    await shot(
      tester,
      HomeScreen(state: state, now: now),
      '123-app-customers-dark',
      brightness: Brightness.dark,
    );
  });

  screenTest('today\'s route of customers', (tester) async {
    await loadFonts();
    final state = await makeState(tester);
    await shot(
      tester,
      HomeScreen(state: state, now: now),
      '104-app-customers-today',
    );
    expect(find.text('فروشگاه بهار'), findsNothing); // visited on Mondays
  });

  screenTest('customer card', (tester) async {
    await loadFonts();
    final state = await makeState(tester);
    await shot(
      tester,
      CustomerScreen(state: state, customer: state.catalog!.customers.first),
      '105-app-customer',
    );
  });

  screenTest('writing an order, with the server\'s price', (tester) async {
    await loadFonts();
    final state = await makeState(tester);
    final cat = state.catalog!;
    final lines = [
      DraftLine(cat.item('milk')!, 'box', Decimal.fromInt(2)),
      DraftLine(cat.item('water')!, 'pack', Decimal.fromInt(5)),
      DraftLine(cat.item('rice')!, 'kg', Decimal.parse('2.5')),
    ];
    await shot(
      tester,
      OrderScreen(state: state, customer: cat.customers.first, initial: lines),
      '106-app-order-estimate',
    );
    await tester.runAsync(() async {
      await tester.tap(find.text('قیمت قطعی از سرور'));
      await Future<void>.delayed(const Duration(milliseconds: 50));
    });
    await tester.pump();
    await tester.drag(find.byType(ListView), const Offset(0, -420));
    expect(find.text('مبلغ قطعی'), findsOneWidget);
    await tester.pump();
    await expectLater(
      find.byType(MaterialApp),
      matchesGoldenFile('goldens/107-app-order-quote.png'),
    );
  });

  screenTest('choosing items by photo, and showing one large', (tester) async {
    await loadFonts();
    final state = await makeState(tester);
    final cat = state.catalog!;
    await shot(
      tester,
      OrderScreen(state: state, customer: cat.customers.first),
      null,
    );
    await tester.tap(find.text('افزودن کالا'));
    await tester.pump(const Duration(milliseconds: 500));
    await settleImages(tester);
    expect(find.byType(GridView), findsOneWidget);
    await expectLater(
      find.byType(MaterialApp),
      matchesGoldenFile('goldens/120-app-item-photos.png'),
    );

    await tester.tap(find.text('شیر پرچرب ۱ لیتری'));
    for (var i = 0; i < 4; i++) {
      await tester.pump(const Duration(milliseconds: 400));
    }
    await settleImages(tester);
    expect(find.text('افزودن به سفارش'), findsOneWidget);
    await tester.tap(find.byTooltip('زیاد'));
    await tester.pump();
    await expectLater(
      find.byType(MaterialApp),
      matchesGoldenFile('goldens/121-app-item-photo-large.png'),
    );

    // Added from the photo: 2 pieces of milk in the order.
    await tester.tap(find.text('افزودن به سفارش'));
    for (var i = 0; i < 4; i++) {
      await tester.pump(const Duration(milliseconds: 400));
    }
    await settleImages(tester);
    expect(find.byType(ItemGalleryScreen), findsNothing);
    expect(find.text('شیر پرچرب ۱ لیتری'), findsOneWidget);
    expect(find.text('۲'), findsOneWidget);
  });

  screenTest('orders and their status', (tester) async {
    await loadFonts();
    final state = await makeState(tester);
    await shot(tester, HomeScreen(state: state, now: now), null);
    await tester.tap(find.text('سفارش‌ها'));
    await tester.pump(const Duration(milliseconds: 300));
    await expectLater(
      find.byType(MaterialApp),
      matchesGoldenFile('goldens/108-app-orders.png'),
    );
  });

  screenTest('offline queue', (tester) async {
    await loadFonts();
    final state = await makeState(tester, online: false);
    await shot(tester, HomeScreen(state: state, now: now), null);
    await tester.tap(find.text('صف'));
    await tester.pump(const Duration(milliseconds: 300));
    expect(find.text('ارسال دوباره'), findsOneWidget);
    await expectLater(
      find.byType(MaterialApp),
      matchesGoldenFile('goldens/109-app-offline-queue.png'),
    );
  });

  screenTest('a server not yet updated to v2', (tester) async {
    await loadFonts();
    final state = await makeState(tester, online: false);
    await tester.runAsync(() async {
      await state.db.put('server_api_level', '1');
      await state.reload();
    });
    await shot(tester, HomeScreen(state: state, now: now), null);
    await tester.tap(find.text('صف'));
    await tester.pump(const Duration(milliseconds: 300));
    expect(find.textContaining('نسخه‌ی سرور قدیمی است'), findsOneWidget);
    await expectLater(
      find.byType(MaterialApp),
      matchesGoldenFile('goldens/131-app-server-outdated.png'),
    );
  });

  screenTest('search across customers, items and orders', (tester) async {
    await loadFonts();
    final state = await makeState(tester);
    await shot(
      tester,
      SearchScreen(state: state, initial: 'شیر'),
      '124-app-search',
    );
    expect(find.text('کالاها'), findsOneWidget);
    expect(find.text('سفارش‌ها'), findsOneWidget); // milk is in order 2
  });

  screenTest('order detail with repeat and share', (tester) async {
    await loadFonts();
    final state = await makeState(tester);
    await shot(
      tester,
      OrderDetailScreen(
        state: state,
        order: state.orders.firstWhere((o) => o['id'] == 'o2'),
      ),
      '125-app-order-detail',
    );
    expect(find.text('تکرار این سفارش'), findsOneWidget);
  });

  screenTest('my report for the month', (tester) async {
    await loadFonts();
    final state = await makeState(tester);
    await shot(tester, HomeScreen(state: state, now: now), null);
    await tester.tap(find.text('گزارش من'));
    for (var i = 0; i < 3; i++) {
      await tester.runAsync(
        () => Future<void>.delayed(const Duration(milliseconds: 50)),
      );
      await tester.pump(const Duration(milliseconds: 200));
    }
    expect(find.text('آبان ۱۴۰۵'), findsOneWidget);
    expect(find.text('۶۳٪'), findsOneWidget);
    await expectLater(
      find.byType(MaterialApp),
      matchesGoldenFile('goldens/127-app-report.png'),
    );
  });

  screenTest('a cheque collection', (tester) async {
    await loadFonts();
    final state = await makeState(tester);
    await shot(
      tester,
      CollectionScreen(state: state, customer: state.catalog!.customers.first),
      null,
    );
    await tester.tap(find.text('چک'));
    for (var i = 0; i < 4; i++) {
      await tester.pump(const Duration(milliseconds: 300));
    }
    await tester.enterText(
      find.widgetWithText(TextField, 'مبلغ (تومان)'),
      '150000',
    );
    await tester.enterText(
      find.widgetWithText(TextField, 'شماره‌ی چک'),
      '452100',
    );
    // Let the labels finish floating above the typed text.
    FocusManager.instance.primaryFocus?.unfocus();
    for (var i = 0; i < 3; i++) {
      await tester.pump(const Duration(milliseconds: 300));
    }
    await expectLater(
      find.byType(MaterialApp),
      matchesGoldenFile('goldens/128-app-collection.png'),
    );
  });

  screenTest('a new customer request', (tester) async {
    await loadFonts();
    final state = await makeState(tester);
    await shot(tester, NewCustomerScreen(state: state), null);
    await tester.enterText(
      find.widgetWithText(TextField, 'نام فروشگاه'),
      'سوپر ستاره',
    );
    await tester.enterText(
      find.widgetWithText(TextField, 'نام مالک'),
      'حسن رضایی',
    );
    await tester.enterText(
      find.widgetWithText(TextField, 'موبایل'),
      '09123456789',
    );
    // Let the labels finish floating above the typed text.
    FocusManager.instance.primaryFocus?.unfocus();
    for (var i = 0; i < 3; i++) {
      await tester.pump(const Duration(milliseconds: 300));
    }
    await expectLater(
      find.byType(MaterialApp),
      matchesGoldenFile('goldens/129-app-new-customer.png'),
    );
  });

  screenTest('notifications', (tester) async {
    await loadFonts();
    final state = await makeState(tester);
    await shot(
      tester,
      NotificationsScreen(state: state),
      '130-app-notifications',
    );
    expect(find.text('تازه'), findsNWidgets(2));
  });
}
