export type Organization = {
  id: string;
  name: string;
  display_currency: "IRR" | "IRT";
  timezone: string;
  negative_stock_policy: "deny" | "warn" | "allow";
  last_offsite_backup_at: string | null;
  default_vat_rate: string;
  prices_include_vat: boolean;
  cashier_discount_limit: string;
  backup_warning_days: number;
  receipt_header: string | null;
  receipt_footer: string | null;
  invoice_paper: "thermal" | "a5" | "a4";
  about: string | null;
  phone: string | null;
  address: string | null;
  website: string | null;
  /** Changes with every new logo; null = no logo. */
  logo_version: string | null;
  row_version: string;
};

export type Branch = {
  id: string;
  code: string;
  name: string;
  address: string | null;
  is_active: boolean;
  row_version: string;
};

export type CashRegister = {
  id: string;
  branch_id: string;
  code: string;
  name: string;
  is_active: boolean;
  row_version: string;
};
