import { describe, expect, it } from "vitest";
import { parseQty, previewInvoice, remainingOrderQty, resolveVatRate, roundDiv } from "./preview";

describe("roundDiv", () => {
  it("rounds half away from zero", () => {
    expect(roundDiv(5n, 2n)).toBe(3n);
    expect(roundDiv(4n, 3n)).toBe(1n);
    expect(roundDiv(-5n, 2n)).toBe(-3n);
    expect(roundDiv(10n, 5n)).toBe(2n);
  });
});

describe("parseQty", () => {
  it("accepts up to three decimals and Persian digits", () => {
    expect(parseQty("۱۲.۵")).toBe(12500n);
    expect(parseQty("0.001")).toBe(1n);
    expect(parseQty("1.0004")).toBeNull();
    expect(parseQty("0")).toBeNull();
    expect(parseQty("abc")).toBeNull();
  });
});

describe("previewInvoice", () => {
  it("computes gross, discount, VAT and totals in exact rials", () => {
    const p = previewInvoice(
      [
        { qty: "100", unitCost: "80000", discount: "200000", vatRate: "10" },
        { qty: "50", unitCost: "30000", discount: "0", vatRate: "0" },
      ],
      [],
    );
    expect(p.lines[0]).toMatchObject({ gross: "8000000.0000", net: "7800000.0000", tax: "780000.0000" });
    expect(p.lines[1]).toMatchObject({ gross: "1500000.0000", tax: "0.0000" });
    expect(p.subtotal).toBe("9500000.0000");
    expect(p.discount_total).toBe("200000.0000");
    expect(p.tax_total).toBe("780000.0000");
    expect(p.grand_total).toBe("10080000.0000");
    expect(p.cost_total).toBe("9300000.0000");
    expect(p.complete).toBe(true);
  });

  it("rounds gross and tax half-up to whole rials", () => {
    const p = previewInvoice([{ qty: "1.5", unitCost: "3", discount: "", vatRate: "9" }], []);
    // 4.5 → 5; 5 × 9% = 0.45 → 0
    expect(p.lines[0]).toMatchObject({ gross: "5.0000", net: "5.0000", tax: "0.0000" });
  });

  it("spreads landed costs by net with the residue on the largest line", () => {
    const p = previewInvoice(
      [
        { qty: "1", unitCost: "100", discount: "0", vatRate: "0" },
        { qty: "1", unitCost: "200", discount: "0", vatRate: "0" },
      ],
      ["100"],
    );
    expect(p.lines[0]?.landed).toBe("33.0000");
    expect(p.lines[1]?.landed).toBe("67.0000");
    expect(p.charges_total).toBe("100.0000");
    expect(p.cost_total).toBe("400.0000");
    expect(p.grand_total).toBe("400.0000");
  });

  it("weighs free lines by base quantity", () => {
    const p = previewInvoice(
      [
        { qty: "1", unitCost: "0", discount: "0", vatRate: "0", factor: "12" },
        { qty: "4", unitCost: "0", discount: "0", vatRate: "0" },
      ],
      ["160"],
    );
    expect(p.lines[0]?.landed).toBe("120.0000");
    expect(p.lines[1]?.landed).toBe("40.0000");
  });

  it("leaves out invalid lines and flags the preview incomplete", () => {
    const p = previewInvoice(
      [
        { qty: "", unitCost: "100", discount: "0", vatRate: "0" },
        { qty: "1", unitCost: "100", discount: "200", vatRate: "0" },
        { qty: "2", unitCost: "100", discount: "0", vatRate: "0" },
      ],
      ["abc"],
    );
    expect(p.lines[0]).toBeNull();
    expect(p.lines[1]).toBeNull();
    expect(p.subtotal).toBe("200.0000");
    expect(p.complete).toBe(false);
  });
});

describe("resolveVatRate", () => {
  it("follows the server's precedence", () => {
    expect(resolveVatRate("5", "10", true, "9")).toBe("0");
    expect(resolveVatRate("۵", "10", false, "9")).toBe("5");
    expect(resolveVatRate("", "10", false, "9")).toBe("10");
    expect(resolveVatRate("", null, false, "9")).toBe("9");
  });
});

describe("remainingOrderQty", () => {
  it("converts the unreceived base quantity back to the line unit", () => {
    expect(remainingOrderQty("10.000", "120.000", "0.000")).toBe("10");
    expect(remainingOrderQty("10.000", "120.000", "36.000")).toBe("7");
    expect(remainingOrderQty("10.000", "120.000", "120.000")).toBe("0");
    expect(remainingOrderQty("3.000", "3.000", "1.500")).toBe("1.5");
  });
});
