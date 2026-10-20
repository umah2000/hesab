export type ColumnKind = "text" | "money" | "qty" | "int" | "percent" | "date";
export type Column = { key: string; label: string; kind: ColumnKind };
export type Row = Record<string, string | number | boolean | null | undefined> & { _level?: number; _bold?: boolean };

export type ReportTable = {
  key: string;
  title: string;
  columns: Column[];
  rows: Row[];
  totals: Row | null;
  total_rows: number;
  page: number;
  page_size: number;
  notes: string[];
};

export type ReportInfo = { key: string; title: string; description: string; group: string; filters: string[] };

export type SavedFilter = { id: string; report: string; name: string; params: Record<string, string>; created_at: string };

export type Kpi = {
  net_sales: string;
  gross_profit: string;
  margin: string | null;
  invoices: number;
  returns: number;
  average_basket: string | null;
};

export type Dashboard = {
  date_from: string;
  date_to: string;
  current: Kpi;
  previous: Kpi;
  series: { date: string; net_sales: string; gross_profit: string; invoices: number }[];
  top_items: { item_id: string; code: string; name: string; qty: string; net_sales: string }[];
  payments: Record<string, string>;
  inventory_value: string | null;
  below_min_items: number | null;
  receivables: string | null;
  payables: string | null;
  cash_shortage: string;
  unknown_card_transactions: number;
  generated_at: string;
};

/** Group-by options per report (labels match the server). */
export const GROUP_BY: Record<string, [string, string][]> = {
  sales: [
    ["day", "روز"],
    ["item", "کالا"],
    ["group", "گروه کالا"],
    ["cashier", "صندوق‌دار"],
    ["register", "صندوق"],
    ["branch", "شعبه"],
  ],
  "cash-shortages": [
    ["cashier", "صندوق‌دار"],
    ["register", "صندوق"],
    ["shift", "شیفت"],
  ],
};

/** Ratio of two rial strings as a percent change, using integers only. */
export function changePct(current: string, previous: string): number | null {
  const c = BigInt(current.split(".")[0]);
  const p = BigInt(previous.split(".")[0]);
  if (p === 0n) return null;
  return Number(((c - p) * 1000n) / (p < 0n ? -p : p)) / 10;
}
