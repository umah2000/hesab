import { formatCredit, formatMoney, toEnDigits, toFaDigits } from "./format";

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
    expect(formatMoney("-50000.0000", "IRT")).toBe("\u2066−۵٬۰۰۰\u2069 تومان");
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

describe("formatCredit", () => {
  it("names unlimited and missing credit instead of showing an amount", () => {
    expect(formatCredit({ credit_unlimited: true, credit_limit: null }, "IRT")).toBe("نامحدود");
    expect(formatCredit({ credit_limit: null }, "IRT", "ندارد")).toBe("ندارد");
    expect(formatCredit({ credit_limit: "50000000.0000" }, "IRT")).toBe(formatMoney("50000000.0000", "IRT"));
  });
});
