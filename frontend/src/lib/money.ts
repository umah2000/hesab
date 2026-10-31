/**
 * Money entry. Users type in the display currency (usually toman); the API
 * takes rials as a decimal string (ADR-0008). String math only — no floats.
 */
import type { DisplayCurrency } from "./format";
import { toEnDigits } from "./format";

/** User text → rials string, or null if not a valid non-negative amount. */
export function inputToRials(input: string, currency: DisplayCurrency): string | null {
  const clean = toEnDigits(input).replace(/[,٬\s]/g, "").replace("٫", ".");
  if (clean === "") return "0";
  const m = clean.match(/^(\d+)(?:\.(\d+))?$/);
  if (!m) return null;
  let intPart = m[1].replace(/^0+(?=\d)/, "");
  let frac = m[2] ?? "";
  if (currency === "IRT") {
    // ×10: shift one fractional digit into the integer part.
    intPart = intPart + (frac[0] ?? "0");
    frac = frac.slice(1);
  }
  if (frac.length > 4) return null;
  intPart = intPart.replace(/^0+(?=\d)/, "");
  if (intPart.length > 15) return null;
  return frac ? `${intPart}.${frac}` : intPart;
}

/** Rials string from the API → editable text in the display currency. */
export function rialsToInput(rials: string, currency: DisplayCurrency): string {
  const [i, f = ""] = rials.replace(/^-/, "").split(".");
  const frac = f.replace(/0+$/, "");
  if (currency === "IRR") return frac ? `${i}.${frac}` : i;
  const intPart = i.length > 1 ? i.slice(0, -1) : "0";
  const tf = (i.slice(-1) + frac).replace(/0+$/, "");
  return tf ? `${intPart}.${tf}` : intPart;
}

/** Group digits while typing: "1234567" → "1,234,567" (keeps a decimal part). */
export function groupDigits(input: string): string {
  const clean = toEnDigits(input).replace(/[,٬\s]/g, "");
  const [i, f] = clean.split(".");
  const grouped = i.replace(/\B(?=(\d{3})+(?!\d))/g, ",");
  return f !== undefined ? `${grouped}.${f}` : grouped;
}

/** Sum of decimal strings without floats (BigInt on 4 fixed decimals). */
export function sumRials(values: string[]): string {
  const total = values.reduce((acc, v) => acc + toUnits(v), 0n);
  return fromUnits(total);
}

export function compareRials(a: string, b: string): number {
  const d = toUnits(a) - toUnits(b);
  return d === 0n ? 0 : d > 0n ? 1 : -1;
}

export function subRials(a: string, b: string): string {
  return fromUnits(toUnits(a) - toUnits(b));
}

function toUnits(v: string): bigint {
  const neg = v.startsWith("-");
  const [i, f = ""] = v.replace("-", "").split(".");
  const units = BigInt(i || "0") * 10000n + BigInt((f + "0000").slice(0, 4));
  return neg ? -units : units;
}

function fromUnits(u: bigint): string {
  const neg = u < 0n;
  const abs = neg ? -u : u;
  const s = `${abs / 10000n}.${String(abs % 10000n).padStart(4, "0")}`;
  return neg ? `-${s}` : s;
}

/** Rials ÷ quantity (3 decimals), rounded half up to whole rials; "0" for a zero quantity. */
export function divRialsByQty(rials: string, qty: string): string {
  const [qi, qf = ""] = qty.replace("-", "").split(".");
  const q = BigInt(qi || "0") * 1000n + BigInt((qf + "000").slice(0, 3));
  if (q === 0n) return "0";
  // units are rials × 10⁴; × 1000 for the quantity's decimals.
  const num = toUnits(rials) * 1000n;
  const whole = (num / q + 5000n) / 10000n;
  return whole.toString();
}

export function addRials(a: string, b: string): string {
  return fromUnits(toUnits(a) + toUnits(b));
}
