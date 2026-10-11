import { keepPreviousData, useQuery } from "@tanstack/react-query";
import { CheckCircle2, Printer, TriangleAlert } from "lucide-react";
import * as React from "react";
import { Link } from "react-router";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { EmptyState, ErrorBox, Spinner } from "@/components/ui/feedback";
import { Checkbox, Field, Select } from "@/components/ui/form-controls";
import { Pagination } from "@/components/ui/table";
import { api, type Page } from "@/lib/api";
import { type DisplayCurrency, formatMoney, toFaDigits } from "@/lib/format";
import { isoToJalaliFa } from "@/lib/jalali";
import { cn } from "@/lib/utils";
import { type FiscalYear, type Level, type Voucher, useAccounts, useCurrency, useCurrentYear, useDetailAccounts, useFiscalYears } from "./api";
import { JalaliDateInput, Picker, accountOptions, detailOptions } from "./inputs";

type TBRow = {
  account_id: string;
  code: string;
  name: string;
  level: Level;
  opening_debit: string;
  opening_credit: string;
  turnover_debit: string;
  turnover_credit: string;
  balance_debit: string;
  balance_credit: string;
};
type TB = { rows: TBRow[]; totals: TBRow; is_balanced: boolean };
type LedgerRow = {
  voucher_id: string;
  voucher_number: number;
  document_date: string;
  account_code: string;
  detail_account_name: string | null;
  description: string | null;
  debit: string;
  credit: string;
  balance: string;
};
type Ledger = {
  account_code: string;
  account_name: string;
  opening_balance: string;
  rows: LedgerRow[];
  total: number;
  page: number;
  page_size: number;
  period_debit: string;
  period_credit: string;
  closing_balance: string;
};

const m = (v: string, c: DisplayCurrency) => (v.startsWith("0.0000") || v === "0" ? "" : formatMoney(v, c));
const balanceText = (v: string, c: DisplayCurrency) =>
  v.startsWith("-") ? `${formatMoney(v.slice(1), c)} بس` : v.replace(/[0.]/g, "") ? `${formatMoney(v, c)} بد` : "—";

function Filters({
  years,
  fy,
  setFy,
  from,
  setFrom,
  to,
  setTo,
  children,
}: {
  years: FiscalYear[];
  fy: string;
  setFy: (v: string) => void;
  from: string | null;
  setFrom: (v: string | null) => void;
  to: string | null;
  setTo: (v: string | null) => void;
  children?: React.ReactNode;
}) {
  return (
    <div className="flex flex-wrap items-end gap-3 p-4 print:hidden">
      <Field label="سال مالی" className="w-40">
        <Select value={fy} onChange={(e) => setFy(e.target.value)}>
          {years.map((y) => (
            <option key={y.id} value={y.id}>{y.title}</option>
          ))}
        </Select>
      </Field>
      <Field label="از تاریخ" className="w-32">
        <JalaliDateInput value={from} onChange={setFrom} placeholder="ابتدای سال" />
      </Field>
      <Field label="تا تاریخ" className="w-32">
        <JalaliDateInput value={to} onChange={setTo} placeholder="پایان سال" />
      </Field>
      {children}
      <div className="flex-1" />
      <Button variant="outline" onClick={() => window.print()}>
        <Printer /> چاپ
      </Button>
    </div>
  );
}

