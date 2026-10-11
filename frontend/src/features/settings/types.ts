export type Organization = {
  id: string;
  name: string;
  display_currency: "IRR" | "IRT";
  timezone: string;
  negative_stock_policy: "deny" | "warn" | "allow";
  last_offsite_backup_at: string | null;
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
