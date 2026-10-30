import 'package:flutter/material.dart';

import '../format.dart';

/// A Jalali date chooser (year, month, day); returns a UTC date or null.
Future<DateTime?> pickJalaliDate(BuildContext context, {DateTime? initial}) {
  final (y0, m0, d0) = toJalali(tehran(initial ?? DateTime.now()));
  var y = y0, m = m0, d = d0;
  return showDialog<DateTime>(
    context: context,
    builder: (c) => StatefulBuilder(
      builder: (c, set) {
        final days = jalaliMonthDays(y, m);
        if (d > days) d = days;
        return AlertDialog(
          title: const Text('تاریخ'),
          content: Row(
            children: [
              Expanded(
                child: DropdownButtonFormField<int>(
                  initialValue: d,
                  decoration: const InputDecoration(labelText: 'روز'),
                  items: [
                    for (var i = 1; i <= days; i++)
                      DropdownMenuItem(value: i, child: Text(faDigits(i))),
                  ],
                  onChanged: (v) => set(() => d = v!),
                ),
              ),
              const SizedBox(width: 8),
              Expanded(
                flex: 2,
                child: DropdownButtonFormField<int>(
                  initialValue: m,
                  decoration: const InputDecoration(labelText: 'ماه'),
                  items: [
                    for (var i = 1; i <= 12; i++)
                      DropdownMenuItem(
                        value: i,
                        child: Text(jalaliMonths[i - 1]),
                      ),
                  ],
                  onChanged: (v) => set(() => m = v!),
                ),
              ),
              const SizedBox(width: 8),
              Expanded(
                flex: 2,
                child: DropdownButtonFormField<int>(
                  initialValue: y,
                  decoration: const InputDecoration(labelText: 'سال'),
                  items: [
                    for (var i = y0 - 1; i <= y0 + 2; i++)
                      DropdownMenuItem(value: i, child: Text(faDigits(i))),
                  ],
                  onChanged: (v) => set(() => y = v!),
                ),
              ),
            ],
          ),
          actions: [
            TextButton(
              onPressed: () => Navigator.pop(c),
              child: const Text('انصراف'),
            ),
            FilledButton(
              onPressed: () => Navigator.pop(c, fromJalali(y, m, d)),
              child: const Text('انتخاب'),
            ),
          ],
        );
      },
    ),
  );
}
