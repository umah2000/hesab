import { type DisplayCurrency, toFaDigits } from "@/lib/format";

export type Method = "cash" | "card" | "credit";
export const METHOD_LABEL: Record<Method, string> = { cash: "نقد", card: "کارت", credit: "نسیه" };

export type Shift = {
  id: string;
  branch_id: string;
  cash_register_id: string;
  register_name: string;
  user_id: string;
  user_name: string;
  status: "open" | "closed";
  opened_at: string;
  opening_cash: string;
  closed_at: string | null;
  expected_cash: string | null;
  counted_cash: string | null;
  difference: string | null;
  close_note: string | null;
  voucher_id: string | null;
  row_version: string;
};

export type MethodTotal = { method: Method; sales: string; refunds: string };

export type ShiftReport = {
  shift: Shift;
  sale_count: number;
  return_count: number;
  sales_total: string;
  returns_total: string;
  discount_total: string;
  tax_total: string;
  by_method: MethodTotal[];
  expected_cash: string;
};

export type TerminalInfo = { adapter_id: string; label: string; verified: boolean; simulated: boolean; scenarios: string[] };

/** A card reader the register may send to (ADR-0023); `reason` says why it cannot yet. */
export type TerminalChoice = {
  id: string;
  name: string;
  provider_label: string;
  is_default: boolean;
  ready: boolean;
  reason: string | null;
  simulated: boolean;
  scenarios: string[];
};

export type RegisterState = {
  cash_register_id: string;
  register_name: string;
  branch_id: string;
  branch_name: string;
  warehouse_id: string;
  shift: Shift | null;
  other_shift_user: string | null;
  held_count: number;
  display_currency: DisplayCurrency;
  receipt_header: string | null;
  receipt_footer: string | null;
  organization_name: string;
  terminal: TerminalInfo | null;
  terminals: TerminalChoice[];
  permissions: string[];
};

export type CartLine = {
  key: string;
  item_id: string;
  code: string;
  name: string;
  unit_id?: string;
  qty: string;
  barcode?: string;
  /** Weight/price came from a scale label: quantity is fixed by the label. */
  fixed?: boolean;
  manual_discount?: string;
};

export type QuoteLine = {
  line_no: number;
  item_id: string;
  item_code: string;
  item_name: string;
  unit_id: string;
  unit_name: string;
  qty: string;
  unit_price: string;
  price_source: "list" | "scale";
  gross: string;
  promotion_id: string | null;
  promotion_name: string | null;
  promotion_discount: string;
  manual_discount: string;
  vat_exempt: boolean;
  vat_rate: string;
  tax: string;
  line_total: string;
  stock_qty: string | null;
  scanned_barcode: string | null;
};

export type Quote = {
  lines: QuoteLine[];
  subtotal: string;
  promotion_total: string;
  manual_discount_total: string;
  discount_total: string;
  tax_total: string;
  grand_total: string;
  manual_discount_percent: string;
  discount_limit_percent: string;
  needs_discount_approval: boolean;
  warnings: string[];
};

export type Payment = { method: Method; amount: string; card_reference?: string | null; terminal_transaction_id?: string | null };

export type InvoiceLine = QuoteLine & { id: string; cost_total: string | null; original_line_id: string | null; returned_qty: string };

export type Invoice = {
  id: string;
  kind: "sale" | "return";
  status: "draft" | "held" | "recalled" | "final";
  number: number | null;
  document_date: string;
  branch_id: string;
  cash_register_id: string;
  register_name: string;
  shift_id: string | null;
  cashier_name: string;
  customer_id: string | null;
  customer_name: string | null;
  original_invoice_id: string | null;
  original_number: number | null;
  subtotal: string;
  discount_total: string;
  tax_total: string;
  grand_total: string;
  cash_tendered: string | null;
  change_due: string | null;
  note: string | null;
  voucher_id: string | null;
  finalized_at: string | null;
  created_at: string;
  lines: InvoiceLine[];
  payments: Payment[];
  warnings: string[];
  /** Sold while the server was unreachable: the register's number until it syncs. */
  device_number?: string | null;
  offline?: boolean;
};

/** "فاکتور ۱۲" online, "فیش صندوق AB12CD34-3" for an offline sale not yet numbered. */
export function invoiceLabel(inv: Pick<Invoice, "number" | "device_number">): string {
  if (inv.number == null && inv.device_number) return `فیش صندوق ${inv.device_number}`;
  return `فاکتور ${toFaDigits(inv.number ?? 0)}`;
}

export type InvoiceSummary = {
  id: string;
  kind: "sale" | "return";
  status: "held" | "final";
  number: number | null;
  document_date: string;
  register_name: string;
  cashier_name: string;
  customer_name: string | null;
  grand_total: string;
  line_count: number;
  note: string | null;
  created_at: string;
};

export type Customer = {
  id: string;
  code: string;
  name: string;
  credit_limit: string | null;
  credit_unlimited: boolean;
  balance: string;
  available: string | null;
};

export type TerminalTx = {
  id: string;
  request_id: string;
  cash_register_id: string;
  cart_id: string;
  adapter_id: string;
  amount: string;
  status: "Created" | "Pending" | "Approved" | "Declined" | "Unknown" | "ReconciliationRequired" | "Cancelled";
  rrn: string | null;
  trace_no: string | null;
  masked_pan: string | null;
  response_code: string | null;
  is_simulated: boolean;
  created_at: string;
  row_version: string;
};

export const TX_LABEL: Record<TerminalTx["status"], string> = {
  Created: "ایجاد شد",
  Pending: "در انتظار دستگاه",
  Approved: "تأیید شد",
  Declined: "رد شد",
  Unknown: "نامشخص — استعلام لازم است",
  ReconciliationRequired: "نیازمند تطبیق با گزارش بانک",
  Cancelled: "لغو شد",
};

export type Promotion = {
  id: string;
  name: string;
  kind: "percent" | "amount";
  scope: "item" | "group";
  item_id: string | null;
  group_id: string | null;
  target_name: string;
  value: string;
  starts_on: string;
  ends_on: string;
  is_active: boolean;
  row_version: string;
};

export type DailyReport = {
  date: string;
  branch_id: string | null;
  sale_count: number;
  return_count: number;
  sales_total: string;
  returns_total: string;
  net_total: string;
  discount_total: string;
  tax_total: string;
  cost_total: string;
  gross_profit: string;
  by_method: MethodTotal[];
  by_register: { cash_register_id: string; register_name: string; sale_count: number; sales_total: string; returns_total: string }[];
};

/** The register this browser/workstation works as (set once by the cashier or admin). */
export const REGISTER_KEY = "nc.register";
export function storedRegister(): string | null {
  try {
    return localStorage.getItem(REGISTER_KEY);
  } catch {
    return null;
  }
}
export function storeRegister(id: string | null) {
  try {
    if (id) localStorage.setItem(REGISTER_KEY, id);
    else localStorage.removeItem(REGISTER_KEY);
  } catch {
    /* private mode: the cashier picks the register again */
  }
}
