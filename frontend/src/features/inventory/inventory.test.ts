import { describe, expect, it } from "vitest";
import { trimQty } from "./api";
import { barcodeFormat } from "./LabelsPage";

describe("trimQty", () => {
  it("drops trailing zeros without touching integers", () => {
    expect(trimQty("12.500")).toBe("12.5");
    expect(trimQty("3.000")).toBe("3");
    expect(trimQty("0.000")).toBe("0");
    expect(trimQty("120")).toBe("120");
    expect(trimQty(null)).toBe("0");
  });
});

describe("barcodeFormat", () => {
  it("prints retail codes as EAN and everything else as Code128", () => {
    expect(barcodeFormat("6261000000115")).toBe("EAN13");
    expect(barcodeFormat("12345670")).toBe("EAN8");
    expect(barcodeFormat("2001")).toBe("CODE128");
    expect(barcodeFormat("ABC-12")).toBe("CODE128");
  });
});
