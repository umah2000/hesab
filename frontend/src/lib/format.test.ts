import { formatMoney, toEnDigits, toFaDigits } from "./format";

describe("formatMoney", () => {
  it("converts rials to tomans with string math", () => {
    expect(formatMoney("1234567890.0000", "IRT")).toBe("۱۲۳٬۴۵۶٬۷۸۹ تومان");
  });
  it("keeps a non-zero last rial digit as a toman fraction", () => {
    expect(formatMoney("15.0000", "IRT")).toBe("۱٫۵ تومان");
  });
  it("shows rials when configured", () => {
    expect(formatMoney("1500000.0000", "IRR")).toBe("۱٬۵۰۰٬۰۰۰ ریال");
  });
  it("handles very large amounts exactly", () => {
    expect(formatMoney("999999999999999.0000", "IRR")).toBe("۹۹۹٬۹۹۹٬۹۹۹٬۹۹۹٬۹۹۹ ریال");
  });
  it("handles negatives and zero", () => {
    expect(formatMoney("-50000.0000", "IRT")).toBe("−۵٬۰۰۰ تومان");
    expect(formatMoney("0.0000", "IRT")).toBe("۰ تومان");
  });
});

describe("digits", () => {
  it("converts both ways, including Arabic-Indic input", () => {
    expect(toFaDigits("2026")).toBe("۲۰۲۶");
    expect(toEnDigits("۱۴۰۵")).toBe("1405");
    expect(toEnDigits("٣٤")).toBe("34");
  });
});
