import { describe, expect, it } from "vitest";
import { fromPersianLayout } from "./keyboard";

describe("fromPersianLayout", () => {
  it("maps scanner keys typed on the Persian layout back to Latin", () => {
    expect(fromPersianLayout("شذزی۱۲۳")).toBe("abcd123");
    expect(fromPersianLayout("ضصثقفغعهخح")).toBe("qwertyuiop");
  });
  it("leaves real names and plain codes alone", () => {
    expect(fromPersianLayout("شیر پرچرب")).toBeNull(); // space and پ are not code characters
    expect(fromPersianLayout("6260100212345")).toBeNull(); // nothing to convert
    expect(fromPersianLayout("۶۲۶۰۱")).toBeNull(); // digits only: toEnDigits handles them
  });
});
