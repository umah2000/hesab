/// Display formatting: Persian digits, toman/rial, Jalali dates.
///
/// Amounts arrive from the server as decimal strings in rials and stay [Decimal]
/// here; a binary double never touches money (ADR-0008).
library;

import 'package:decimal/decimal.dart';

const _faDigits = '۰۱۲۳۴۵۶۷۸۹';

String faDigits(Object value) => value.toString().replaceAllMapped(
  RegExp(r'[0-9]'),
  (m) => _faDigits[int.parse(m[0]!)],
);

/// Persian or Arabic-Indic digits typed on a phone keyboard → Latin.
String enDigits(String s) {
  const ar = '٠١٢٣٤٥٦٧٨٩';
  final b = StringBuffer();
  for (final ch in s.runes) {
    final c = String.fromCharCode(ch);
    final fa = _faDigits.indexOf(c);
    final a = ar.indexOf(c);
    b.write(fa >= 0 ? '$fa' : (a >= 0 ? '$a' : c));
  }
  return b.toString();
}

final _ten = Decimal.fromInt(10);

String _group(String digits) {
  final out = StringBuffer();
  for (var i = 0; i < digits.length; i++) {
    if (i > 0 && (digits.length - i) % 3 == 0) out.write('٬');
    out.write(digits[i]);
  }
  return out.toString();
}

/// A rial amount shown in the organisation's display currency (`IRT` = toman).
String money(Decimal rials, String currency, {bool unit = false}) {
  var v = currency == 'IRT'
      ? (rials / _ten).toDecimal(scaleOnInfinitePrecision: 4)
      : rials;
  final neg = v < Decimal.zero;
  if (neg) v = -v;
  final whole = v.truncate();
  final frac = v - whole;
  var text = _group(whole.toBigInt().toString());
  if (frac != Decimal.zero) {
    final f = frac.toStringAsFixed(1).split('.').last;
    if (f != '0') text = '$text٫$f';
  }
  final label = unit ? (currency == 'IRT' ? ' تومان' : ' ریال') : '';
  // Left-to-right isolate: the minus stays in front of the digits inside RTL text.
  final number = neg ? '\u2066−${faDigits(text)}\u2069' : faDigits(text);
  return '$number$label';
}

Decimal dec(String s) => Decimal.parse(s);

/// A quantity without trailing zeros, Persian digits: "2.500" → "۲٫۵".
String qty(String q) {
  var s = Decimal.parse(q).toString();
  if (s.contains('.')) {
    s = s.replaceFirst(RegExp(r'0+$'), '').replaceFirst(RegExp(r'\.$'), '');
  }
  return faDigits(s.replaceAll('.', '٫'));
}

/// Gregorian → Jalali (the standard arithmetic algorithm, as in nextcam_core.jalali).
(int, int, int) toJalali(DateTime d) {
  const gDays = [0, 31, 59, 90, 120, 151, 181, 212, 243, 273, 304, 334];
  final gy = d.year, gm = d.month, gd = d.day;
  final gy2 = gm > 2 ? gy + 1 : gy;
  var days =
      355666 +
      365 * gy +
      (gy2 + 3) ~/ 4 -
      (gy2 + 99) ~/ 100 +
      (gy2 + 399) ~/ 400 +
      gd +
      gDays[gm - 1];
  var jy = -1595 + 33 * (days ~/ 12053);
  days %= 12053;
  jy += 4 * (days ~/ 1461);
  days %= 1461;
  if (days > 365) {
    jy += (days - 1) ~/ 365;
    days = (days - 1) % 365;
  }
  final int jm, jd;
  if (days < 186) {
    jm = 1 + days ~/ 31;
    jd = 1 + days % 31;
  } else {
    jm = 7 + (days - 186) ~/ 30;
    jd = 1 + (days - 186) % 30;
  }
  return (jy, jm, jd);
}

/// Jalali → Gregorian (the inverse of [toJalali]); a UTC date at midnight.
DateTime fromJalali(int jy, int jm, int jd) {
  final jy2 = jy + 1595;
  var days =
      -355668 +
      365 * jy2 +
      (jy2 ~/ 33) * 8 +
      ((jy2 % 33) + 3) ~/ 4 +
      jd +
      (jm < 7 ? (jm - 1) * 31 : (jm - 7) * 30 + 186);
  var gy = 400 * (days ~/ 146097);
  days %= 146097;
  if (days > 36524) {
    days--;
    gy += 100 * (days ~/ 36524);
    days %= 36524;
    if (days >= 365) days++;
  }
  gy += 4 * (days ~/ 1461);
  days %= 1461;
  if (days > 365) {
    gy += (days - 1) ~/ 365;
    days = (days - 1) % 365;
  }
  var gd = days + 1;
  final leap = (gy % 4 == 0 && gy % 100 != 0) || gy % 400 == 0;
  final months = [31, leap ? 29 : 28, 31, 30, 31, 30, 31, 31, 30, 31, 30, 31];
  var gm = 0;
  while (gm < 12 && gd > months[gm]) {
    gd -= months[gm];
    gm++;
  }
  return DateTime.utc(gy, gm + 1, gd);
}

/// Days in a Jalali month (Esfand: 29, or 30 in a leap year).
int jalaliMonthDays(int jy, int jm) {
  if (jm <= 6) return 31;
  if (jm <= 11) return 30;
  final next = fromJalali(jy + 1, 1, 1);
  return next.difference(fromJalali(jy, 12, 1)).inDays;
}

const jalaliMonths = [
  'فروردین',
  'اردیبهشت',
  'خرداد',
  'تیر',
  'مرداد',
  'شهریور',
  'مهر',
  'آبان',
  'آذر',
  'دی',
  'بهمن',
  'اسفند',
];

/// Iran has kept UTC+03:30 all year since 2022.
DateTime tehran(DateTime t) =>
    t.toUtc().add(const Duration(hours: 3, minutes: 30));

String jalaliDate(DateTime t) {
  final (y, m, d) = toJalali(tehran(t));
  return faDigits(
    '$y/${m.toString().padLeft(2, '0')}/${d.toString().padLeft(2, '0')}',
  );
}

String jalaliDateTime(DateTime t) {
  final local = tehran(t);
  final hh = local.hour.toString().padLeft(2, '0');
  final mm = local.minute.toString().padLeft(2, '0');
  return '${jalaliDate(t)}  ${faDigits('$hh:$mm')}';
}

/// 0 = Saturday … 6 = Friday (the Iranian week), as the server stores visit days.
int iranWeekday(DateTime t) => (tehran(t).weekday + 1) % 7;

const weekdayNames = [
  'شنبه',
  'یکشنبه',
  'دوشنبه',
  'سه‌شنبه',
  'چهارشنبه',
  'پنجشنبه',
  'جمعه',
];

/// An amount typed in the display currency (toman or rial) → rials; null if invalid.
Decimal? rialsFromInput(String raw, String currency) {
  final t = enDigits(raw)
      .replaceAll(RegExp(r'[٬,\s]'), '')
      .replaceAll('٫', '.');
  final v = Decimal.tryParse(t);
  if (v == null || v <= Decimal.zero) return null;
  return currency == 'IRT' ? (v * _ten).round() : v.round();
}

/// A server date (yyyy-mm-dd) in Jalali.
String jalaliDay(String isoDate) =>
    jalaliDate(DateTime.parse('${isoDate}T12:00:00Z'));
