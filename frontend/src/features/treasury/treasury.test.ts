import { describe, expect, it } from "vitest";
import { absRials, actionAccount, cleanDigits, flowOf, reconVerdict, sayadOk, settlementNet } from "./helpers";

describe("settlementNet", () => {
  it("subtracts the fee with exact decimal math", () => {
    expect(settlementNet("10000000", "35000")).toBe("9965000.0000");
    expect(settlementNet("10000000", "")).toBe("10000000.0000");
    expect(settlementNet("10000000", null)).toBe("10000000.0000");
    expect(settlementNet("900719925474099300", "1")).toBe("900719925474099299.0000");
  });
  it("is null when the fee is not below the amount or input is invalid", () => {
    expect(settlementNet("1000", "1000")).toBeNull();
    expect(settlementNet("1000", "2000")).toBeNull();
    expect(settlementNet("0", "0")).toBeNull();
    expect(settlementNet(null, "0")).toBeNull();
    expect(settlementNet("12a", "0")).toBeNull();
  });
});

describe("flowOf / absRials", () => {
  it("labels signed amounts as deposit or withdrawal", () => {
    expect(flowOf("5000000.0000")).toEqual({ label: "واریز", abs: "5000000.0000", incoming: true });
    expect(flowOf("-120000.0000")).toEqual({ label: "برداشت", abs: "120000.0000", incoming: false });
    expect(absRials("-7")).toBe("7");
  });
});

describe("sayadOk / cleanDigits", () => {
  it("accepts empty or 16 digits, Persian digits too", () => {
    expect(sayadOk("")).toBe(true);
    expect(sayadOk("1234567890123456")).toBe(true);
    expect(sayadOk("۱۲۳۴۵۶۷۸۹۰۱۲۳۴۵۶")).toBe(true);
    expect(sayadOk("1234 5678 9012 3456")).toBe(true);
    expect(sayadOk("123")).toBe(false);
    expect(sayadOk("12345678901234567")).toBe(false);
    expect(cleanDigits("۱۲-۳ ۴")).toBe("1234");
  });
});

describe("reconVerdict", () => {
  it("agrees only when adjusted book equals the bank balance", () => {
    expect(reconVerdict("1000.0000", "1000")).toEqual({ state: "agree", diff: "0.0000" });
    expect(reconVerdict("1500.0000", "1000.0000")).toEqual({ state: "differ", diff: "500.0000" });
    expect(reconVerdict("1000", "1500")).toEqual({ state: "differ", diff: "-500.0000" });
    expect(reconVerdict("1000", null)).toEqual({ state: "unknown", diff: null });
  });
});

describe("actionAccount", () => {
  it("asks for a bank on deposits and for any account when cashing a cheque in hand", () => {
    expect(actionAccount("received", "in_hand", "deposit")).toBe("bank");
    expect(actionAccount("received", "bounced", "redeposit")).toBe("bank");
    expect(actionAccount("received", "in_hand", "clear")).toBe("any");
    expect(actionAccount("received", "deposited", "clear")).toBeNull();
    expect(actionAccount("received", "in_hand", "return")).toBeNull();
    expect(actionAccount("issued", "issued", "clear")).toBeNull();
  });
});
