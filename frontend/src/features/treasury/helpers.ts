/**
 * Pure display helpers for treasury. No business rules: amounts, balances and
 * allowed cheque actions always come from the server; these only format or
 * preview what the server will compute. String/BigInt math only — no floats.
 */
import { toEnDigits } from "@/lib/format";
import { compareRials, subRials } from "@/lib/money";

const RIALS = /^-?\d+(\.\d+)?$/;

/** Net card settlement preview (amount − fee), or null while either is invalid or fee ≥ amount. */
export function settlementNet(amount: string | null, fee: string | null): string | null {
  if (!amount || !RIALS.test(amount)) return null;
  const f = fee && fee !== "" ? fee : "0";
  if (!RIALS.test(f)) return null;
  if (compareRials(amount, "0") <= 0 || compareRials(f, "0") < 0 || compareRials(f, amount) >= 0) return null;
  return subRials(amount, f);
}

/** Absolute value of a decimal rial string. */
export function absRials(v: string): string {
  return v.trim().replace(/^-/, "");
}

/** Signed statement / book amount → «واریز» (into the account) or «برداشت» plus the absolute amount. */
export function flowOf(amount: string): { label: "واریز" | "برداشت"; abs: string; incoming: boolean } {
  const incoming = compareRials(amount, "0") >= 0;
  return { label: incoming ? "واریز" : "برداشت", abs: absRials(amount), incoming };
}

/** Sayad (صیادی) id: optional; when given, 16 digits (Persian digits and spaces accepted). */
export function sayadOk(v: string): boolean {
  const s = toEnDigits(v).replace(/[\s-]/g, "");
  return s === "" || /^\d{16}$/.test(s);
}

export function cleanDigits(v: string): string {
  return toEnDigits(v).replace(/[\s-]/g, "");
}

/**
 * Reconciliation verdict as shown to the user: the server gives the adjusted book
 * balance and the bank's own balance; this only compares them.
 * `diff` = adjusted book − statement (null when the statement carries no balance).
 */
export function reconVerdict(
  adjusted: string,
  statement: string | null,
): { state: "agree" | "differ" | "unknown"; diff: string | null } {
  if (statement === null) return { state: "unknown", diff: null };
  const diff = subRials(adjusted, statement);
  return { state: compareRials(diff, "0") === 0 ? "agree" : "differ", diff };
}

/**
 * Whether a cheque action needs a money account picked now — mirrors the server's
 * TRANSITIONS table only to show the right field; the server re-checks.
 * "bank" = deposit/redeposit (bank only); "any" = cashing a cheque in hand (box or bank).
 */
export function actionAccount(direction: string, status: string, action: string): "bank" | "any" | null {
  if (direction !== "received") return null;
  if (action === "deposit" || action === "redeposit") return "bank";
  if (action === "clear" && status === "in_hand") return "any";
  return null;
}
