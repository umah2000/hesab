import { useQuery } from "@tanstack/react-query";
import type { Tone } from "@/components/ui/feedback";
import type { Organization } from "@/features/settings/types";
import { api } from "@/lib/api";

/** Mirrors backend/app/modules/purchasing/schemas.py. Money = rials string, qty = decimal string. */

export const PERM = "purchasing.manage";

export type OrderStatus = "draft" | "approved" | "closed" | "cancelled";
export type InvoiceKind = "invoice" | "return";
export type InvoiceStatus = "draft" | "final";

export type OrderLine = {
  id: string;
  line_no: number;
  item_id: string;
  item_code: string;
  item_name: string;
  unit_id: string;
  unit_name: string;
  qty: string;
  base_qty: string;
  unit_cost: string | null;
  received_base_qty: string;
};

export type Order = {
  id: string;
  number: number | null;
  status: OrderStatus;
  branch_id: string;
  warehouse_id: string;
  warehouse_name: string;
  supplier_id: string;
  supplier_name: string;
  order_date: string;
  expected_date: string | null;
  note: string | null;
  estimated_total: string;
  lines: OrderLine[];
  created_at: string;
  row_version: string;
};

export type OrderSummary = {
  id: string;
  number: number | null;
  status: OrderStatus;
  supplier_name: string;
  warehouse_name: string;
  order_date: string;
  expected_date: string | null;
  estimated_total: string;
};

export type OrderLineIn = { item_id: string; unit_id: string | null; qty: string; unit_cost: string | null };
export type OrderIn = {
  warehouse_id: string;
  supplier_id: string;
  order_date: string;
  expected_date: string | null;
  note: string | null;
  lines: OrderLineIn[];
};

export type InvoiceLine = {
  id: string;
  line_no: number;
  item_id: string;
  item_code: string;
  item_name: string;
  unit_id: string;
  unit_name: string;
  qty: string;
  base_qty: string;
  unit_cost: string;
  gross: string;
  discount: string;
  net: string;
  vat_rate: string;
  tax: string;
  landed: string;
  total_cost: string;
  expiry_date: string | null;
  order_line_id: string | null;
  original_line_id: string | null;
  returnable_qty: string | null;
};

export type Charge = {
  id: string;
  line_no: number;
  description: string;
  amount: string;
  payee_id: string | null;
  payee_name: string;
};

export type Invoice = {
  id: string;
  kind: InvoiceKind;
  status: InvoiceStatus;
  number: number | null;
  branch_id: string;
  warehouse_id: string;
  warehouse_name: string;
  supplier_id: string;
  supplier_name: string;
  document_date: string;
  supplier_invoice_no: string | null;
  supplier_invoice_date: string | null;
  due_date: string | null;
  order_id: string | null;
  order_number: number | null;
  original_invoice_id: string | null;
  original_number: number | null;
  subtotal: string;
  discount_total: string;
  tax_total: string;
  charges_total: string;
  grand_total: string;
  cost_total: string;
  note: string | null;
  voucher_id: string | null;
  stock_document_id: string | null;
  lines: InvoiceLine[];
  charges: Charge[];
  warnings: string[];
  created_at: string;
  finalized_at: string | null;
  row_version: string;
};

export type InvoiceSummary = {
  id: string;
  kind: InvoiceKind;
  status: InvoiceStatus;
  number: number | null;
  supplier_id: string;
  supplier_name: string;
  supplier_invoice_no: string | null;
  document_date: string;
  due_date: string | null;
  grand_total: string;
};

export type InvoiceLineIn = {
  item_id: string;
  unit_id: string | null;
  qty: string;
  unit_cost: string;
  discount: string;
  vat_rate: string | null;
  expiry_date: string | null;
  order_line_id: string | null;
};
export type ChargeIn = { description: string; amount: string; payee_id: string | null };
export type InvoiceIn = {
  warehouse_id: string;
  supplier_id: string;
  document_date: string;
  supplier_invoice_no: string | null;
  supplier_invoice_date: string | null;
  due_date: string | null;
  order_id: string | null;
  note: string | null;
  lines: InvoiceLineIn[];
  charges: ChargeIn[];
};

export type ReturnIn = { document_date: string; reason: string; lines: { original_line_id: string; qty: string }[] };

export type PriceHistory = {
  invoice_id: string;
  number: number | null;
  document_date: string;
  supplier_name: string;
  qty: string;
  unit_name: string;
  unit_cost: string;
  base_unit_cost: string;
};

export type Due = {
  supplier_id: string;
  supplier_name: string;
  invoice_id: string;
  number: number | null;
  supplier_invoice_no: string | null;
  document_date: string;
  due_date: string;
  grand_total: string;
  outstanding: string;
  supplier_balance: string;
  overdue_days: number;
};

export const ORDER_STATUS: Record<OrderStatus, { label: string; tone: Tone }> = {
  draft: { label: "پیش‌نویس", tone: "warning" },
  approved: { label: "تأییدشده", tone: "info" },
  closed: { label: "بسته", tone: "success" },
  cancelled: { label: "لغوشده", tone: "danger" },
};

export const KIND_LABEL: Record<InvoiceKind, string> = { invoice: "خرید", return: "برگشت از خرید" };

export const usePriceHistory = (itemId: string | null) =>
  useQuery({
    queryKey: ["purchasing", "price-history", itemId],
    queryFn: () => api.get<PriceHistory[]>(`/purchasing/items/${itemId}/price-history`),
    enabled: !!itemId,
  });

export const useDues = (days: number) =>
  useQuery({ queryKey: ["purchasing", "dues", days], queryFn: () => api.get<Due[]>(`/purchasing/dues?days=${days}`) });

/** Organisation default VAT rate, used only for the client-side preview. */
export function useDefaultVatRate(): string {
  const { data } = useQuery({
    queryKey: ["organization"],
    queryFn: () => api.get<Organization>("/organization/settings"),
    staleTime: 300_000,
  });
  return data?.default_vat_rate ?? "0";
}
