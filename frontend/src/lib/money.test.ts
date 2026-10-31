import { isoToJalali, jalaliToIso } from "./jalali";
import { compareRials, divRialsByQty, groupDigits, inputToRials, rialsToInput, subRials, sumRials } from "./money";

describe("money entry", () => {
  it("converts toman input to rials", () => {
    expect(inputToRials("1,250,000", "IRT")).toBe("12500000");
    expect(inputToRials("۱۲۵۰", "IRT")).toBe("12500");
    expect(inputToRials("12.5", "IRT")).toBe("125");
    expect(inputToRials("0.05", "IRT")).toBe("0.5");
  });
  it("keeps rial input as is", () => {
    expect(inputToRials("1500000", "IRR")).toBe("1500000");
    expect(inputToRials("1.25", "IRR")).toBe("1.25");
  });
  it("rejects invalid input", () => {
    expect(inputToRials("-5", "IRT")).toBeNull();
    expect(inputToRials("abc", "IRT")).toBeNull();
    expect(inputToRials("1.123456", "IRT")).toBeNull();
    expect(inputToRials("9999999999999999", "IRR")).toBeNull();
  });
  it("round-trips rials to editable text", () => {
    expect(rialsToInput("12500000.0000", "IRT")).toBe("1250000");
    expect(rialsToInput("125.0000", "IRT")).toBe("12.5");
    expect(rialsToInput("1500000.0000", "IRR")).toBe("1500000");
    expect(inputToRials(rialsToInput("987654321.1200", "IRT"), "IRT")).toBe("987654321.12");
  });
  it("groups digits while typing", () => {
    expect(groupDigits("1234567")).toBe("1,234,567");
    expect(groupDigits("1234.5")).toBe("1,234.5");
  });
  it("sums and compares without floats", () => {
    expect(sumRials(["0.1", "0.2"])).toBe("0.3000");
    expect(sumRials(["999999999999999.9999", "0.0001"])).toBe("1000000000000000.0000");
    expect(compareRials("100.0000", "100")).toBe(0);
    expect(subRials("100", "250.5")).toBe("-150.5000");
  });
});

describe("jalali", () => {
  it("converts both ways", () => {
    expect(jalaliToIso("1405/07/19")).toBe("2026-10-11");
    expect(jalaliToIso("۱۴۰۵/۰۱/۰۱")).toBe("2026-03-21");
    expect(isoToJalali("2026-10-11")).toBe("1405/07/19");
  });
  it("rejects impossible dates", () => {
    expect(jalaliToIso("1405/12/31")).toBeNull(); // 1405 is not a leap year
    expect(jalaliToIso("1405/13/01")).toBeNull();
    expect(jalaliToIso("14050719")).toBeNull();
  });
});

describe("divRialsByQty", () => {
  it("divides without floats and rounds half up", () => {
    expect(divRialsByQty("330000", "3")).toBe("110000");
    expect(divRialsByQty("100000", "3")).toBe("33333");
    expect(divRialsByQty("5", "2")).toBe("3");
    expect(divRialsByQty("3900000", "1.442")).toBe("2704577");
    expect(divRialsByQty("100", "0")).toBe("0");
  });
});
