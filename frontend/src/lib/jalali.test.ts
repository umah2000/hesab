import { describe, expect, it } from "vitest";
import { periodPresets } from "@/components/ui/jalali-calendar";

describe("periodPresets", () => {
  it("builds Jalali periods for Saturday 1405/08/09", () => {
    const p = Object.fromEntries(periodPresets("2026-10-31").map(([l, f, t]) => [l, [f, t]]));
    expect(p["امروز"]).toEqual(["2026-10-31", "2026-10-31"]);
    expect(p["دیروز"]).toEqual(["2026-10-30", "2026-10-30"]);
    expect(p["این هفته"]).toEqual(["2026-10-31", "2026-10-31"]); // the week starts on Saturday
    expect(p["این ماه"]).toEqual(["2026-10-23", "2026-10-31"]); // 1405/08/01
    expect(p["ماه قبل"]).toEqual(["2026-09-23", "2026-10-22"]); // Mehr: 30 days
    expect(p["امسال"]).toEqual(["2026-03-21", "2026-10-31"]); // 1405/01/01
  });
  it("starts the week on the previous Saturday", () => {
    const week = periodPresets("2026-11-05").find(([l]) => l === "این هفته");
    expect(week?.slice(1)).toEqual(["2026-10-31", "2026-11-05"]);
  });
});
