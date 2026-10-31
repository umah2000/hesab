import { useQuery } from "@tanstack/react-query";
import { AlertTriangle, ArrowDownLeft, ArrowUpLeft, BarChart3, CalendarClock } from "lucide-react";
import * as React from "react";
import { Link } from "react-router";
import { Card, CardBody, CardHeader } from "@/components/ui/card";
import { Badge, ErrorBox, Skeleton } from "@/components/ui/feedback";
import { Select } from "@/components/ui/form-controls";
import { useCurrency } from "@/features/accounting/api";
import { trimQty } from "@/features/inventory/api";
import { api } from "@/lib/api";
import { type DisplayCurrency, formatMoney, toFaDigits } from "@/lib/format";
import { isoToJalaliFa, todayIso } from "@/lib/jalali";
import { cn } from "@/lib/utils";
import { changePct, type Dashboard } from "./api";

const PRESETS: [string, string, number][] = [
  ["today", "امروز", 1],
  ["7", "۷ روز اخیر", 7],
  ["30", "۳۰ روز اخیر", 30],
  ["90", "۹۰ روز اخیر", 90],
];
const METHOD: Record<string, string> = { cash: "نقد", card: "کارت", credit: "نسیه" };

function shiftIso(iso: string, days: number): string {
  const d = new Date(`${iso}T12:00:00Z`);
  d.setUTCDate(d.getUTCDate() + days);
  return d.toISOString().slice(0, 10);
}

/** Whole rials as a JS number for drawing only (never for money math or display). */
const toNum = (rials: string) => Number(rials.split(".")[0]);

function compact(rials: string, currency: DisplayCurrency): string {
  const v = toNum(rials) / (currency === "IRT" ? 10 : 1);
  const abs = Math.abs(v);
  const fmt = (n: number, s: string) => `${toFaDigits(n.toLocaleString("en-US", { maximumFractionDigits: 1 }))}${s}`;
  if (abs >= 1e9) return fmt(v / 1e9, " میلیارد");
  if (abs >= 1e6) return fmt(v / 1e6, " میلیون");
  if (abs >= 1e3) return fmt(v / 1e3, " هزار");
  return toFaDigits(String(v));
}

function Delta({ current, previous, label }: { current: string; previous: string; label: string }) {
  const pct = changePct(current, previous);
  if (pct === null) return <span className="text-xs text-ink-faint">بدون داده در {label}</span>;
  const up = pct >= 0;
  const Icon = up ? ArrowUpLeft : ArrowDownLeft;
  return (
    <span className={cn("inline-flex items-center gap-1 text-xs font-medium", up ? "text-success" : "text-danger")}>
      <Icon className="size-3.5" aria-hidden />
      {toFaDigits(Math.abs(pct).toLocaleString("en-US", { maximumFractionDigits: 1 }))}٪ {up ? "افزایش" : "کاهش"}
      <span className="font-normal text-ink-faint">نسبت به {label}</span>
    </span>
  );
}

function Kpi({ label, value, children }: { label: string; value: React.ReactNode; children?: React.ReactNode }) {
  return (
    <Card className="p-5">
      <p className="text-sm text-ink-faint">{label}</p>
      <div className="tabular mt-2 text-2xl font-extrabold text-ink">{value}</div>
      {children ? <div className="mt-1.5">{children}</div> : null}
    </Card>
  );
}

