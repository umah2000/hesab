import { keepPreviousData, useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { ArrowLeft, BarChart3, BookmarkPlus, FileSpreadsheet, Printer, Trash2 } from "lucide-react";
import * as React from "react";
import { Link, useParams, useSearchParams } from "react-router";
import { toast } from "sonner";
import { PageTitle } from "@/components/layout/AppShell";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { Badge, EmptyState, ErrorBox, Spinner } from "@/components/ui/feedback";
import { Checkbox, Field, Input, Select } from "@/components/ui/form-controls";
import { Pagination, Table, Td, Th, Tr } from "@/components/ui/table";
import { useCurrency } from "@/features/accounting/api";
import { JalaliDateInput } from "@/features/accounting/inputs";
import { trimQty, useWarehouses } from "@/features/inventory/api";
import type { Branch } from "@/features/settings/types";
import { ApiError, api } from "@/lib/api";
import { type DisplayCurrency, formatMoney, toFaDigits } from "@/lib/format";
import { isoToJalaliFa } from "@/lib/jalali";
import { cn } from "@/lib/utils";
import { type Column, GROUP_BY, type ReportInfo, type ReportTable, type Row, type SavedFilter } from "./api";

const onError = (e: unknown) => toast.error(e instanceof ApiError ? e.message : "خطا");

export function ReportsHome() {
  const list = useQuery({ queryKey: ["reports", "catalog"], queryFn: () => api.get<ReportInfo[]>("/reports") });
  const groups = React.useMemo(() => {
    const m = new Map<string, ReportInfo[]>();
    for (const r of list.data ?? []) m.set(r.group, [...(m.get(r.group) ?? []), r]);
    return [...m.entries()];
  }, [list.data]);
  return (
    <>
      <PageTitle title="گزارش‌ها" subtitle="همه گزارش‌ها از اسناد قطعی؛ فیلتر ذخیره‌شده، خروجی Excel و چاپ (PDF)" />
      {list.isLoading ? (
        <Spinner />
      ) : list.isError ? (
        <ErrorBox error={list.error} />
      ) : !groups.length ? (
        <Card>
          <EmptyState icon={BarChart3} title="گزارشی برای نقش شما تعریف نشده" />
        </Card>
      ) : (
        <div className="flex flex-col gap-5">
          {groups.map(([group, reports]) => (
            <section key={group}>
              <h2 className="mb-2 text-sm font-bold text-ink-soft">{group}</h2>
              <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-3">
                {reports.map((r) => (
                  <Link
                    key={r.key}
                    to={`/reports/${r.key}`}
                    className="glass group flex items-start gap-3 rounded-2xl p-4 transition hover:-translate-y-0.5 hover:shadow-[var(--shadow-float)]"
                  >
                    <BarChart3 className="mt-0.5 size-5 shrink-0 text-brand-500" />
                    <span className="flex-1">
                      <span className="block font-semibold text-ink">{r.title}</span>
                      <span className="mt-1 block text-xs text-ink-faint">{r.description}</span>
                    </span>
                    <ArrowLeft className="size-4 text-ink-faint transition group-hover:-translate-x-1" />
                  </Link>
                ))}
              </div>
            </section>
          ))}
        </div>
      )}
    </>
  );
}

// --- cell formatting ------------------------------------------------------------------

export function formatCell(c: Column, v: Row[string], currency: DisplayCurrency): string {
  if (v === null || v === undefined || v === "") return "—";
  switch (c.kind) {
    case "money":
      return formatMoney(String(v), currency).replace(/ (تومان|ریال)$/, "");
    case "qty":
      return toFaDigits(trimQty(String(v)).replace(".", "٫"));
    case "int":
      return toFaDigits(String(v));
    case "percent":
      return `${toFaDigits(trimQty(String(v)).replace(".", "٫"))}٪`;
    case "date":
      return /^\d{4}-\d{2}-\d{2}$/.test(String(v)) ? isoToJalaliFa(String(v)) : String(v);
    default:
      return String(v);
  }
}

const isNumeric = (c: Column) => c.kind !== "text" && c.kind !== "date";

function ReportGrid({ table, currency }: { table: ReportTable; currency: DisplayCurrency }) {
  const unit = currency === "IRT" ? "تومان" : "ریال";
  return (
    <Table>
      <thead>
        <tr>
          {table.columns.map((c) => (
            <Th key={c.key} className={cn(isNumeric(c) && "text-start")}>
              {c.label}
              {c.kind === "money" ? <span className="font-normal text-ink-faint"> ({unit})</span> : null}
            </Th>
          ))}
        </tr>
      </thead>
      <tbody>
        {table.rows.map((r, i) => (
          <Tr key={i} className={cn(r._bold && "font-bold")}>
            {table.columns.map((c, ci) => (
              <Td
                key={c.key}
                className={cn(isNumeric(c) && "tabular", ci === 1 && r._level ? "" : "")}
                style={ci === 1 && r._level ? { paddingInlineStart: `${0.75 + r._level * 1.25}rem` } : undefined}
              >
                {formatCell(c, r[c.key], currency)}
              </Td>
            ))}
          </Tr>
        ))}
      </tbody>
      {table.totals ? (
        <tfoot>
          <tr className="border-t-2 border-[var(--line)] font-bold">
            {table.columns.map((c) => (
              <Td key={c.key} className={cn(isNumeric(c) && "tabular")}>
                {table.totals?.[c.key] === undefined ? "" : formatCell(c, table.totals[c.key], currency)}
              </Td>
            ))}
          </tr>
        </tfoot>
      ) : null}
    </Table>
  );
}

// --- one report -------------------------------------------------------------------------

const FILTER_LABEL: Record<string, string> = {
  date_from: "از تاریخ",
  date_to: "تا تاریخ",
  as_of: "تا تاریخ",
  branch_id: "شعبه",
  warehouse_id: "انبار",
  group_by: "تفکیک",
  q: "جست‌وجوی کالا",
  only_moved: "فقط کالاهای دارای گردش",
  days: "بازه (روز)",
  cover_days: "پوشش بیش از (روز)",
};

export function ReportPage() {
  const { key = "" } = useParams();
  const currency = useCurrency();
  const qc = useQueryClient();
  const [search, setSearch] = useSearchParams();
  const catalog = useQuery({ queryKey: ["reports", "catalog"], queryFn: () => api.get<ReportInfo[]>("/reports") });
  const info = catalog.data?.find((r) => r.key === key);
  const branches = useQuery({ queryKey: ["branches"], queryFn: () => api.get<Branch[]>("/organization/branches"), enabled: !!info?.filters.includes("branch_id") });
  const warehouses = useWarehouses();
  const params = React.useMemo(() => {
    const p = new URLSearchParams(search);
    p.delete("page");
    return p;
  }, [search]);
  const page = Number(search.get("page") ?? "1");
  const query = new URLSearchParams(params);
  query.set("page", String(page));
  query.set("page_size", "100");
  const table = useQuery({
    queryKey: ["reports", key, query.toString()],
    queryFn: () => api.get<ReportTable>(`/reports/${key}?${query}`),
    placeholderData: keepPreviousData,
    enabled: !!info,
  });
  const saved = useQuery({ queryKey: ["reports", "saved", key], queryFn: () => api.get<SavedFilter[]>(`/reports/saved-filters?report=${key}`) });
  const save = useMutation({
    mutationFn: (name: string) => api.post<SavedFilter>("/reports/saved-filters", { report: key, name, params: Object.fromEntries(params) }),
    onSuccess: () => {
      toast.success("فیلتر ذخیره شد");
      qc.invalidateQueries({ queryKey: ["reports", "saved", key] });
    },
    onError,
  });
  const remove = useMutation({
    mutationFn: (id: string) => api.del(`/reports/saved-filters/${id}`, ""),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["reports", "saved", key] }),
    onError,
  });

  const set = (k: string, v: string | null) => {
    const next = new URLSearchParams(params);
    if (v === null || v === "") next.delete(k);
    else next.set(k, v);
    setSearch(next, { replace: true });
  };
  if (catalog.isLoading) return <Spinner />;
  if (!info) return <Card><EmptyState icon={BarChart3} title="گزارش یافت نشد یا مجوز آن را ندارید" /></Card>;
  const excelHref = `/api/v1/reports/${key}?${new URLSearchParams([...params.entries(), ["format", "xlsx"]])}`;

  return (
    <>
      <PageTitle
        title={info.title}
        subtitle={info.description}
        actions={
          <div className="no-print flex gap-2">
            <Button variant="outline" asChild>
              <Link to="/reports">همه گزارش‌ها</Link>
            </Button>
          </div>
        }
      />
      <Card className="no-print mb-4">
        <div className="flex flex-wrap items-end gap-3 p-4">
          {info.filters.map((f) => {
            const label = FILTER_LABEL[f] ?? f;
            if (f === "date_from" || f === "date_to" || f === "as_of")
              return (
                <Field key={f} label={label}>
                  <JalaliDateInput className="w-36" value={params.get(f)} onChange={(v) => v !== null && set(f, v)} />
                </Field>
              );
            if (f === "branch_id")
              return (
                <Field key={f} label={label}>
                  <Select value={params.get(f) ?? ""} onChange={(e) => set(f, e.target.value)}>
                    <option value="">همه شعب مجاز</option>
                    {branches.data?.map((b) => <option key={b.id} value={b.id}>{b.name}</option>)}
                  </Select>
                </Field>
              );
            if (f === "warehouse_id")
              return (
                <Field key={f} label={label}>
                  <Select value={params.get(f) ?? ""} onChange={(e) => set(f, e.target.value)}>
                    <option value="">همه انبارها</option>
                    {warehouses.data?.map((w) => <option key={w.id} value={w.id}>{w.name}</option>)}
                  </Select>
                </Field>
              );
            if (f === "group_by")
              return (
                <Field key={f} label={label}>
                  <Select value={params.get(f) ?? GROUP_BY[key]?.[0]?.[0] ?? ""} onChange={(e) => set(f, e.target.value)}>
                    {(GROUP_BY[key] ?? []).map(([v, l]) => <option key={v} value={v}>{l}</option>)}
                  </Select>
                </Field>
              );
            if (f === "only_moved")
              return (
                <label key={f} className="flex h-10 items-center gap-2 text-sm">
                  <Checkbox checked={params.get(f) !== "false"} onCheckedChange={(v) => set(f, v === true ? null : "false")} />
                  {label}
                </label>
              );
            if (f === "days" || f === "cover_days")
              return (
                <Field key={f} label={label}>
                  <Input className="w-28" dir="ltr" inputMode="numeric" value={params.get(f) ?? ""} placeholder={f === "days" ? "30" : "90"} onChange={(e) => set(f, e.target.value.replace(/[^\d]/g, ""))} />
                </Field>
              );
            return (
              <Field key={f} label={label}>
                <Input className="w-48" value={params.get(f) ?? ""} onChange={(e) => set(f, e.target.value)} />
              </Field>
            );
          })}
          <div className="flex-1" />
          <Button variant="outline" asChild>
            <a href={excelHref}>
              <FileSpreadsheet /> Excel
            </a>
          </Button>
          <Button variant="outline" onClick={() => window.print()} title="در پنجره چاپ «ذخیره به‌صورت PDF» را انتخاب کنید">
            <Printer /> چاپ / PDF
          </Button>
          <Button
            variant="outline"
            onClick={() => {
              const name = window.prompt("نام این فیلتر:");
              if (name && name.trim().length >= 2) save.mutate(name.trim());
            }}
          >
            <BookmarkPlus /> ذخیره فیلتر
          </Button>
        </div>
        {saved.data?.length ? (
          <div className="flex flex-wrap items-center gap-2 border-t border-[var(--line)] px-4 py-3 text-sm">
            <span className="text-ink-faint">فیلترهای من:</span>
            {saved.data.map((f) => (
              <span key={f.id} className="inline-flex items-center gap-1 rounded-full bg-brand-500/10 px-3 py-1">
                <button type="button" className="text-brand-700 hover:underline dark:text-brand-300" onClick={() => setSearch(new URLSearchParams(f.params), { replace: true })}>
                  {f.name}
                </button>
                <button type="button" aria-label={`حذف ${f.name}`} className="text-ink-faint hover:text-danger" onClick={() => remove.mutate(f.id)}>
                  <Trash2 className="size-3.5" />
                </button>
              </span>
            ))}
          </div>
        ) : null}
      </Card>
      <Card>
        <div className="hidden p-4 text-lg font-bold print:block">{table.data?.title ?? info.title}</div>
        <div className="surface m-4 overflow-x-auto rounded-2xl">
          {table.isLoading ? (
            <Spinner />
          ) : table.isError ? (
            <ErrorBox error={table.error} />
          ) : !table.data?.rows.length ? (
            <EmptyState icon={BarChart3} title="داده‌ای برای این فیلتر نیست" />
          ) : (
            <ReportGrid table={table.data} currency={currency} />
          )}
        </div>
        {table.data && table.data.total_rows > table.data.page_size ? (
          <div className="no-print mx-4 mb-2">
            <Pagination page={page} pageSize={table.data.page_size} total={table.data.total_rows} onPage={(p) => set("page", String(p))} />
          </div>
        ) : null}
        {table.data?.notes.length ? (
          <ul className="mx-4 mb-4 flex flex-col gap-1 text-xs text-ink-faint">
            {table.data.notes.map((n) => (
              <li key={n}>{n.startsWith("⚠") ? <Badge tone="warning">{n.replace("⚠ ", "")}</Badge> : n}</li>
            ))}
          </ul>
        ) : null}
      </Card>
    </>
  );
}
