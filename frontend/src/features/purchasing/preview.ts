/**
 * Client-side PREVIEW of purchase invoice totals while a draft is edited.
 * The authoritative figures are always the ones the server returns after saving
 * (purchasing.services.invoices); this mirrors its rules with BigInt fixed-point
 * math only — never floats (ADR-0008):
 *   gross = rial(qty × unit_cost), net = gross − discount, tax = rial(net × rate / 100),
 *   landed costs spread by net (by base quantity when every line is free), the rounding
 *   residue on the largest line (the first one on ties).
 */
import { toEnDigits } from "@/lib/format";
import { qtyUnits } from "@/lib/qty";

const M = 10_000n; // money: 4 decimals (rials)

/** Half-up rounding away from zero, like Decimal ROUND_HALF_UP. */
export function roundDiv(n: bigint, d: bigint): bigint {
  const neg = n < 0n !== d < 0n;
  const a = n < 0n ? -n : n;
  const b = d < 0n ? -d : d;
  const q = (2n * a + b) / (2n * b);
  return neg ? -q : q;
}

function parseFixed(v: string, places: number): bigint | null {
  const clean = toEnDigits(v).trim().replace(/[,٬\s]/g, "").replace("٫", ".");
  const m = clean.match(/^(-?)(\d+)(?:\.(\d+))?$/);
  if (!m) return null;
  const frac = m[3] ?? "";
  if (frac.replace(/0+$/, "").length > places) return null;
  const scale = 10n ** BigInt(places);
  const u = BigInt(m[2]) * scale + BigInt((frac + "0".repeat(places)).slice(0, places) || "0");
  return m[1] ? -u : u;
}

/** Valid positive quantity with at most 3 decimals (DECIMAL(19,3)). */
export function parseQty(v: string): bigint | null {
  const u = parseFixed(v, 3);
  return u !== null && u > 0n ? u : null;
}

const money = (v: string) => parseFixed(v, 4);

export function fromMoneyUnits(u: bigint): string {
  const neg = u < 0n;
  const a = neg ? -u : u;
  return `${neg ? "-" : ""}${a / M}.${String(a % M).padStart(4, "0")}`;
}

export type PreviewLineIn = {
  qty: string;
  /** Rials per line unit, excluding VAT. */
  unitCost: string;
  /** Rials. */
  discount: string;
  /** Percent, already resolved (override, item rate or organisation default; 0 when exempt). */
  vatRate: string;
  /** Base units per line unit; only used to weigh landed costs when every line is free. */
  factor?: string;
};

export type PreviewLine = { gross: string; discount: string; net: string; tax: string; landed: string; total_cost: string };

export type Preview = {
  lines: (PreviewLine | null)[];
  subtotal: string;
  discount_total: string;
  tax_total: string;
  charges_total: string;
  grand_total: string;
  cost_total: string;
  /** False when some line or charge is incomplete or invalid (those are left out). */
  complete: boolean;
};

export function previewInvoice(lines: PreviewLineIn[], charges: string[]): Preview {
  let complete = true;
  type Calc = { gross: bigint; discount: bigint; net: bigint; tax: bigint; weightQty: bigint };
  const calc: (Calc | null)[] = lines.map((l) => {
    const qty = parseQty(l.qty);
    const cost = money(l.unitCost);
    const disc = l.discount.trim() ? money(l.discount) : 0n;
    const rate = parseFixed(l.vatRate || "0", 2);
    if (qty === null || cost === null || cost < 0n || disc === null || disc < 0n || rate === null || rate < 0n) {
      complete = false;
      return null;
    }
    const gross = roundDiv(qty * cost, 1000n * M) * M;
    if (disc > gross) {
      complete = false;
      return null;
    }
    const net = gross - disc;
    const tax = roundDiv(net * rate, 10n ** 8n) * M;
    const factor = l.factor ? qtyUnits(l.factor) : 1000n;
    return { gross, discount: disc, net, tax, weightQty: qty * factor };
  });

  let chargesTotal = 0n;
  for (const c of charges) {
    const a = money(c);
    if (a === null || a <= 0n) complete = false;
    else chargesTotal += a;
  }

  const valid = calc.flatMap((c, i) => (c ? [i] : []));
  const landed = new Map<number, bigint>();
  if (valid.length) {
    let weights = valid.map((i) => calc[i]!.net);
    if (weights.every((w) => w === 0n)) weights = valid.map((i) => calc[i]!.weightQty);
    const total = weights.reduce((a, b) => a + b, 0n);
    let biggest = 0;
    weights.forEach((w, k) => {
      if (w > weights[biggest]) biggest = k;
    });
    let done = 0n;
    valid.forEach((i, k) => {
      const share = k === biggest || total === 0n ? 0n : roundDiv(chargesTotal * weights[k], total * M) * M;
      landed.set(i, share);
      done += share;
    });
    landed.set(valid[biggest], chargesTotal - done);
  }

  let subtotal = 0n;
  let discountTotal = 0n;
  let taxTotal = 0n;
  let costTotal = 0n;
  const out = calc.map((c, i) => {
    if (!c) return null;
    const l = landed.get(i) ?? 0n;
    subtotal += c.gross;
    discountTotal += c.discount;
    taxTotal += c.tax;
    costTotal += c.net + l;
    return {
      gross: fromMoneyUnits(c.gross),
      discount: fromMoneyUnits(c.discount),
      net: fromMoneyUnits(c.net),
      tax: fromMoneyUnits(c.tax),
      landed: fromMoneyUnits(l),
      total_cost: fromMoneyUnits(c.net + l),
    };
  });
  return {
    lines: out,
    subtotal: fromMoneyUnits(subtotal),
    discount_total: fromMoneyUnits(discountTotal),
    tax_total: fromMoneyUnits(taxTotal),
    charges_total: fromMoneyUnits(chargesTotal),
    grand_total: fromMoneyUnits(subtotal - discountTotal + taxTotal + chargesTotal),
    cost_total: fromMoneyUnits(costTotal),
    complete,
  };
}

/** The VAT rate the server would apply: exempt items 0, else override, item rate, org default. */
export function resolveVatRate(override: string, itemRate: string | null, exempt: boolean, orgDefault: string): string {
  if (exempt) return "0";
  const o = toEnDigits(override).trim();
  if (o) return o;
  return itemRate ?? orgDefault;
}

/**
 * Still-to-receive quantity of an order line in its own unit (qty × remaining base / base),
 * truncated to thousandths; "0" when nothing is left.
 */
export function remainingOrderQty(qty: string, baseQty: string, receivedBase: string): string {
  const q = qtyUnits(qty);
  const b = qtyUnits(baseQty);
  const r = qtyUnits(receivedBase);
  if (r <= 0n || b <= 0n) return trim(q);
  const left = b - r;
  if (left <= 0n) return "0";
  return trim((q * left) / b);
}

function trim(t: bigint): string {
  const f = (t % 1000n).toString().padStart(3, "0").replace(/0+$/, "");
  return `${t / 1000n}${f ? `.${f}` : ""}`;
}