/** Daily net sales: one series, columns from a single baseline, hover for the exact day. */
function DailyChart({ data, currency }: { data: Dashboard["series"]; currency: DisplayCurrency }) {
  const [hover, setHover] = React.useState<number | null>(null);
  const W = 720;
  const H = 220;
  const pad = { top: 16, bottom: 28, left: 8, right: 64 };
  const max = Math.max(1, ...data.map((d) => toNum(d.net_sales)));
  const min = Math.min(0, ...data.map((d) => toNum(d.net_sales)));
  const plotW = W - pad.left - pad.right;
  const plotH = H - pad.top - pad.bottom;
  const band = plotW / data.length;
  const barW = Math.min(24, Math.max(2, band - 2));
  const y = (v: number) => pad.top + ((max - v) / (max - min)) * plotH;
  const ticks = [0, 0.5, 1].map((t) => min + (max - min) * t);
  const step = Math.max(1, Math.ceil(data.length / 8));
  const h = hover !== null ? data[hover] : null;
  return (
    <div className="relative">
      <svg viewBox={`0 0 ${W} ${H}`} className="w-full" role="img" aria-label="نمودار فروش خالص روزانه">
        {ticks.map((t) => (
          <g key={t}>
            <line x1={pad.left} x2={W - pad.right} y1={y(t)} y2={y(t)} stroke="var(--line)" strokeWidth={1} />
            <text x={W - pad.right + 6} y={y(t) + 4} fontSize={11} fill="var(--ink-faint, currentColor)" className="fill-ink-faint">
              {compact(String(Math.round(t)), currency)}
            </text>
          </g>
        ))}
        {data.map((d, i) => {
          // Right-to-left: the first day sits on the right.
          const cx = W - pad.right - band * (i + 0.5);
          const v = toNum(d.net_sales);
          const top = y(Math.max(v, 0));
          const bottom = y(Math.min(v, 0));
          const hgt = Math.max(bottom - top, v === 0 ? 0 : 1);
          const r = Math.min(4, hgt, barW / 2);
          const x = cx - barW / 2;
          const path =
            v >= 0
              ? `M${x},${bottom} V${top + r} Q${x},${top} ${x + r},${top} H${x + barW - r} Q${x + barW},${top} ${x + barW},${top + r} V${bottom} Z`
              : `M${x},${top} V${bottom - r} Q${x},${bottom} ${x + r},${bottom} H${x + barW - r} Q${x + barW},${bottom} ${x + barW},${bottom - r} V${top} Z`;
          return (
            <g key={d.date} onMouseEnter={() => setHover(i)} onMouseLeave={() => setHover(null)}>
              <rect x={cx - band / 2} y={pad.top} width={band} height={plotH} fill="transparent" />
              {hgt > 0 ? <path d={path} className={cn("fill-brand-500 transition-opacity", hover !== null && hover !== i && "opacity-40")} /> : null}
              {i % step === 0 ? (
                <text x={cx} y={H - 8} fontSize={11} textAnchor="middle" className="fill-ink-faint">
                  {isoToJalaliFa(d.date).slice(5)}
                </text>
              ) : null}
            </g>
          );
        })}
        <line x1={pad.left} x2={W - pad.right} y1={y(0)} y2={y(0)} stroke="var(--line)" strokeWidth={1} />
      </svg>
      {h ? (
        <div className="glass-strong pointer-events-none absolute top-2 left-2 rounded-xl px-3 py-2 text-xs" role="status">
          <div className="font-bold text-ink">{isoToJalaliFa(h.date)}</div>
          <div className="tabular text-ink-soft">فروش خالص: {formatMoney(h.net_sales, currency)}</div>
          <div className="tabular text-ink-soft">سود ناخالص: {formatMoney(h.gross_profit, currency)}</div>
          <div className="tabular text-ink-soft">فاکتور: {toFaDigits(h.invoices)}</div>
        </div>
      ) : null}
    </div>
  );
}

/** Labelled horizontal bars (one hue; each bar is named, so no legend is needed). */
function Bars({ rows, currency }: { rows: { label: string; value: string; hint?: string }[]; currency: DisplayCurrency }) {
  const max = Math.max(1, ...rows.map((r) => Math.abs(toNum(r.value))));
  return (
    <ul className="flex flex-col gap-3">
      {rows.map((r) => (
        <li key={r.label} className="text-sm" title={`${r.label}: ${formatMoney(r.value, currency)}`}>
          <div className="mb-1 flex justify-between gap-3">
            <span className="truncate text-ink">{r.label}</span>
            <span className="tabular shrink-0 text-ink-soft">
              {formatMoney(r.value, currency)}
              {r.hint ? <span className="text-ink-faint"> · {r.hint}</span> : null}
            </span>
          </div>
          <div className="h-2.5 rounded-full bg-brand-500/10">
            <div className="h-2.5 rounded-full bg-brand-500" style={{ width: `${Math.max(2, (Math.abs(toNum(r.value)) / max) * 100)}%` }} />
          </div>
        </li>
      ))}
    </ul>
  );
}

