import { useQuery } from "@tanstack/react-query";
import * as React from "react";
import type { Organization } from "@/features/settings/types";
import { api } from "@/lib/api";
import type { DisplayCurrency } from "@/lib/format";
import { todayIso } from "@/lib/jalali";

export type Level = "group" | "general" | "subsidiary";
export type Category = "asset" | "liability" | "equity" | "revenue" | "expense";
export type Nature = "debit" | "credit" | "none";

export type Account = {
  id: string;
  code: string;
  name: string;
  level: Level;
  parent_id: string | null;
  category: Category;
  nature: Nature;
  requires_detail: boolean;
  is_active: boolean;
  is_system: boolean;
  row_version: string;
};

export type DetailAccount = {
  id: string;
  code: string;
  name: string;
  kind: "person" | "bank" | "cash" | "cost_center" | "project" | "other";
  is_active: boolean;
  /** Customers: credit-sale limit in rials; null = no credit sales. */
  credit_limit?: string | null;
  /** Customers: credit sales with no limit. */
  credit_unlimited?: boolean;
  row_version: string;
};

export type FiscalPeriod = {
  id: string;
  number: number;
  title: string;
  start_date: string;
  end_date: string;
  is_locked: boolean;
  row_version: string;
};

export type FiscalYear = {
  id: string;
  title: string;
  jalali_year: number;
  start_date: string;
  end_date: string;
  status: "open" | "closed";
  closed_at: string | null;
  periods: FiscalPeriod[];
  row_version: string;
};

export type VoucherLine = {
  id: string;
  line_no: number;
  account_id: string;
  account_code: string;
  account_name: string;
  detail_account_id: string | null;
  detail_account_code: string | null;
  detail_account_name: string | null;
  debit: string;
  credit: string;
  description: string | null;
};

export type Voucher = {
  id: string;
  branch_id: string | null;
  fiscal_year_id: string;
  number: number | null;
  document_date: string;
  status: "draft" | "final";
  description: string | null;
  source_type: "manual" | "opening" | "closing" | "reversal" | "auto";
  source_ref: string | null;
  total_debit: string;
  total_credit: string;
  is_balanced: boolean;
  reversal_of_id: string | null;
  reversed_by_id: string | null;
  finalized_at: string | null;
  created_at: string;
  row_version: string;
  lines: VoucherLine[];
};

export type VoucherSummary = Omit<Voucher, "lines" | "branch_id" | "fiscal_year_id" | "is_balanced" | "finalized_at" | "created_at" | "row_version" | "source_ref"> & {
  line_count: number;
};

export const CATEGORY_LABEL: Record<Category, string> = {
  asset: "دارایی",
  liability: "بدهی",
  equity: "حقوق مالکانه",
  revenue: "درآمد",
  expense: "هزینه",
};
export const NATURE_LABEL: Record<Nature, string> = { debit: "بدهکار", credit: "بستانکار", none: "—" };
export const LEVEL_LABEL: Record<Level, string> = { group: "گروه", general: "کل", subsidiary: "معین" };
export const SOURCE_LABEL: Record<Voucher["source_type"], string> = {
  manual: "دستی",
  opening: "افتتاحیه",
  closing: "اختتامیه",
  reversal: "برگشتی",
  auto: "خودکار",
};

export function useAccounts() {
  return useQuery({
    queryKey: ["accounting", "accounts"],
    queryFn: () => api.get<Account[]>("/accounting/accounts"),
    staleTime: 60_000,
  });
}

export function useDetailAccounts() {
  return useQuery({
    queryKey: ["accounting", "details"],
    queryFn: () => api.get<DetailAccount[]>("/accounting/detail-accounts"),
    staleTime: 60_000,
  });
}

export function useFiscalYears() {
  return useQuery({
    queryKey: ["accounting", "fiscal-years"],
    queryFn: () => api.get<FiscalYear[]>("/accounting/fiscal-years"),
  });
}

/** The fiscal year containing today, else the latest. */
export function useCurrentYear(): FiscalYear | undefined {
  const { data } = useFiscalYears();
  return React.useMemo(() => {
    if (!data?.length) return undefined;
    const today = todayIso();
    return data.find((y) => y.start_date <= today && today <= y.end_date) ?? data[0];
  }, [data]);
}

export function useCurrency(): DisplayCurrency {
  const { data } = useQuery({
    queryKey: ["organization"],
    queryFn: () => api.get<Organization>("/organization/settings"),
    staleTime: 300_000,
  });
  return data?.display_currency ?? "IRT";
}
