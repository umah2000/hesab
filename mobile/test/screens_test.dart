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
import 'package:nextcam_visitor/src/ui/customer.dart';
import 'package:nextcam_visitor/src/ui/home.dart';
import 'package:nextcam_visitor/src/ui/login.dart';
import 'package:nextcam_visitor/src/ui/order.dart';
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
    'customer_name': 'رستوران آفتاب',
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
    await db.saveOrders('u1', orders);
    final store = MemoryTokenStore()..session = session();
    final client = MockClient((req) async {
      if (req.url.path.endsWith('/quote')) {
        return http.Response(
          jsonEncode(quoteBody),
          200,
          headers: {'content-type': 'application/json; charset=utf-8'},
        );
      }
      throw http.ClientException('offline');
    });
    final api = ApiClient(store, client: client);
    await api.restore();
    state = AppState(api: api, db: db);
    if (!online) {
      await db.addOutbox('p1', 'u1', 'order', {
        'id': 'p1',
        'customer_id': 'c0',
        'lines': [
          {'item_id': 'milk', 'qty': '24'},
          {'item_id': 'water', 'qty': '10'},
        ],
      });
      await db.addOutbox('p2', 'u1', 'visit', {
        'id': 'p2',
        'customer_id': 'c1',
        'outcome': 'closed',
      });
      await db.addOutbox('p3', 'u1', 'order', {
        'id': 'p3',
        'customer_id': 'c3',
        'lines': [
          {'item_id': 'rice', 'qty': '5'},
        ],
      });
      await db.markFailed('p3', 'این مشتری به شما تخصیص داده نشده است');
    }
    await state.reload();
    state.online = online;
  });
  return state;
}

Widget frame(Widget child) => MaterialApp(
  debugShowCheckedModeBanner: false,
  locale: const Locale('fa', 'IR'),
  supportedLocales: const [Locale('fa', 'IR')],
  localizationsDelegates: GlobalMaterialLocalizations.delegates,
  theme: visitorTheme(),
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

  Future<void> shot(WidgetTester tester, Widget w, String? name) async {
    tester.view.physicalSize = const Size(1080, 2340);
    tester.view.devicePixelRatio = 2.75;
    FocusManager.instance.highlightStrategy =
        FocusHighlightStrategy.alwaysTouch;
    // Tests draw shadows as solid outlines unless told otherwise.
    debugDisableShadows = false;
    addTearDown(tester.view.reset);
    await tester.pumpWidget(frame(w));
    await tester.pump(const Duration(milliseconds: 300));
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
    await tester.tap(find.text('صف ارسال'));
    await tester.pump(const Duration(milliseconds: 300));
    expect(find.text('ارسال دوباره'), findsOneWidget);
    await expectLater(
      find.byType(MaterialApp),
      matchesGoldenFile('goldens/109-app-offline-queue.png'),
    );
  });
}
