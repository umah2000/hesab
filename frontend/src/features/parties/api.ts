import { useQuery } from "@tanstack/react-query";
import { api, type Page } from "@/lib/api";

export type PartyType = "person" | "company";

export type PartySummary = {
  id: string;
  code: string;
  name: string;
  party_type: PartyType;
  is_customer: boolean;
  is_supplier: boolean;
  group_name: string | null;
  mobile: string | null;
  credit_limit: string | null;
  /** Credit sales with no limit (credit_limit is then null). */
  credit_unlimited: boolean;
  /** Rials; positive = the party owes us, negative = we owe them. */
  balance: string;
  is_active: boolean;
};

export type Party = PartySummary & {
  group_id: string | null;
  national_id: string | null;
  economic_code: string | null;
  registration_no: string | null;
  phone: string | null;
  email: string | null;
  postal_code: string | null;
  city: string | null;
  address: string | null;
  payment_terms_days: number | null;
  /** Identity and contact fields are masked for users without parties.manage. */
  masked: boolean;
  created_at: string;
  row_version: string;
};

export type StatementLine = {
  voucher_id: string;
  voucher_number: number | null;
  document_date: string;
  description: string | null;
  account_code: string;
  account_name: string;
  debit: string;
  credit: string;
  balance: string;
};

export type Statement = {
  party_id: string;
  party_name: string;
  date_from: string | null;
  date_to: string | null;
  opening_balance: string;
  total_debit: string;
  total_credit: string;
  closing_balance: string;
  lines: StatementLine[];
};

export type Note = {
  id: string;
  party_id: string;
  party_name: string;
  body: string;
  follow_up_on: string | null;
  done: boolean;
  author: string;
  created_at: string;
};

export type PartyGroup = { id: string; code: string; name: string };

export type PartyOption = { id: string; code: string; name: string; hint?: string };

/** Active parties for pickers (suppliers for purchasing, customers or both for treasury). */
export function usePartyOptions(role?: "customer" | "supplier") {
  return useQuery({
    queryKey: ["parties", "options", role ?? "all"],
    queryFn: async () => {
      const params = new URLSearchParams({ page_size: "200", active: "true" });
      if (role) params.set("role", role);
      const page = await api.get<Page<PartySummary>>(`/parties?${params}`);
      return page.items.map<PartyOption>((p) => ({
        id: p.id,
        code: p.code,
        name: p.name,
        hint: p.is_customer && p.is_supplier ? "مشتری و تأمین‌کننده" : p.is_supplier ? "تأمین‌کننده" : "مشتری",
      }));
    },
    staleTime: 30_000,
  });
}

export const usePartyGroups = () =>
  useQuery({ queryKey: ["parties", "groups"], queryFn: () => api.get<PartyGroup[]>("/parties/groups") });