export function ManagementDashboard() {
  const currency = useCurrency();
  const [preset, setPreset] = React.useState(() => localStorage.getItem("nc.dash.range") ?? "today");
  const days = PRESETS.find((p) => p[0] === preset)?.[2] ?? 1;
  const to = todayIso();
  const from = shiftIso(to, -(days - 1));
  const dash = useQuery({
    queryKey: ["reports", "dashboard", from, to],
    queryFn: () => api.get<Dashboard>(`/reports/dashboard?date_from=${from}&date_to=${to}`),
    refetchInterval: 60_000,
  });
  const d = dash.data;
  const prevLabel = days === 1 ? "دیروز" : "دوره قبل";
  const money = (v: string) => formatMoney(v, currency);
  return (
    <section className="flex flex-col gap-4" aria-label="داشبورد مدیریتی">
      {d?.expiry && (d.expiry.expired || d.expiry.urgent) ? <ExpiryBanner e={d.expiry} /> : null}
      <div className="flex flex-wrap items-center gap-3">
        <h2 className="text-lg font-bold text-ink">وضعیت فروشگاه</h2>
        <Select
          className="w-40"
          aria-label="بازه داشبورد"
          value={preset}
          onChange={(e) => {
            setPreset(e.target.value);
            try {
              localStorage.setItem("nc.dash.range", e.target.value);
            } catch {
              /* preference only */
            }
          }}
        >
          {PRESETS.map(([k, l]) => <option key={k} value={k}>{l}</option>)}
        </Select>
        <span className="text-xs text-ink-faint">فقط اسناد قطعی · {isoToJalaliFa(from)} تا {isoToJalaliFa(to)}</span>
        <div className="flex-1" />
        <Link to="/reports" className="text-sm text-brand-600 hover:underline dark:text-brand-300">همه گزارش‌ها</Link>
      </div>
      {dash.isError ? <ErrorBox error={dash.error} /> : null}
      <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-4">
        <Kpi label="فروش خالص (بدون مالیات)" value={d ? money(d.current.net_sales) : <Skeleton className="h-8 w-32" />}>
          {d ? <Delta current={d.current.net_sales} previous={d.previous.net_sales} label={prevLabel} /> : null}
        </Kpi>
        <Kpi label="سود ناخالص" value={d ? money(d.current.gross_profit) : <Skeleton className="h-8 w-28" />}>
          {d?.current.margin ? <span className="text-xs text-ink-faint">حاشیه سود {toFaDigits(d.current.margin)}٪</span> : null}
        </Kpi>
        <Kpi label="تعداد فاکتور" value={d ? toFaDigits(d.current.invoices) : <Skeleton className="h-8 w-16" />}>
          {d?.current.average_basket ? <span className="text-xs text-ink-faint">میانگین سبد {money(d.current.average_basket)}</span> : null}
        </Kpi>
        <Kpi label="برگشت از فروش" value={d ? toFaDigits(d.current.returns) : <Skeleton className="h-8 w-12" />}>
          {d ? <span className="text-xs text-ink-faint">کسری صندوق: {money(d.cash_shortage)}</span> : null}
        </Kpi>
      </div>
      <div className="grid gap-4 xl:grid-cols-3">
        <Card className="xl:col-span-2">
          <CardHeader icon={<BarChart3 className="size-5" />} title="فروش خالص روزانه" description="روی هر ستون بروید تا جزئیات آن روز را ببینید" />
          <CardBody>
            {!d ? <Skeleton className="h-52" /> : d.series.length ? <DailyChart data={d.series} currency={currency} /> : <p className="text-sm text-ink-faint">بازه بیش از ۹۲ روز؛ از گزارش فروش استفاده کنید.</p>}
          </CardBody>
        </Card>
        <Card>
          <CardHeader title="روش‌های دریافت" description="خالص پس از استرداد" />
          <CardBody>
            {d ? (
              Object.keys(d.payments).length ? (
                <Bars currency={currency} rows={Object.entries(d.payments).map(([k, v]) => ({ label: METHOD[k] ?? k, value: v }))} />
              ) : (
                <p className="text-sm text-ink-faint">فروشی در این بازه ثبت نشده است.</p>
              )
            ) : (
              <Skeleton className="h-32" />
            )}
          </CardBody>
        </Card>
      </div>
      <div className="grid gap-4 xl:grid-cols-3">
        <Card className="xl:col-span-2">
          <CardHeader title="پرفروش‌ترین کالاها" description="بر اساس فروش خالص" actions={<Link className="text-sm text-brand-600 hover:underline dark:text-brand-300" to="/reports/sales?group_by=item">گزارش کامل</Link>} />
          <CardBody>
            {d ? (
              d.top_items.length ? (
                <Bars currency={currency} rows={d.top_items.map((t) => ({ label: t.name, value: t.net_sales, hint: `${toFaDigits(trimQty(t.qty))} واحد` }))} />
              ) : (
                <p className="text-sm text-ink-faint">فروشی در این بازه ثبت نشده است.</p>
              )
            ) : (
              <Skeleton className="h-40" />
            )}
          </CardBody>
        </Card>
        <Card>
          <CardHeader title="مانده‌ها و هشدارها" description="لحظه‌ای، مستقل از بازه" />
          <CardBody className="flex flex-col gap-3 text-sm">
            {d?.inventory_value !== null && d?.inventory_value !== undefined ? (
              <Row label="ارزش موجودی کالا" value={money(d.inventory_value)} />
            ) : null}
            {d?.below_min_items ? (
              <Row label="کالای زیر حداقل موجودی" value={<Badge tone="warning">{toFaDigits(d.below_min_items)} قلم</Badge>} />
            ) : null}
            {d?.expiry && (d.expiry.expired || d.expiry.urgent || d.expiry.soon) ? (
              <Row
                label={<Link className="hover:underline" to="/reports/near-expiry">دسته‌های نزدیک انقضا</Link>}
                value={
                  <span className="flex flex-wrap justify-end gap-1">
                    {d.expiry.expired ? (
                      <Badge tone="danger" icon={false}><AlertTriangle className="size-3.5" /> {toFaDigits(d.expiry.expired)} منقضی</Badge>
                    ) : null}
                    {d.expiry.urgent ? (
                      <Badge tone="danger" icon={false}><CalendarClock className="size-3.5" /> {toFaDigits(d.expiry.urgent)} تا {toFaDigits(d.expiry.urgent_days)} روز</Badge>
                    ) : null}
                    {d.expiry.soon ? (
                      <Badge tone="warning" icon={false}><CalendarClock className="size-3.5" /> {toFaDigits(d.expiry.soon)} تا {toFaDigits(d.expiry.warn_days)} روز</Badge>
                    ) : null}
                  </span>
                }
              />
            ) : null}
            {d?.receivables !== null && d?.receivables !== undefined ? (
              <Row label={<Link className="hover:underline" to="/reports/debtors">طلب از مشتریان</Link>} value={money(d.receivables)} />
            ) : null}
            {d?.payables !== null && d?.payables !== undefined ? (
              <Row label={<Link className="hover:underline" to="/reports/creditors">بدهی به تأمین‌کنندگان</Link>} value={money(d.payables)} />
            ) : null}
            {d?.unknown_card_transactions ? (
              <Row
                label={<Link className="hover:underline" to="/sales/card-transactions">تراکنش نامشخص کارت‌خوان</Link>}
                value={
                  <Badge tone="danger">
                    <AlertTriangle className="size-3.5" /> {toFaDigits(d.unknown_card_transactions)}
                  </Badge>
                }
              />
            ) : null}
            {!d ? <Skeleton className="h-24" /> : null}
          </CardBody>
        </Card>
      </div>
    </section>
  );
}

