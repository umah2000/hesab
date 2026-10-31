import { describe, expect, it } from "vitest";
import { amountHint, numberToWords } from "./words";

describe("numberToWords", () => {
  it.each([
    ["0", "صفر"],
    ["5", "پنج"],
    ["15", "پانزده"],
    ["120", "صد و بیست"],
    ["205", "دویست و پنج"],
    ["1000", "یک هزار"],
    ["1205000", "یک میلیون و دویست و پنج هزار"],
    ["338950000", "سیصد و سی و هشت میلیون و نهصد و پنجاه هزار"],
    ["2000000000", "دو میلیارد"],
    ["۱۲۳", "صد و بیست و سه"],
  ])("%s → %s", (n, words) => expect(numberToWords(n)).toBe(words));
});

describe("amountHint", () => {
  it("shows toman in words and the rial figure", () => {
    expect(amountHint("1200000", "IRT")).toBe("یک میلیون و دویست هزار تومان · ۱۲٬۰۰۰٬۰۰۰ ریال");
  });
  it("shows rial in words and the toman figure", () => {
    expect(amountHint("50000", "IRR")).toBe("پنجاه هزار ریال · ۵٬۰۰۰ تومان");
  });
  it("is empty while nothing valid is typed", () => {
    expect(amountHint("", "IRT")).toBeNull();
    expect(amountHint("1.2.3", "IRT")).toBeNull();
  });
});