function TrialBalance({ fy, from, to }: { fy: string; from: string | null; to: string | null }) {
  const currency = useCurrency();
  const [level, setLevel] = React.useState<Level>("subsidiary");
  const [includeClosing, setIncludeClosing] = React.useState(false);
  const params = new URLSearchParams({ fiscal_year_id: fy, level, include_closing: String(includeClosing) });
  if (from) params.set("date_from", from);
  if (to) params.set("date_to", to);
  const q = useQuery({
    queryKey: ["accounting", "tb", params.toString()],
    queryFn: () => api.get<TB>(`/accounting/reports/trial-balance?${params}`),
    placeholderData: keepPreviousData,
  });
  const cols: (keyof TBRow)[] = ["opening_debit", "opening_credit", "turnover_debit", "turnover_credit", "balance_debit", "balance_credit"];
  return (
    <>
      <div className="flex flex-wrap items-center gap-4 px-4 pb-3 print:hidden">
        <div className="flex gap-1 rounded-xl bg-black/5 p-1 dark:bg-white/5" role="radiogroup" aria-label="سطح">
          {(["group", "general", "subsidiary"] as Level[]).map((l) => (
            <button
              key={l}
              type="button"
              role="radio"
              aria-checked={level === l}
              onClick={() => setLevel(l)}
              className={cn("rounded-lg px-3 py-1.5 text-sm", level === l ? "bg-white font-semibold text-brand-600 shadow-sm dark:bg-white/15 dark:text-white" : "text-ink-soft")}
            >
              {l === "group" ? "گروه" : l === "general" ? "کل" : "معین"}
            </button>
          ))}
        </div>
        <label className="flex cursor-pointer items-center gap-2 text-sm text-ink-soft">
          <Checkbox checked={includeClosing} onCheckedChange={(c) => setIncludeClosing(c === true)} />
          شامل سند اختتامیه
        </label>
        {q.data ? (
          q.data.is_balanced ? (
            <span className="flex items-center gap-1 text-sm text-success"><CheckCircle2 className="size-4" /> تراز است</span>
          ) : (
            <span className="flex items-center gap-1 text-sm text-danger"><TriangleAlert className="size-4" /> تراز نیست</span>
          )
        ) : null}
      </div>
      <div className="surface mx-4 mb-4 overflow-x-auto rounded-2xl">
        {q.isLoading ? (
          <Spinner />
        ) : q.isError ? (
          <ErrorBox error={q.error} />
        ) : !q.data?.rows.length ? (
          <EmptyState icon={CheckCircle2} title="در این بازه سند قطعی وجود ندارد" />
        ) : (
          <table className="w-full min-w-[64rem] text-sm">
            <thead>
              <tr className="text-xs text-ink-faint">
                <th rowSpan={2} className="px-3 py-2 text-start">حساب</th>
                <th colSpan={2} className="border-b border-[var(--line)] px-3 py-2">مانده ابتدای دوره</th>
                <th colSpan={2} className="border-b border-[var(--line)] px-3 py-2">گردش دوره</th>
                <th colSpan={2} className="border-b border-[var(--line)] px-3 py-2">مانده پایان دوره</th>
              </tr>
              <tr className="text-xs text-ink-faint">
                {["بدهکار", "بستانکار", "بدهکار", "بستانکار", "بدهکار", "بستانکار"].map((h, i) => (
                  <th key={i} className="px-3 py-2 text-start">{h}</th>
                ))}
              </tr>
            </thead>
            <tbody>
              {q.data.rows.map((r) => (
                <tr key={r.account_id} className="border-t border-[var(--line)] hover:bg-brand-500/[0.04]">
                  <td className="px-3 py-2">
                    <span className="tabular text-ink-faint">{toFaDigits(r.code)}</span> {r.name}
                  </td>
                  {cols.map((c) => (
                    <td key={c} className="tabular px-3 py-2">{m(r[c] as string, currency)}</td>
                  ))}
                </tr>
              ))}
            </tbody>
            <tfoot>
              <tr className="border-t-2 border-[var(--line)] bg-[var(--surface-muted)] font-bold">
                <td className="px-3 py-3">جمع کل</td>
                {cols.map((c) => (
                  <td key={c} className="tabular px-3 py-3">{formatMoney(q.data.totals[c] as string, currency)}</td>
                ))}
              </tr>
            </tfoot>
          </table>
        )}
      </div>
    </>
  );
}

