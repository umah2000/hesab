/** Display-only formatting. Values are stored in UTC and rials by the backend (ADR-0008). */

const faDigits = "۰۱۲۳۴۵۶۷۸۹";
const arDigits = "٠١٢٣٤٥٦٧٨٩";

export function toFaDigits(value: string | number): string {
  return String(value).replace(/\d/g, (d) => faDigits[Number(d)]);
}

/** Accept Persian/Arabic digits typed by users and normalise to ASCII. */
export function toEnDigits(value: string): string {
  return value
    .replace(/[۰-۹]/g, (d) => String(faDigits.indexOf(d)))
    .replace(/[٠-٩]/g, (d) => String(arDigits.indexOf(d)));
}

const dateFmt = new Intl.DateTimeFormat("fa-IR-u-ca-persian", {
  year: "numeric",
  month: "2-digit",
  day: "2-digit",
  timeZone: "Asia/Tehran",
});
const timeFmt = new Intl.DateTimeFormat("fa-IR", {
  hour: "2-digit",
  minute: "2-digit",
  hour12: false,
  timeZone: "Asia/Tehran",
});
const weekdayFmt = new Intl.DateTimeFormat("fa-IR", { weekday: "long", timeZone: "Asia/Tehran" });
const dayMonthYearFmt = new Intl.DateTimeFormat("fa-IR-u-ca-persian", {
  year: "numeric",
  month: "long",
  day: "numeric",
  timeZone: "Asia/Tehran",
});

export const formatDate = (iso: string | Date) => dateFmt.format(new Date(iso));
export const formatTime = (iso: string | Date) => timeFmt.format(new Date(iso));
export const formatDateTime = (iso: string | Date) => `${formatDate(iso)}، ${formatTime(iso)}`;
export const formatLongDate = (d: Date) => `${weekdayFmt.format(d)}، ${dayMonthYearFmt.format(d)}`;

export type DisplayCurrency = "IRR" | "IRT";

/**
 * Money arrives as a decimal string in rials. Formatting uses string math only,
 * never floating point.
 */
export function formatMoney(rials: string, currency: DisplayCurrency = "IRT"): string {
  const negative = rials.trim().startsWith("-");
  const [intPart] = rials.replace("-", "").split(".");
  let digits = intPart.replace(/^0+(?=\d)/, "");
  let fraction = "";
  if (currency === "IRT") {
    // 1 toman = 10 rials; a non-zero last rial digit is shown, never silently dropped.
    const last = digits.slice(-1);
    digits = digits.length > 1 ? digits.slice(0, -1) : "0";
    if (last !== "0") fraction = `٫${last}`;
  }
  const grouped = digits.replace(/\B(?=(\d{3})+(?!\d))/g, "٬");
  const unit = currency === "IRT" ? "تومان" : "ریال";
  const number = toFaDigits(grouped + fraction);
  // Left-to-right isolate: inside RTL text the minus stays in front of the digits.
  return `${negative ? `\u2066−${number}\u2069` : number} ${unit}`;
}

export function formatNumber(n: number): string {
  return new Intl.NumberFormat("fa-IR").format(n);
}
