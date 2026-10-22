import type { Tone } from "@/components/ui/feedback";

export type OrderStatus = "submitted" | "approved" | "rejected" | "invoiced" | "delivered" | "cancelled";

export const ORDER_STATUS: Record<OrderStatus, { label: string; tone: Tone }> = {
  submitted: { label: "در انتظار بررسی", tone: "warning" },
  approved: { label: "تأییدشده", tone: "info" },
  rejected: { label: "ردشده", tone: "danger" },
  invoiced: { label: "فاکتورشده", tone: "brand" },
  delivered: { label: "تحویل‌شده", tone: "success" },
  cancelled: { label: "لغو ویزیتور", tone: "neutral" },
};

export const WEEKDAYS = ["شنبه", "یکشنبه", "دوشنبه", "سه‌شنبه", "چهارشنبه", "پنجشنبه", "جمعه"];

export const OUTCOME_LABEL: Record<string, string> = {
  order: "سفارش گرفت",
  no_order: "بدون سفارش",
  closed: "مغازه بسته بود",
  absent: "مسئول خرید نبود",
};

export type Visitor = {
  id: string;
  user_id: string;
  username: string;
  name: string;
  branch_id: string;
  branch_name: string;
  code: string;
  is_active: boolean;
  note: string | null;
  customer_count: number;
  last_seen_at: string | null;
  row_version: string;
};

export type Candidate = { user_id: string; username: string; full_name: string; visitor_id: string | null };

export type AssignedCustomer = {
  customer_id: string;
  code: string;
  name: string;
  phone: string | null;
  address: string | null;
  visit_weekday: number | null;
  credit_limit: string | null;
  credit_unlimited: boolean;
  balance: string;
  available: string | null;
};

export type OrderLine = {
  line_no: number;
  item_id: string;
  item_code: string;
  item_name: string;
  unit_id: string;
  unit_name: string;
  qty: string;
  unit_price: string;
  gross: string;
  promotion_name: string | null;
  promotion_discount: string;
  vat_rate: string;
  tax: string;
  line_total: string;
};

export type Order = {
  id: string;
  number: number | null;
  status: OrderStatus;
  branch_id: string;
  visitor_id: string;
  visitor_name: string;
  customer_id: string;
  customer_name: string;
  ordered_at: string;
  received_at: string;
  subtotal: string;
  discount_total: string;
  tax_total: string;
  grand_total: string;
  client_total: string | null;
  price_changed: boolean;
  note: string | null;
  decided_by_name: string | null;
  decided_at: string | null;
  decision_note: string | null;
  invoice_id: string | null;
  invoice_number: number | null;
  delivered_at: string | null;
  lines: OrderLine[];
  warnings: string[];
  row_version: string;
};

export type OrderSummary = Pick<
  Order,
  "id" | "number" | "status" | "visitor_name" | "customer_name" | "ordered_at" | "received_at" | "grand_total" | "price_changed" | "invoice_number"
>;

export type Visit = {
  id: string;
  visitor_name: string;
  customer_id: string;
  customer_name: string;
  visited_at: string;
  received_at: string;
  outcome: string;
  note: string | null;
  order_id: string | null;
};
