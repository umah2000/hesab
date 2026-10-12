/** Treasury types (mirror backend/app/modules/treasury/schemas.py), labels and query hooks. */
import { useQuery } from "@tanstack/react-query";
import { toast } from "sonner";
import type { Tone } from "@/components/ui/feedback";
import { ApiError, api } from "@/lib/api";

export type AccountKind = "cash" | "bank";
export type Method = "cash" | "bank" | "cheque";
export type Against = "receivable" | "payable";
export type DocKind = "receipt" | "payment" | "transfer" | "settlement";
export type ChequeAction = "deposit" | "clear" | "bounce" | "return" | "redeposit" | "cancel";

export type MoneyAccount = {
  id: string;
  code: string;
  name: string;
  kind: AccountKind;
  branch_id: string | null;
  branch_name: string | null;
  bank_name: string | null;
  bank_branch: string | null;
  account_no: string | null;
  iban: string | null;
  is_active: boolean;
  /** Rials, final vouchers only. */
  balance: string;
  row_version: string;
};

export type DocLine = {
  line_no: number;
  method: Method;
  money_account_id: string | null;
  money_account_name: string | null;
  amount: string;
  reference: string | null;
  cheque_id: string | null;
  cheque_number: string | null;
  cheque_due_date: string | null;
  cheque_status: string | null;
};

export type TreasuryDocument = {
  id: string;
  kind: DocKind;
  status: "draft" | "final" | "reversed";
  number: number | null;
  branch_id: string;
  document_date: string;
  party_id: string | null;
  party_name: string | null;
  against: Against | null;
  from_account_id: string | null;
  from_account_name: string | null;
  to_account_id: string | null;
  to_account_name: string | null;
  amount: string;
  fee: string;
  reference: string | null;
  description: string | null;
  voucher_id: string | null;
  reversal_voucher_id: string | null;
  reversed_at: string | null;
  reversal_reason: string | null;
  lines: DocLine[];
  created_at: string;
  row_version: string;
};

export type DocumentSummary = {
  id: string;
  kind: DocKind;
  status: "final" | "reversed";
  number: number | null;
  document_date: string;
  /** Party, or the bank account for settlements. */
  party_name: string | null;
  amount: string;
  description: string | null;
};

export type ChequeEvent = {
  seq: number;
  event_date: string;
  from_status: string | null;
  to_status: string;
  money_account_name: string | null;
  voucher_id: string | null;
  note: string | null;
  user: string | null;
  created_at: string;
};

export type Cheque = {
  id: string;
  direction: "received" | "issued";
  status: string;
  party_id: string;
  party_name: string;
  number: string;
  sayad_id: string | null;
  bank_name: string | null;
  drawer: string | null;
  amount: string;
  due_date: string;
  money_account_id: string | null;
  money_account_name: string | null;
  document_id: string;
  document_number: number | null;
  actions: ChequeAction[];
  events: ChequeEvent[];
  row_version: string;
};

export type ChequeSummary = {
  id: string;
  direction: "received" | "issued";
  status: string;
  party_name: string;
  number: string;
  bank_name: string | null;
  amount: string;
  due_date: string;
  overdue: boolean;
};

export type StatementLine = {
  id: string;
  line_date: string;
  /** Signed rials: positive = deposit into the account. */
  amount: string;
  description: string | null;
  reference: string | null;
  balance: string | null;
  voucher_line_id: string | null;
  voucher_id: string | null;
  voucher_number: number | null;
  matched_at: string | null;
};

export type BookLine = {
  voucher_line_id: string;
  voucher_id: string;
  voucher_number: number | null;
  document_date: string;
  description: string | null;
  /** Signed rials: positive = into the account. */
  amount: string;
};

export type Reconciliation = {
  account_id: string;
  as_of: string;
  book_balance: string;
  statement_balance: string | null;
  statement_unmatched: StatementLine[];
  book_unmatched: BookLine[];
  adjusted_book_balance: string;
};

