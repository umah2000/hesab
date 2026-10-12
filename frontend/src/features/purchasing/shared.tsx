import { type QueryClient, useQueries } from "@tanstack/react-query";
import { X } from "lucide-react";
import * as React from "react";
import { Link } from "react-router";
import { toast } from "sonner";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/feedback";
import { Picker } from "@/features/accounting/inputs";
import type { Item } from "@/features/inventory/api";
import type { PartyOption } from "@/features/parties/api";
import { ApiError, api } from "@/lib/api";
import { toFaDigits } from "@/lib/format";
import { KIND_LABEL, ORDER_STATUS, type InvoiceKind, type InvoiceStatus, type OrderStatus } from "./api";

export const onError = (e: unknown) => toast.error(e instanceof ApiError ? e.message : "خطا");

/** The server definitively rejected the request: a retry is a new submit with a new key. */
export const rejected = (e: unknown) => e instanceof ApiError && e.status > 0;

export const linkCls = "text-sm text-brand-600 underline dark:text-brand-300";

export function InvoiceStatusBadge({ status }: { status: InvoiceStatus }) {
  return status === "final" ? <Badge tone="success">قطعی</Badge> : <Badge tone="warning">پیش‌نویس</Badge>;
}

export function KindBadge({ kind }: { kind: InvoiceKind }) {
  return kind === "invoice" ? (
    <Badge tone="brand" icon={false}>{KIND_LABEL.invoice}</Badge>
  ) : (
    <Badge tone="warning">{KIND_LABEL.return}</Badge>
  );
}

export function OrderStatusBadge({ status }: { status: OrderStatus }) {
  const s = ORDER_STATUS[status];
  return <Badge tone={s.tone}>{s.label}</Badge>;
}

export const itemQuery = (id: string) => ({
  queryKey: ["inventory", "item", id],
  queryFn: () => api.get<Item>(`/inventory/items/${id}`),
  staleTime: 60_000,
});

export const fetchItem = (qc: QueryClient, id: string) => qc.fetchQuery(itemQuery(id));

/** Item details (units, expiry tracking, VAT) for every line, keyed by item id. */
export function useItemsMeta(ids: string[]): Record<string, Item> {
  const unique = [...new Set(ids)];
  const results = useQueries({ queries: unique.map((id) => itemQuery(id)) });
  const out: Record<string, Item> = {};
  results.forEach((r, i) => {
    if (r.data) out[unique[i]] = r.data;
  });
  return out;
}

/** Unit options of an item: base unit (factor 1) then its alternative units. */
export function unitOptions(item: Item | undefined, unitName: (id: string) => string, fallback?: { id: string; name: string }) {
  if (!item) return fallback ? [{ id: fallback.id, name: fallback.name, factor: "1" }] : [];
  return [
    { id: item.base_unit_id, name: item.base_unit_name || unitName(item.base_unit_id), factor: "1" },
    ...item.units.map((u) => ({ id: u.unit_id, name: unitName(u.unit_id), factor: u.factor })),
  ];
}

export function PartyPicker({
  options,
  value,
  onChange,
  ariaLabel,
  placeholder,
  disabled,
  fallbackName,
  className,
}: {
  options: PartyOption[];
  value: string | null;
  onChange: (id: string | null) => void;
  ariaLabel: string;
  placeholder?: string;
  disabled?: boolean;
  /** Shown read-only when the party is not among the (active) options. */
  fallbackName?: string;
  className?: string;
}) {
  if (disabled) {
    const o = options.find((x) => x.id === value);
    return <p className="py-2">{o ? `${toFaDigits(o.code)} — ${o.name}` : fallbackName || "—"}</p>;
  }
  return (
    <div className={`flex items-center gap-1 ${className ?? ""}`}>
      <Picker className="flex-1" options={options} value={value} onChange={onChange} ariaLabel={ariaLabel} placeholder={placeholder} />
      {value ? (
        <Button variant="ghost" size="icon" aria-label={`پاک کردن ${ariaLabel}`} onClick={() => onChange(null)}>
          <X />
        </Button>
      ) : null}
    </div>
  );
}

export function DocLink({ to, children }: { to: string; children: React.ReactNode }) {
  return (
    <Link className={linkCls} to={to}>
      {children}
    </Link>
  );
}
