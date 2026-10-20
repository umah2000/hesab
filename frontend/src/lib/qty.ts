/** Quantities (DECIMAL(19,3)) as integer thousandths — no floating point (ADR-0008). */
export function qtyUnits(v: string): bigint {
  const neg = v.trim().startsWith("-");
  const [i, f = ""] = v.trim().replace("-", "").split(".");
  const u = BigInt(i || "0") * 1000n + BigInt((f + "000").slice(0, 3));
  return neg ? -u : u;
}

export function fromQtyUnits(t: bigint): string {
  const neg = t < 0n;
  const a = neg ? -t : t;
  const f = (a % 1000n).toString().padStart(3, "0").replace(/0+$/, "");
  return `${neg ? "-" : ""}${a / 1000n}${f ? `.${f}` : ""}`;
}

export const addQty = (a: string, b: string) => fromQtyUnits(qtyUnits(a) + qtyUnits(b));
export const subQty = (a: string, b: string) => fromQtyUnits(qtyUnits(a) - qtyUnits(b));
