import { describe, expect, it } from "vitest";
import { changePct } from "./api";
import { formatCell } from "./ReportsPage";

describe("reports", () => {
  it("formats cells by column kind without floats", () => {
    expect(formatCell({ key: "a", label: "", kind: "money" }, "1100000.0000", "IRT")).toBe("۱۱۰٬۰۰۰");
    expect(formatCell({ key: "a", label: "", kind: "money" }, "10323.0000", "IRT")).toBe("۱٬۰۳۲٫۳");
    expect(formatCell({ key: "a", label: "", kind: "qty" }, "2.500", "IRT")).toBe("۲٫۵");
    expect(formatCell({ key: "a", label: "", kind: "percent" }, "20.00", "IRT")).toBe("۲۰٪");
    expect(formatCell({ key: "a", label: "", kind: "percent" }, "12.50", "IRT")).toBe("۱۲٫۵٪");
    expect(formatCell({ key: "a", label: "", kind: "percent" }, "100.00", "IRT")).toBe("۱۰۰٪");
    expect(formatCell({ key: "a", label: "", kind: "int" }, null, "IRT")).toBe("—");
  });
  it("computes period change from rial strings", () => {
    expect(changePct("1500000.0000", "1000000.0000")).toBe(50);
    expect(changePct("500000.0000", "1000000.0000")).toBe(-50);
    expect(changePct("1", "0")).toBeNull();
  });
});