function Row({ label, value }: { label: React.ReactNode; value: React.ReactNode }) {
  return (
    <div className="flex items-center justify-between gap-3">
      <span className="text-ink-soft">{label}</span>
      <span className="tabular font-semibold text-ink">{value}</span>
    </div>
  );
}

/** Shown above everything while some stock has expired or expires within the urgent days. */
function ExpiryBanner({ e }: { e: NonNullable<Dashboard["expiry"]> }) {
  const parts = [
    e.expired ? `${toFaDigits(e.expired)} دسته منقضی شده` : null,
    e.urgent ? `${toFaDigits(e.urgent)} دسته تا ${toFaDigits(e.urgent_days)} روز دیگر منقضی می‌شود` : null,
  ].filter(Boolean);
  return (
    <div role="alert" className="flex flex-wrap items-center gap-3 rounded-2xl bg-danger/10 px-4 py-3 text-sm ring-1 ring-danger/30">
      <AlertTriangle className="size-5 text-danger" />
      <span className="flex-1 font-semibold text-ink">هشدار انقضا: {parts.join("، ")}.</span>
      <Link className="font-semibold text-brand-600 hover:underline dark:text-brand-300" to="/reports/near-expiry">
        فهرست دسته‌ها
      </Link>
    </div>
  );
}
