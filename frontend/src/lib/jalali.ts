import { isValidJalaaliDate, toGregorian, toJalaali } from "jalaali-js";
import { toEnDigits, toFaDigits } from "./format";

const pad = (n: number) => String(n).padStart(2, "0");

/** "1405/07/19" (Persian or Latin digits, / or -) → "2026-10-11"; null if invalid. */
export function jalaliToIso(input: string): string | null {
  const m = toEnDigits(input.trim()).match(/^(\d{4})[/-](\d{1,2})[/-](\d{1,2})$/);
  if (!m) return null;
  const [jy, jm, jd] = [Number(m[1]), Number(m[2]), Number(m[3])];
  if (!isValidJalaaliDate(jy, jm, jd)) return null;
  const g = toGregorian(jy, jm, jd);
  return `${g.gy}-${pad(g.gm)}-${pad(g.gd)}`;
}

/** "2026-10-11" → "1405/07/19" (Latin digits, for editing). */
export function isoToJalali(iso: string): string {
  const [y, m, d] = iso.slice(0, 10).split("-").map(Number);
  const j = toJalaali(y, m, d);
  return `${j.jy}/${pad(j.jm)}/${pad(j.jd)}`;
}

/** Display form with Persian digits. */
export function isoToJalaliFa(iso: string): string {
  return toFaDigits(isoToJalali(iso));
}

export function todayIso(): string {
  const now = new Date();
  // Tehran calendar day, independent of the browser's time zone.
  const parts = new Intl.DateTimeFormat("en-CA", { timeZone: "Asia/Tehran" }).format(now);
  return parts;
}