function LedgerReport({ fy, from, to }: { fy: string; from: string | null; to: string | null }) {
  const currency = useCurrency();
  const accounts = useAccounts();
  const details = useDetailAccounts();
  const [account, setAccount] = React.useState<string | null>(null);
  const [detail, setDetail] = React.useState<string | null>(null);
  const [page, setPage] = React.useState(1);
  const params = new URLSearchParams({ fiscal_year_id: fy, page: String(page), page_size: "100" });
  if (account) params.set("account_id", account);
  if (detail) params.set("detail_account_id", detail);
  if (from) params.set("date_from", from);
  if (to) params.set("date_to", to);
  const q = useQuery({
    queryKey: ["accounting", "ledger", params.toString()],
    queryFn: () => api.get<Ledger>(`/accounting/reports/ledger?${params}`),
    enabled: !!account,
    placeholderData: keepPreviousData,
  });
  return (
    <>
      <div className="grid gap-3 px-4 pb-3 sm:grid-cols-2 print:hidden">
        <Picker options={accountOptions(accounts.data)} value={account} onChange={(v) => { setAccount(v); setPage(1); }} placeholder="حساب (گروه، کل یا معین)" ariaLabel="حساب" />
        <Picker options={detailOptions(details.data)} value={detail} onChange={(v) => { setDetail(v); setPage(1); }} placeholder="تفصیلی (اختیاری)" ariaLabel="تفصیلی" />
      </div>
      <div className="surface mx-4 mb-4 overflow-x-auto rounded-2xl">
        {!account ? (
          <EmptyState icon={CheckCircle2} title="حساب را انتخاب کنید" description="دفتر کل برای حساب گروه/کل و دفتر معین برای حساب معین نمایش داده می‌شود." />
        ) : q.isLoading ? (
          <Spinner />
        ) : q.isError ? (
          <ErrorBox error={q.error} />
        ) : q.data ? (
          <>
            <table className="w-full min-w-[60rem] text-sm">
              <thead>
                <tr className="text-xs text-ink-faint">
                  <th className="w-28 px-3 py-3 text-start">تاریخ</th>
                  <th className="w-20 px-3 py-3 text-start">سند</th>
                  <th className="px-3 py-3 text-start">شرح</th>
                  <th className="w-40 px-3 py-3 text-start">بدهکار</th>
                  <th className="w-40 px-3 py-3 text-start">بستانکار</th>
                  <th className="w-44 px-3 py-3 text-start">مانده</th>
                </tr>
              </thead>
              <tbody>
                {page === 1 ? (
                  <tr className="border-t border-[var(--line)] bg-[var(--surface-muted)]">
                    <td colSpan={5} className="px-3 py-2 text-ink-soft">مانده ابتدای دوره</td>
                    <td className="tabular px-3 py-2 font-semibold">{balanceText(q.data.opening_balance, currency)}</td>
                  </tr>
                ) : null}
                {q.data.rows.map((r, i) => (
                  <tr key={`${r.voucher_id}-${i}`} className="border-t border-[var(--line)] hover:bg-brand-500/[0.04]">
                    <td className="tabular px-3 py-2 text-ink-soft">{isoToJalaliFa(r.document_date)}</td>
                    <td className="tabular px-3 py-2">
                      <Link className="text-brand-600 hover:underline dark:text-brand-300" to={`/accounting/vouchers/${r.voucher_id}`}>{toFaDigits(r.voucher_number)}</Link>
                    </td>
                    <td className="px-3 py-2">
                      {r.description}
                      {r.detail_account_name ? <span className="text-xs text-ink-faint"> · {r.detail_account_name}</span> : null}
                    </td>
                    <td className="tabular px-3 py-2">{m(r.debit, currency)}</td>
                    <td className="tabular px-3 py-2">{m(r.credit, currency)}</td>
                    <td className="tabular px-3 py-2">{balanceText(r.balance, currency)}</td>
                  </tr>
                ))}
              </tbody>
              <tfoot>
                <tr className="border-t-2 border-[var(--line)] bg-[var(--surface-muted)] font-bold">
                  <td colSpan={3} className="px-3 py-3">جمع گردش و مانده پایان دوره</td>
                  <td className="tabular px-3 py-3">{formatMoney(q.data.period_debit, currency)}</td>
                  <td className="tabular px-3 py-3">{formatMoney(q.data.period_credit, currency)}</td>
                  <td className="tabular px-3 py-3">{balanceText(q.data.closing_balance, currency)}</td>
                </tr>
              </tfoot>
            </table>
            <Pagination page={page} pageSize={100} total={q.data.total} onPage={setPage} />
          </>
        ) : null}
      </div>
    </>
  );
}

