import { describe, expect, it } from "vitest";
import { ApiError } from "@/lib/api";
import { absRials, apiErrorText, balanceSide } from "./helpers";

describe("parties helpers", () => {
  it("classifies balance sign without floats", () => {
    expect(balanceSide("1500.0000")).toBe("debtor");
    expect(balanceSide("-0.0001")).toBe("creditor");
    expect(balanceSide("0.0000")).toBe("zero");
    expect(absRials("-25000.0000")).toBe("25000.0000");
  });

  it("joins validation details into the toast text", () => {
    const e = new ApiError(400, "validation_error", "ورودی نامعتبر است", [
      { loc: ["mobile"], msg: "Value error, شماره همراه باید ۱۱ رقم و با ۰۹ شروع شود" },
    ]);
    expect(apiErrorText(e)).toBe("ورودی نامعتبر است: شماره همراه باید ۱۱ رقم و با ۰۹ شروع شود");
    expect(apiErrorText(new ApiError(409, "conflict", "تعارض"))).toBe("تعارض");
    expect(apiErrorText(new Error("x"))).toBe("خطا");
  });
});
