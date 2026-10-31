/**
 * Amounts in Persian words for forms and printed invoices («مبلغ به حروف»).
 * Integer strings only (BigInt), never floats.
 */
import type { DisplayCurrency } from "./format";
import { formatMoney, toEnDigits } from "./format";
import { inputToRials } from "./money";

const ONES = ["", "یک", "دو", "سه", "چهار", "پنج", "شش", "هفت", "هشت", "نه"];
const TEENS = ["ده", "یازده", "دوازده", "سیزده", "چهارده", "پانزده", "شانزده", "هفده", "هجده", "نوزده"];
const TENS = ["", "", "بیست", "سی", "چهل", "پنجاه", "شصت", "هفتاد", "هشتاد", "نود"];
const HUNDREDS = ["", "صد", "دویست", "سیصد", "چهارصد", "پانصد", "ششصد", "هفتصد", "هشتصد", "نهصد"];
const SCALES = ["", "هزار", "میلیون", "میلیارد", "هزار میلیارد", "میلیون میلیارد"];

function belowThousand(n: number): string {
  const parts: string[] = [];
  const h = Math.floor(n / 100);
  const rest = n % 100;
  if (h) parts.push(HUNDREDS[h]);
  if (rest >= 10 && rest < 20) parts.push(TEENS[rest - 10]);
  else {
    const t = Math.floor(rest / 10);
    const o = rest % 10;
    if (t) parts.push(TENS[t]);
    if (o) parts.push(ONES[o]);
  }
  return parts.join(" و ");
}

/** "1205000" → «یک میلیون و دویست و پنج هزار»; "0" → «صفر». */
export function numberToWords(value: string | bigint): string {
  let n = typeof value === "bigint" ? value : BigInt(toEnDigits(value).replace(/[,٬\s]/g, "").split(".")[0] || "0");
  if (n === 0n) return "صفر";
  const negative = n < 0n;
  if (negative) n = -n;
  const groups: string[] = [];
  let scale = 0;
  while (n > 0n) {
    const chunk = Number(n % 1000n);
    if (chunk) {
      const words = belowThousand(chunk);
      groups.unshift(scale ? `${words} ${SCALES[scale] ?? ""}`.trim() : words);
    }
    n /= 1000n;
    scale += 1;
  }
  return (negative ? "منفی " : "") + groups.join(" و ");
}

/** An amount typed in the display currency, in words and in the other currency:
 * «یک میلیون و دویست هزار تومان · ۱۲٬۰۰۰٬۰۰۰ ریال». Null while empty or invalid. */
export function amountHint(input: string, currency: DisplayCurrency): string | null {
  if (!input || !/\d/.test(input)) return null;
  const rials = inputToRials(input, currency);
  if (rials === null) return null;
  const whole = rials.split(".")[0];
  const shown = currency === "IRT" ? (BigInt(whole) / 10n).toString() : whole;
  const words = `${numberToWords(shown)} ${currency === "IRT" ? "تومان" : "ریال"}`;
  const other = formatMoney(rials, currency === "IRT" ? "IRR" : "IRT");
  return `${words} · ${other}`;
}
