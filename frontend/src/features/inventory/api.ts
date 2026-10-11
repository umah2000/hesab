import { useQuery } from "@tanstack/react-query";
import { api } from "@/lib/api";

export type Unit = { id: string; code: string; name: string; allows_fraction: boolean };
export type Group = { id: string; code: string; name: string; parent_id: string | null; row_version: string };
export type Warehouse = { id: string; branch_id: string; code: string; name: string; is_active: boolean; row_version: string };
export type PriceList = { id: string; code: string; name: string; is_default: boolean; is_active: boolean };

export type ItemUnit = { unit_id: string; factor: string };
export type Barcode = { barcode: string; unit_id: string | null };
export type Price = { price_list_id: string | null; unit_id: string | null; price: string };

export type Item = {
  id: string;
  code: string;
  name: string;
  group_id: string | null;
  group_name: string | null;
  base_unit_id: string;
  base_unit_name: string;
  item_type: "goods" | "service";
  is_weighted: boolean;
  scale_code: string | null;
  track_expiry: boolean;
  vat_exempt: boolean;
  vat_rate: string | null;
  tax_item_code: string | null;
  min_qty: string | null;
  max_qty: string | null;
  is_active: boolean;
  units: ItemUnit[];
  barcodes: Barcode[];
  prices: Price[];
  stock_qty: string | null;
  row_version: string;
};

export type ItemSummary = {
  id: string;
  code: string;
  name: string;
  group_name: string | null;
  base_unit_name: string;
  is_weighted: boolean;
  is_active: boolean;
  barcode: string | null;
  price: string | null;
  stock_qty: string;
};

export type Lookup = {
  item_id: string;
  code: string;
  name: string;
  unit_id: string;
  unit_name: string;
  qty: string;
  unit_price: string | null;
  line_price: string | null;
  source: "barcode" | "pack_barcode" | "scale_weight" | "scale_price" | "code";
  is_weighted: boolean;
  vat_exempt: boolean;
  vat_rate: string | null;
};

export type ScaleRule = {
  id: string;
  name: string;
  prefix: string;
  item_code_length: number;
  value_length: number;
  value_type: "weight" | "price";
  value_decimals: number;
  is_active: boolean;
  row_version: string;
};

export type DocType = "opening" | "adjustment" | "transfer" | "count";
export const DOC_LABEL: Record<DocType, string> = {
  opening: "موجودی اول دوره",
  adjustment: "تعدیل موجودی",
  transfer: "انتقال بین انبارها",
  count: "شمارش موجودی",
};

export type StockLine = {
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
  total_cost: string | null;
  system_qty: string | null;
  expiry_date: string | null;
  description: string | null;
};

export type StockDoc = {
  id: string;
  branch_id: string;
  warehouse_id: string;
  dest_warehouse_id: string | null;
  doc_type: DocType;
  number: number | null;
  document_date: string;
  status: "draft" | "final";
  description: string | null;
  voucher_id: string | null;
  voucher_number: number | null;
  source_document_id: string | null;
  total_value: string | null;
  finalized_at: string | null;
  row_version: string;
  lines: StockLine[];
};

export type StockDocSummary = {
  id: string;
  doc_type: DocType;
  number: number | null;
  document_date: string;
  status: "draft" | "final";
  warehouse_id: string;
  dest_warehouse_id: string | null;
  description: string | null;
  line_count: number;
};

export const useUnits = () =>
  useQuery({ queryKey: ["inventory", "units"], queryFn: () => api.get<Unit[]>("/inventory/units"), staleTime: 600_000 });
export const useGroups = () =>
  useQuery({ queryKey: ["inventory", "groups"], queryFn: () => api.get<Group[]>("/inventory/groups"), staleTime: 60_000 });
export const useWarehouses = () =>
  useQuery({ queryKey: ["inventory", "warehouses"], queryFn: () => api.get<Warehouse[]>("/inventory/warehouses"), staleTime: 60_000 });

/** Trim the trailing zeros of a decimal string for display ("12.500" → "12.5"). */
export function trimQty(v: string | null | undefined): string {
  if (!v) return "0";
  return v.includes(".") ? v.replace(/\.?0+$/, "") || "0" : v;
}