function Journal({ fy, from, to }: { fy: string; from: string | null; to: string | null }) {
  const currency = useCurrency();
  const [page, setPage] = React.useState(1);
  const params = new URLSearchParams({ fiscal_year_id: fy, page: String(page), page_size: "20" });
  if (from) params.set("date_from", from);
  if (to) params.set("date_to", to);
  const q = useQuery({
    queryKey: ["accounting", "journal", params.toString()],
    queryFn: () => api.get<Page<Voucher>>(`/accounting/reports/journal?${params}`),
    placeholderData: keepPreviousData,
  });
  return (
    <div className="surface mx-4 mb-4 overflow-x-auto rounded-2xl">
      {q.isLoading ? (
        <Spinner />
      ) : q.isError ? (
        <ErrorBox error={q.error} />
      ) : !q.data?.items.length ? (
        <EmptyState icon={CheckCircle2} title="در این بازه سند قطعی وجود ندارد" />
      ) : (
        <>
          <table className="w-full min-w-[56rem] text-sm">
            <thead>
              <tr className="text-xs text-ink-faint">
                <th className="w-28 px-3 py-3 text-start">تاریخ / سند</th>
                <th className="px-3 py-3 text-start">حساب و شرح</th>
                <th className="w-40 px-3 py-3 text-start">بدهکار</th>
                <th className="w-40 px-3 py-3 text-start">بستانکار</th>
              </tr>
            </thead>
            {q.data.items.map((v) => (
              <tbody key={v.id} className="border-t-2 border-[var(--line)]">
                {v.lines.map((l, i) => (
                  <tr key={l.id}>
                    <td className="tabular px-3 py-1.5 align-top text-ink-soft">
                      {i === 0 ? (
                        <>
                          {isoToJalaliFa(v.document_date)}
                          <br />
                          <Link className="text-brand-600 hover:underline dark:text-brand-300" to={`/accounting/vouchers/${v.id}`}>سند {toFaDigits(v.number ?? 0)}</Link>
                        </>
                      ) : null}
                    </td>
                    <td className={cn("px-3 py-1.5", Number(l.credit) > 0 && "ps-10")}>
                      <span className="tabular text-ink-faint">{toFaDigits(l.account_code)}</span> {l.account_name}
                      {l.detail_account_name ? <span className="text-ink-faint"> / {l.detail_account_name}</span> : null}
                      {l.description ? <span className="block text-xs text-ink-faint">{l.description}</span> : null}
                    </td>
                    <td className="tabular px-3 py-1.5">{m(l.debit, currency)}</td>
                    <td className="tabular px-3 py-1.5">{m(l.credit, currency)}</td>
                  </tr>
                ))}
              </tbody>
            ))}
          </table>
          <Pagination page={page} pageSize={20} total={q.data.total} onPage={setPage} />
        </>
      )}
    </div>
  );
}

export function ReportsPage() {
  const years = useFiscalYears();
  const current = useCurrentYear();
  const [fy, setFy] = React.useState("");
  const [from, setFrom] = React.useState<string | null>(null);
  const [to, setTo] = React.useState<string | null>(null);
  const [tab, setTab] = React.useState<"tb" | "ledger" | "journal">("tb");
  const fyId = fy || current?.id || "";

  if (years.isLoading) return <Spinner />;
  if (!fyId) return <Card><EmptyState icon={CheckCircle2} title="سال مالی تعریف نشده است" /></Card>;

  return (
    <Card>
      <div className="flex gap-1 px-4 pt-4 print:hidden" role="tablist">
        {[
          ["tb", "تراز آزمایشی"],
          ["ledger", "دفتر کل / معین"],
          ["journal", "دفتر روزنامه"],
        ].map(([k, label]) => (
          <button
            key={k}
            type="button"
            role="tab"
            aria-selected={tab === k}
            onClick={() => setTab(k as typeof tab)}
            className={cn("rounded-xl px-4 py-2 text-sm font-medium", tab === k ? "bg-brand-500 text-white" : "text-ink-soft hover:bg-black/5 dark:hover:bg-white/10")}
          >
            {label}
          </button>
        ))}
      </div>
      <Filters years={years.data ?? []} fy={fyId} setFy={setFy} from={from} setFrom={setFrom} to={to} setTo={setTo} />
      {tab === "tb" ? <TrialBalance fy={fyId} from={from} to={to} /> : tab === "ledger" ? <LedgerReport fy={fyId} from={from} to={to} /> : <Journal fy={fyId} from={from} to={to} />}
    </Card>
  );
}
