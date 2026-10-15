/**
 * A USB barcode scanner is a keyboard: with the Windows input language on Persian,
 * the same key presses arrive as Persian letters. These are the unshifted letter keys
 * expected to be identical in the Windows "Persian" and the Persian standard
 * (ISIRI 9147) layouts; keys known to differ (e.g. M, \, [, ], ;, ') and all shifted
 * keys are deliberately left out. Digits arrive as Persian digits and are
 * handled by toEnDigits. To be confirmed with the shop's real scanner (test plan §3).
 */
const PERSIAN_TO_LATIN: Record<string, string> = {
  ض: "q", ص: "w", ث: "e", ق: "r", ف: "t", غ: "y", ع: "u", ه: "i", خ: "o", ح: "p",
  ش: "a", س: "s", ی: "d", ب: "f", ل: "g", ا: "h", ت: "j", ن: "k", م: "l",
  ظ: "z", ط: "x", ز: "c", ر: "v", ذ: "b", د: "n",
};

const PERSIAN_DIGITS = "۰۱۲۳۴۵۶۷۸۹";

/**
 * The Latin text the scanner meant, or null when the input cannot be a mis-typed
 * code (it has letters outside the map, or nothing to convert).
 */
export function fromPersianLayout(input: string): string | null {
  let changed = false;
  let out = "";
  for (const ch of input) {
    const latin = PERSIAN_TO_LATIN[ch];
    if (latin) {
      out += latin;
      changed = true;
    } else if (PERSIAN_DIGITS.includes(ch)) {
      out += String(PERSIAN_DIGITS.indexOf(ch));
    } else if (/[0-9A-Za-z\-._]/.test(ch)) {
      out += ch;
    } else {
      return null;
    }
  }
  return changed ? out : null;
}
