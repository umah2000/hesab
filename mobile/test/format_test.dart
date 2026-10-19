import 'package:decimal/decimal.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:nextcam_visitor/src/api.dart';
import 'package:nextcam_visitor/src/format.dart';

void main() {
  test('money: rials shown as toman with Persian digits, never a double', () {
    expect(money(Decimal.parse('1100000.0000'), 'IRT'), '۱۱۰٬۰۰۰');
    expect(money(Decimal.parse('10323'), 'IRT'), '۱٬۰۳۲٫۳');
    expect(
      money(Decimal.parse('-50000'), 'IRR', unit: true),
      '\u2066−۵۰٬۰۰۰\u2069 ریال',
    );
    expect(money(Decimal.parse('0'), 'IRT', unit: true), '۰ تومان');
  });

  test('quantities drop trailing zeros', () {
    expect(qty('2.000'), '۲');
    expect(qty('0.750'), '۰٫۷۵');
  });

  test('Jalali dates and the Iranian week', () {
    expect(toJalali(DateTime.utc(2026, 10, 15)), (1405, 7, 23));
    expect(toJalali(DateTime.utc(2026, 3, 21)), (1405, 1, 1));
    expect(toJalali(DateTime.utc(2025, 3, 20)), (1403, 12, 30));
    // 2026-10-17 is a Saturday (0); 23:00 UTC Friday is already Saturday in Tehran.
    expect(iranWeekday(DateTime.utc(2026, 10, 17, 9)), 0);
    expect(iranWeekday(DateTime.utc(2026, 10, 16, 23)), 0);
    expect(
      jalaliDateTime(DateTime.utc(2026, 10, 15, 6, 45)),
      '۱۴۰۵/۰۷/۲۳  ۱۰:۱۵',
    );
  });

  test('server address: HTTPS required outside development', () {
    expect(
      normalizeServer('erp.example.ir/', allowHttp: false),
      'https://erp.example.ir',
    );
    expect(
      () => normalizeServer('http://192.168.1.10:8080', allowHttp: false),
      throwsA(isA<ApiException>()),
    );
    expect(
      normalizeServer('http://192.168.1.10:8080', allowHttp: true),
      'http://192.168.1.10:8080',
    );
  });

  test('typed digits from a Persian keyboard', () {
    expect(enDigits('۱۲۳٤'), '1234');
  });
}
