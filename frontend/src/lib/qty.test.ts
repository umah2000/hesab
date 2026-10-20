import { describe, expect, it } from "vitest";
import { addQty, fromQtyUnits, qtyUnits, subQty } from "./qty";

describe("quantities without floats", () => {
  it("adds and subtracts thousandths exactly", () => {
    expect(addQty("0.1", "0.2")).toBe("0.3");
    expect(addQty("1.25", "1")).toBe("2.25");
    expect(subQty("3", "1.250")).toBe("1.75");
    expect(subQty("1", "1")).toBe("0");
    expect(subQty("1", "1.5")).toBe("-0.5");
  });
  it("round-trips", () => {
    expect(qtyUnits("12.345")).toBe(12345n);
    expect(fromQtyUnits(12000n)).toBe("12");
    expect(qtyUnits("-0.5")).toBe(-500n);
  });
});
