import 'package:decimal/decimal.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:nextcam_visitor/src/api.dart';
import 'package:nextcam_visitor/src/format.dart';
import 'package:nextcam_visitor/src/models.dart';

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

  test('Jalali to Gregorian is the inverse, every day for 12 years', () {
    expect(fromJalali(1405, 8, 7), DateTime.utc(2026, 10, 29));
    expect(fromJalali(1403, 12, 30), DateTime.utc(2025, 3, 20)); // leap Esfand
    expect(jalaliMonthDays(1403, 12), 30);
    expect(jalaliMonthDays(1404, 12), 29);
    var d = DateTime.utc(2020, 1, 1);
    while (d.isBefore(DateTime.utc(2032, 1, 1))) {
      final (y, m, day) = toJalali(d);
      expect(fromJalali(y, m, day), d, reason: '$d');
      d = d.add(const Duration(days: 1));
    }
  });

  test('typed amounts in toman become rials', () {
    expect(rialsFromInput('۱۲٬۵۰۰', 'IRT'), Decimal.parse('125000'));
    expect(rialsFromInput('125000', 'IRR'), Decimal.parse('125000'));
    expect(rialsFromInput('0', 'IRT'), isNull);
    expect(rialsFromInput('abc', 'IRT'), isNull);
  });

  test('search ignores Arabic letters, Persian digits and spaces', () {
    expect(searchKey('حمل‌ونقل كاوه ۱۲'), searchKey('حمل ونقل کاوه 12'));
  });
}
