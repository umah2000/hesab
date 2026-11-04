import { describe, expect, it } from "vitest";
import { fold, type IndexRow, searchIndex } from "./search";

const row = (id: string, code: string, name: string, barcodes: string[] = []): IndexRow => [id, code, name, fold(name), "عدد", "1000", false, barcodes, null];
const index = {
  version: "v",
  items: [
    row("1", "S1", "شير پرچرب"),
    row("2", "S2", "پنیر کوزه‌ای"),
    row("3", "S3", "کیک شیری"),
    row("4", "4321", "کنسرو لوبیا", ["6260000004321"]),
    row("5", "S4", "پودر 4321 گرمی"),
  ],
};

describe("fold", () => {
  it("matches the server's folding", () => {
    expect(fold("شير  كوزه‌اي ۱۲")).toBe("شیر کوزهای 12");
  });
});

describe("searchIndex", () => {
  const ids = (q: string) => searchIndex(index, q).map((h) => h.id);
  it("finds Arabic letters and the non-joiner", () => {
    expect(ids("شیر")).toEqual(["1", "3"]);
    expect(ids("کوزهای")).toEqual(["2"]);
    expect(ids("کوزه‌ای")).toEqual(["2"]);
  });
  it("needs every word, in any order", () => {
    expect(ids("پرچرب شير")).toEqual(["1"]);
  });
  it("puts an exact code or barcode first", () => {
    expect(ids("4321")).toEqual(["4", "5"]);
    expect(ids("۴۳۲۱")).toEqual(["4", "5"]);
    expect(ids("6260000004321")).toEqual(["4"]);
  });
  it("is fast on a large catalogue", () => {
    const big = { version: "v", items: Array.from({ length: 50_000 }, (_, i) => row(String(i), `C${i}`, `کالای آزمون شماره ${i}`)) };
    const t = performance.now();
    for (let i = 0; i < 20; i++) searchIndex(big, "آزمون ۴۲");
    const per = (performance.now() - t) / 20;
    expect(per).toBeLessThan(50);
  });
});
