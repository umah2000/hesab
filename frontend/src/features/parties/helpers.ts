import { ApiError } from "@/lib/api";
import { compareRials } from "@/lib/money";

/** Server message plus field-level validation messages (400 details), for toasts. */
export function apiErrorText(e: unknown): string {
  if (!(e instanceof ApiError)) return "خطا";
  const details = Array.isArray(e.details) ? (e.details as { msg?: unknown }[]) : [];
  const msgs = details
    .map((d) => (typeof d?.msg === "string" ? d.msg.replace(/^Value error,\s*/, "") : ""))
    .filter(Boolean);
  return msgs.length ? `${e.message}: ${msgs.join("؛ ")}` : e.message;
}

export type BalanceSide = "debtor" | "creditor" | "zero";

/** Positive balance = the party owes us (بدهکار); negative = we owe them (بستانکار). */
export function balanceSide(rials: string): BalanceSide {
  const c = compareRials(rials, "0");
  return c > 0 ? "debtor" : c < 0 ? "creditor" : "zero";
}

export const BALANCE_LABEL: Record<BalanceSide, string> = { debtor: "بدهکار", creditor: "بستانکار", zero: "بی‌حساب" };

export const absRials = (rials: string) => rials.trim().replace(/^-/, "");