export type StatementImport = {
  total_rows: number;
  new_rows: number;
  duplicate_rows: number;
  errors: { row: number; column: string; message: string }[];
  sample: { line_date: string; amount: string }[];
};

export type AutoMatch = { matched: number; ambiguous: number; unmatched: number };

export type Branch = { id: string; code: string; name: string; address: string | null; is_active: boolean; row_version: string };

// --- labels -------------------------------------------------------------------

export const KIND_LABEL: Record<DocKind, string> = {
  receipt: "دریافت",
  payment: "پرداخت",
  transfer: "انتقال وجه",
  settlement: "تسویه کارت‌خوان",
};
export const KIND_TONE: Record<DocKind, Tone> = { receipt: "success", payment: "warning", transfer: "info", settlement: "brand" };

export const DOC_STATUS_LABEL: Record<string, string> = { draft: "پیش‌نویس", final: "قطعی", reversed: "برگشت‌خورده" };

export const METHOD_LABEL: Record<Method, string> = { cash: "نقد", bank: "بانک (واریز / حواله)", cheque: "چک" };

export const ACCOUNT_KIND_LABEL: Record<AccountKind, string> = { cash: "صندوق", bank: "حساب بانکی" };

export const AGAINST_LABEL: Record<Against, string> = {
  receivable: "حساب‌های دریافتنی (مشتری)",
  payable: "حساب‌های پرداختنی (تأمین‌کننده)",
};

export const DIRECTION_LABEL: Record<string, string> = { received: "دریافتی", issued: "پرداختی" };

export const CHEQUE_STATUS_LABEL: Record<string, string> = {
  in_hand: "نزد صندوق",
  deposited: "واگذارشده به بانک",
  cleared: "وصول‌شده",
  bounced: "برگشتی",
  returned: "مسترد به صاحب چک",
  issued: "صادرشده",
  cancelled: "باطل‌شده",
  void: "ابطال (برگشت سند)",
};
export const CHEQUE_STATUS_TONE: Record<string, Tone> = {
  in_hand: "info",
  deposited: "brand",
  cleared: "success",
  bounced: "danger",
  returned: "neutral",
  issued: "info",
  cancelled: "neutral",
  void: "neutral",
};
export const RECEIVED_STATUSES = ["in_hand", "deposited", "cleared", "bounced", "returned", "void"];
export const ISSUED_STATUSES = ["issued", "cleared", "bounced", "cancelled", "void"];

export const ACTION_LABEL: Record<ChequeAction, string> = {
  deposit: "واگذاری به بانک",
  clear: "وصول",
  bounce: "برگشت (عدم وصول)",
  return: "استرداد به صاحب چک",
  redeposit: "واگذاری مجدد",
  cancel: "ابطال",
};

export const chequeStatusLabel = (s: string | null) => (s ? (CHEQUE_STATUS_LABEL[s] ?? s) : "—");

// --- hooks --------------------------------------------------------------------

export const onError = (e: unknown) => toast.error(e instanceof ApiError ? e.message : "خطا");

/** Cash boxes and bank accounts with server-computed balances. */
export function useMoneyAccounts(kind?: AccountKind) {
  return useQuery({
    queryKey: ["treasury", "accounts", kind ?? "all"],
    queryFn: () => api.get<MoneyAccount[]>(`/treasury/accounts${kind ? `?kind=${kind}` : ""}`),
    staleTime: 15_000,
  });
}

/** Branches in the user's scope (server-filtered); callers keep the active ones. */
export function useBranches() {
  return useQuery({
    queryKey: ["branches"],
    queryFn: () => api.get<Branch[]>("/organization/branches"),
    staleTime: 300_000,
  });
}

/** Display name for an account option. */
export const accountLabel = (a: MoneyAccount) =>
  a.kind === "cash" ? `${a.name}${a.branch_name ? ` — ${a.branch_name}` : ""}` : `${a.name}${a.bank_name ? ` — ${a.bank_name}` : ""}`;
