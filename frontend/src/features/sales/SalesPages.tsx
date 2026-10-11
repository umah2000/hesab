import { keepPreviousData, useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Plus, Printer, ReceiptText, Undo2 } from "lucide-react";
import * as React from "react";
import { Link, NavLink, Outlet, useNavigate, useParams } from "react-router";
import { toast } from "sonner";
import { PageTitle } from "@/components/layout/AppShell";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { Dialog, DialogContent, DialogFooter } from "@/components/ui/dialog";
import { Badge, EmptyState, ErrorBox, Spinner } from "@/components/ui/feedback";
import { Checkbox, Field, Input, Select } from "@/components/ui/form-controls";
import { Pagination, Table, Td, Th, Tr } from "@/components/ui/table";
import { useCurrency } from "@/features/accounting/api";
import { JalaliDateInput, MoneyInput } from "@/features/accounting/inputs";
import { useCan } from "@/features/auth/auth";
import { trimQty, useGroups } from "@/features/inventory/api";
import { ItemSearch } from "@/features/inventory/ItemSearch";
import { ApiError, api, newIdempotencyKey, type Page } from "@/lib/api";
import { formatDateTime, formatMoney, toEnDigits, toFaDigits } from "@/lib/format";
import { isoToJalaliFa, todayIso } from "@/lib/jalali";
import { compareRials, inputToRials, rialsToInput, sumRials } from "@/lib/money";
import { qtyUnits, subQty } from "@/lib/qty";
import { cn } from "@/lib/utils";
import {
  type DailyReport,
  type Invoice,
  type InvoiceSummary,
  METHOD_LABEL,
  type Method,
  type Promotion,
  type Shift,
  type ShiftReport,
  storedRegister,
  type TerminalTx,
  TX_LABEL,
} from "./api";
import { printReceipt, Receipt } from "./Receipt";

const onError = (e: unknown) => toast.error(e instanceof ApiError ? e.message : "خطا");

const TABS = [
  { to: "/sales/invoices", label: "فاکتورها", perm: ["sales.report.view", "sales.return.create"] },
  { to: "/sales/shifts", label: "شیفت‌ها", perm: ["sales.report.view"] },
  { to: "/sales/daily", label: "گزارش روزانه", perm: ["sales.report.view"] },
  { to: "/sales/promotions", label: "پروموشن‌ها", perm: ["inventory.price.manage", "sales.report.view"] },
  { to: "/sales/card-transactions", label: "تراکنش‌های نامشخص کارت", perm: ["payments.reconcile"] },
];

export function SalesLayout() {
  const can = useCan();
  return (
    <>
      <PageTitle title="فروش" subtitle="فاکتورها، برگشت از فروش، شیفت‌ها و گزارش فروش" actions={<Button asChild><Link to="/pos">ورود به صندوق</Link></Button>} />
      <nav className="no-print glass mb-4 flex gap-1 overflow-x-auto rounded-2xl p-1.5" aria-label="بخش‌های فروش">
        {TABS.filter((t) => can(t.perm)).map((t) => (
          <NavLink
            key={t.to}
            to={t.to}
            className={({ isActive }) =>
              cn(
                "rounded-xl px-4 py-2 text-sm font-medium whitespace-nowrap transition",
                isActive ? "bg-white text-brand-600 shadow-sm dark:bg-white/15 dark:text-white" : "text-ink-soft hover:text-ink",
              )
            }
          >
            {t.label}
          </NavLink>
        ))}
      </nav>
      <Outlet />
    </>
  );
}

// --- invoices -------------------------------------------------------------------

export function InvoicesPage() {
  const currency = useCurrency();
  const nav = useNavigate();
  const [page, setPage] = React.useState(1);
  const [kind, setKind] = React.useState("");
  const [number, setNumber] = React.useState("");
  const [from, setFrom] = React.useState<string | null>(todayIso());
  const params = new URLSearchParams({ page: String(page), page_size: "50", status: "final" });
  if (kind) params.set("kind", kind);
  if (number.trim()) params.set("number", toEnDigits(number.trim()));
  if (from && !number.trim()) params.set("date_from", from);
  const list = useQuery({
    queryKey: ["sales", "invoices", params.toString()],
    queryFn: () => api.get<Page<InvoiceSummary>>(`/sales/invoices?${params}`),
    placeholderData: keepPreviousData,
  });
  return (
    <Card>
      <div className="flex flex-wrap items-end gap-3 p-4">
        <Field label="از تاریخ">
          <JalaliDateInput value={from} onChange={(v) => { setFrom(v); setPage(1); }} />
        </Field>
        <Field label="نوع">
          <Select value={kind} onChange={(e) => { setKind(e.target.value); setPage(1); }}>
            <option value="">فروش و برگشت</option>
            <option value="sale">فروش</option>
            <option value="return">برگشت</option>
          </Select>
        </Field>
        <Field label="شماره فاکتور">
          <Input className="w-32" dir="ltr" value={number} onChange={(e) => { setNumber(e.target.value); setPage(1); }} />
        </Field>
      </div>
      <div className="surface mx-4 mb-4 overflow-hidden rounded-2xl">
        {list.isLoading ? (
          <Spinner />
        ) : list.isError ? (
          <ErrorBox error={list.error} />
        ) : !list.data?.items.length ? (
          <EmptyState icon={ReceiptText} title="فاکتوری یافت نشد" />
        ) : (
          <>
            <Table>
              <thead>
                <tr>
                  <Th className="w-24">شماره</Th>
                  <Th className="w-28">نوع</Th>
                  <Th>زمان</Th>
                  <Th>صندوق / صندوق‌دار</Th>
                  <Th>مشتری</Th>
                  <Th className="w-20">اقلام</Th>
                  <Th className="w-40">مبلغ</Th>
                </tr>
              </thead>
              <tbody>
                {list.data.items.map((i) => (
                  <Tr key={i.id} className="cursor-pointer" onClick={() => nav(`/sales/invoices/${i.id}`)}>
                    <Td className="tabular font-bold">{toFaDigits(i.number ?? 0)}</Td>
                    <Td>{i.kind === "sale" ? <Badge tone="success" icon={false}>فروش</Badge> : <Badge tone="warning">برگشت</Badge>}</Td>
                    <Td className="text-ink-soft">{formatDateTime(i.created_at)}</Td>
                    <Td className="text-ink-soft">{i.register_name} · {i.cashier_name}</Td>
                    <Td>{i.customer_name ?? "—"}</Td>
                    <Td className="tabular">{toFaDigits(i.line_count)}</Td>
                    <Td className="tabular font-semibold">{formatMoney(i.grand_total, currency)}</Td>
                  </Tr>
                ))}
              </tbody>
            </Table>
            <Pagination page={page} pageSize={50} total={list.data.total} onPage={setPage} />
          </>
        )}
      </div>
    </Card>
  );
}

export function InvoiceDetailPage() {
  const { id } = useParams();
  const can = useCan();
  const currency = useCurrency();
  const [returning, setReturning] = React.useState(false);
  const inv = useQuery({ queryKey: ["sales", "invoice", id], queryFn: () => api.get<Invoice>(`/sales/invoices/${id}`) });
  const org = useQuery({ queryKey: ["organization"], queryFn: () => api.get<{ name: string; receipt_header: string | null; receipt_footer: string | null }>("/organization/settings") });
  if (inv.isLoading) return <Spinner />;
  if (inv.isError || !inv.data) return <ErrorBox error={inv.error} />;
  const d = inv.data;
  const money = (v: string) => formatMoney(v, currency);
  const returnable = d.kind === "sale" && d.lines.some((l) => compareRials(l.returned_qty, l.qty) < 0);
  return (
    <div className="grid gap-4 xl:grid-cols-[1fr_auto]">
      <Card className="p-4">
        <div className="mb-4 flex flex-wrap items-center gap-3">
          <h2 className="text-lg font-bold text-ink">
            {d.kind === "sale" ? "فاکتور فروش" : "برگشت از فروش"} شماره {toFaDigits(d.number ?? 0)}
          </h2>
          {d.original_invoice_id ? (
            <Link className="text-sm text-brand-600 hover:underline" to={`/sales/invoices/${d.original_invoice_id}`}>
              فاکتور اصلی {toFaDigits(d.original_number ?? 0)}
            </Link>
          ) : null}
          {d.voucher_id ? (
            <Link className="text-sm text-brand-600 hover:underline" to={`/accounting/vouchers/${d.voucher_id}`}>
              سند حسابداری
            </Link>
          ) : null}
          <div className="flex-1" />
          <Button variant="outline" onClick={printReceipt}>
            <Printer /> چاپ مجدد فیش
          </Button>
          {returnable && can("sales.return.create") ? (
            <Button onClick={() => setReturning(true)}>
              <Undo2 /> برگشت از فروش
            </Button>
          ) : null}
        </div>
        <div className="mb-3 text-sm text-ink-soft">
          {formatDateTime(d.finalized_at ?? d.created_at)} · {d.register_name} · {d.cashier_name}
          {d.customer_name ? ` · مشتری: ${d.customer_name}` : ""}
          {d.note ? ` · ${d.note}` : ""}
        </div>
        <div className="surface overflow-hidden rounded-2xl">
          <Table>
            <thead>
              <tr>
                <Th>کالا</Th>
                <Th className="w-28">مقدار</Th>
                <Th className="w-32">فی</Th>
                <Th className="w-28">تخفیف</Th>
                <Th className="w-28">مالیات</Th>
                <Th className="w-36">جمع</Th>
                {d.kind === "sale" ? <Th className="w-24">برگشتی</Th> : null}
              </tr>
            </thead>
            <tbody>
              {d.lines.map((l) => (
                <Tr key={l.id}>
                  <Td>
                    {l.item_name} <span className="tabular text-xs text-ink-faint" dir="ltr">{l.item_code}</span>
                  </Td>
                  <Td className="tabular">{toFaDigits(trimQty(l.qty))} {l.unit_name}</Td>
                  <Td className="tabular">{money(l.unit_price)}</Td>
                  <Td className="tabular">{money(sumRials([l.promotion_discount, l.manual_discount]))}</Td>
                  <Td className="tabular">{l.vat_exempt ? "معاف" : money(l.tax)}</Td>
                  <Td className="tabular font-semibold">{money(l.line_total)}</Td>
                  {d.kind === "sale" ? <Td className="tabular">{Number(l.returned_qty) ? toFaDigits(trimQty(l.returned_qty)) : "—"}</Td> : null}
                </Tr>
              ))}
            </tbody>
          </Table>
        </div>
        <div className="mt-4 flex flex-wrap gap-6 text-sm">
          <span>جمع: <b className="tabular">{money(d.subtotal)}</b></span>
          <span>تخفیف: <b className="tabular">{money(d.discount_total)}</b></span>
          <span>مالیات: <b className="tabular">{money(d.tax_total)}</b></span>
          <span>مبلغ نهایی: <b className="tabular text-base">{money(d.grand_total)}</b></span>
          {d.payments.map((p, i) => (
            <Badge key={i} tone="neutral" icon={false}>
              {METHOD_LABEL[p.method]} {money(p.amount)}
              {p.card_reference ? ` · پیگیری ${toFaDigits(p.card_reference)}` : ""}
            </Badge>
          ))}
        </div>
      </Card>
      <Card className="hidden p-3 xl:block">
        <div className="print-area">
          <Receipt invoice={d} currency={currency} organization={org.data?.name ?? ""} header={org.data?.receipt_header} footer={org.data?.receipt_footer} reprint />
        </div>
      </Card>
      {returning ? <ReturnDialog invoice={d} onClose={() => setReturning(false)} /> : null}
    </div>
  );
}

function ReturnDialog({ invoice, onClose }: { invoice: Invoice; onClose: () => void }) {
  const qc = useQueryClient();
  const nav = useNavigate();
  const currency = useCurrency();
  const register = storedRegister();
  const [qty, setQty] = React.useState<Record<string, string>>({});
  const [reason, setReason] = React.useState("");
  const [method, setMethod] = React.useState<Method>("cash");
  const [cardRef, setCardRef] = React.useState("");
  const keyRef = React.useRef(newIdempotencyKey());
  const lines = invoice.lines
    .map((l) => ({ l, max: subQty(l.qty, l.returned_qty) }))
    .filter((x) => qtyUnits(x.max) > 0n);
  // Preview only: the server computes the exact refund (proportional, last return takes the rest).
  const preview = lines.reduce((acc, { l }) => {
    const v = toEnDigits(qty[l.id] ?? "").trim();
    if (!/^\d+(\.\d{1,3})?$/.test(v) || qtyUnits(v) <= 0n) return acc;
    return acc + (BigInt(l.line_total.split(".")[0]) * qtyUnits(v)) / qtyUnits(l.qty);
  }, 0n);
  const create = useMutation({
    mutationFn: async () => {
      if (!register) throw new ApiError(0, "no_register", "این رایانه به صندوقی وصل نیست؛ برگشت را از صفحه صندوق ثبت کنید");
      const body = {
        cash_register_id: register,
        reason: reason.trim(),
        lines: lines.filter(({ l }) => /^\d+(\.\d{1,3})?$/.test(toEnDigits(qty[l.id] ?? "").trim()) && qtyUnits(toEnDigits(qty[l.id])) > 0n).map(({ l }) => ({ original_line_id: l.id, qty: toEnDigits(qty[l.id]) })),
        // One refund method: the server refunds exactly the computed amount.
        refunds: [{ method, card_reference: method === "card" ? toEnDigits(cardRef) : null }],
      };
      return api.post<Invoice>(`/sales/invoices/${invoice.id}/returns`, body, { idempotencyKey: keyRef.current });
    },
    onSuccess: (r) => {
      toast.success(`برگشت شماره ${toFaDigits(r.number ?? 0)} ثبت شد`);
      qc.invalidateQueries({ queryKey: ["sales"] });
      onClose();
      nav(`/sales/invoices/${r.id}`);
    },
    onError: (e) => {
      keyRef.current = newIdempotencyKey();
      onError(e);
    },
  });
  return (
    <Dialog open onOpenChange={(o) => !o && onClose()}>
      <DialogContent title={`برگشت از فاکتور ${toFaDigits(invoice.number ?? 0)}`} description="کالا با همان بهای تمام‌شده فروش به انبار برمی‌گردد. شیفت باز روی این صندوق لازم است." className="max-w-2xl">
        <div className="flex flex-col gap-3">
          {lines.map(({ l, max }) => (
            <div key={l.id} className="surface flex items-center gap-3 rounded-xl px-3 py-2 text-sm">
              <div className="flex-1">
                <div className="font-medium">{l.item_name}</div>
                <div className="text-xs text-ink-faint">قابل برگشت: {toFaDigits(trimQty(max))} {l.unit_name} · {formatMoney(l.line_total, currency)}</div>
              </div>
              <Input className="w-24 text-center" dir="ltr" inputMode="decimal" placeholder="0" aria-label={`مقدار برگشتی ${l.item_name}`} value={qty[l.id] ?? ""} onChange={(e) => setQty({ ...qty, [l.id]: e.target.value })} />
            </div>
          ))}
          <div className="grid grid-cols-2 gap-3">
            <Field label="روش استرداد">
              <Select value={method} onChange={(e) => setMethod(e.target.value as Method)}>
                <option value="cash">نقد</option>
                <option value="card">کارت (شماره پیگیری)</option>
                {invoice.customer_id ? <option value="credit">کاهش طلب مشتری</option> : null}
              </Select>
            </Field>
            {method === "card" ? (
              <Field label="شماره پیگیری استرداد">
                <Input dir="ltr" value={cardRef} onChange={(e) => setCardRef(e.target.value)} />
              </Field>
            ) : null}
          </div>
          <Field label="علت برگشت">
            <Input aria-label="علت برگشت" value={reason} onChange={(e) => setReason(e.target.value)} />
          </Field>
          <p className="text-sm">مبلغ استرداد (تقریبی): <b className="tabular">{formatMoney(String(preview), currency)}</b></p>
        </div>
        <DialogFooter>
          <Button loading={create.isPending} disabled={preview <= 0n || reason.trim().length < 2} onClick={() => create.mutate()}>
            <Undo2 /> ثبت برگشت
          </Button>
          <Button variant="ghost" onClick={onClose}>انصراف</Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}

// --- shifts -------------------------------------------------------------------------

export function ShiftsPage() {
  const currency = useCurrency();
  const [page, setPage] = React.useState(1);
  const [open, setOpen] = React.useState<string | null>(null);
  const list = useQuery({
    queryKey: ["sales", "shifts", page],
    queryFn: () => api.get<Page<Shift>>(`/sales/shifts?page=${page}`),
    placeholderData: keepPreviousData,
  });
  const report = useQuery({
    queryKey: ["sales", "shift-report", open],
    queryFn: () => api.get<ShiftReport>(`/sales/shifts/${open}/report`),
    enabled: !!open,
  });
  const money = (v: string | null) => (v === null ? "—" : formatMoney(v, currency));
  return (
    <div className="grid gap-4 xl:grid-cols-[1fr_24rem]">
      <Card className="p-2">
        <div className="surface overflow-hidden rounded-2xl">
          {list.isLoading ? (
            <Spinner />
          ) : (
            <>
              <Table>
                <thead>
                  <tr>
                    <Th>صندوق</Th>
                    <Th>صندوق‌دار</Th>
                    <Th>شروع</Th>
                    <Th>پایان</Th>
                    <Th>اختلاف</Th>
                  </tr>
                </thead>
                <tbody>
                  {list.data?.items.map((s) => (
                    <Tr key={s.id} className={cn("cursor-pointer", open === s.id && "bg-brand-500/5")} onClick={() => setOpen(s.id)}>
                      <Td>{s.register_name}</Td>
                      <Td>{s.user_name}</Td>
                      <Td className="text-ink-soft">{formatDateTime(s.opened_at)}</Td>
                      <Td className="text-ink-soft">{s.closed_at ? formatDateTime(s.closed_at) : <Badge tone="info">باز</Badge>}</Td>
                      <Td className={cn("tabular", s.difference && compareRials(s.difference, "0") !== 0 && "text-danger")}>
                        {s.difference === null ? "—" : compareRials(s.difference, "0") === 0 ? "تراز" : money(s.difference)}
                      </Td>
                    </Tr>
                  ))}
                </tbody>
              </Table>
              <Pagination page={page} pageSize={30} total={list.data?.total ?? 0} onPage={setPage} />
            </>
          )}
        </div>
      </Card>
      <Card className="p-4">
        {!open ? (
          <EmptyState icon={ReceiptText} title="یک شیفت را انتخاب کنید" />
        ) : report.isLoading || !report.data ? (
          <Spinner />
        ) : (
          <div className="print-area flex flex-col gap-1.5 text-sm">
            <h3 className="mb-2 font-bold">گزارش شیفت {report.data.shift.register_name} — {report.data.shift.user_name}</h3>
            <KV k="تعداد فروش / برگشت" v={`${toFaDigits(report.data.sale_count)} / ${toFaDigits(report.data.return_count)}`} />
            <KV k="جمع فروش" v={money(report.data.sales_total)} />
            <KV k="جمع برگشت" v={money(report.data.returns_total)} />
            <KV k="تخفیف" v={money(report.data.discount_total)} />
            <KV k="مالیات" v={money(report.data.tax_total)} />
            {report.data.by_method.map((m) => (
              <KV key={m.method} k={`${METHOD_LABEL[m.method]} (فروش / استرداد)`} v={`${money(m.sales)} / ${money(m.refunds)}`} />
            ))}
            <KV k="موجودی اول شیفت" v={money(report.data.shift.opening_cash)} />
            <KV k="نقد مورد انتظار" v={money(report.data.expected_cash)} />
            <KV k="نقد شمارش‌شده" v={money(report.data.shift.counted_cash)} />
            <KV k="اختلاف" v={money(report.data.shift.difference)} />
            <Button variant="outline" className="no-print mt-3" onClick={() => window.print()}>
              <Printer /> چاپ
            </Button>
          </div>
        )}
      </Card>
    </div>
  );
}

function KV({ k, v }: { k: string; v: string }) {
  return (
    <div className="flex justify-between border-b border-[var(--line)] py-1">
      <span className="text-ink-soft">{k}</span>
      <span className="tabular font-semibold">{v}</span>
    </div>
  );
}

// --- daily report -------------------------------------------------------------------

export function DailyReportPage() {
  const currency = useCurrency();
  const [day, setDay] = React.useState<string | null>(todayIso());
  const rep = useQuery({
    queryKey: ["sales", "daily", day],
    queryFn: () => api.get<DailyReport>(`/sales/reports/daily?date=${day}`),
    enabled: !!day,
  });
  const money = (v: string) => formatMoney(v, currency);
  return (
    <div className="flex flex-col gap-4">
      <Card className="flex items-end gap-3 p-4">
        <Field label="تاریخ">
          <JalaliDateInput value={day} onChange={setDay} />
        </Field>
        {rep.data ? <span className="pb-2 text-sm text-ink-faint">{isoToJalaliFa(rep.data.date)}</span> : null}
      </Card>
      {rep.isLoading || !rep.data ? (
        <Spinner />
      ) : (
        <>
          <div className="grid grid-cols-2 gap-4 lg:grid-cols-4">
            <Stat label="فروش خالص" value={money(rep.data.net_total)} hint={`${toFaDigits(rep.data.sale_count)} فاکتور`} />
            <Stat label="برگشت از فروش" value={money(rep.data.returns_total)} hint={`${toFaDigits(rep.data.return_count)} فاکتور`} />
            <Stat label="مالیات بر ارزش افزوده" value={money(rep.data.tax_total)} />
            <Stat label="سود ناخالص" value={money(rep.data.gross_profit)} hint={`بهای تمام‌شده ${money(rep.data.cost_total)}`} />
          </div>
          <div className="grid gap-4 lg:grid-cols-2">
            <Card className="p-4">
              <h3 className="mb-2 font-bold">به تفکیک روش دریافت</h3>
              {rep.data.by_method.map((m) => (
                <KV key={m.method} k={METHOD_LABEL[m.method]} v={`${money(m.sales)}${Number(m.refunds) ? ` (استرداد ${money(m.refunds)})` : ""}`} />
              ))}
            </Card>
            <Card className="p-4">
              <h3 className="mb-2 font-bold">به تفکیک صندوق</h3>
              {rep.data.by_register.length ? (
                rep.data.by_register.map((r) => <KV key={r.cash_register_id} k={`${r.register_name} (${toFaDigits(r.sale_count)} فاکتور)`} v={money(r.sales_total)} />)
              ) : (
                <p className="text-sm text-ink-faint">فروشی ثبت نشده است.</p>
              )}
            </Card>
          </div>
        </>
      )}
    </div>
  );
}

function Stat({ label, value, hint }: { label: string; value: string; hint?: string }) {
  return (
    <Card className="p-4">
      <div className="text-xs text-ink-faint">{label}</div>
      <div className="tabular mt-1 text-xl font-black text-ink">{value}</div>
      {hint ? <div className="mt-1 text-xs text-ink-soft">{hint}</div> : null}
    </Card>
  );
}

// --- promotions ---------------------------------------------------------------------

export function PromotionsPage() {
  const can = useCan();
  const currency = useCurrency();
  const [editing, setEditing] = React.useState<Promotion | "new" | null>(null);
  const list = useQuery({ queryKey: ["sales", "promotions"], queryFn: () => api.get<Promotion[]>("/sales/promotions") });
  const today = todayIso();
  return (
    <Card className="p-2">
      <div className="flex items-center justify-between p-3">
        <p className="text-sm text-ink-soft">در هر ردیف فاکتور، بیشترین تخفیفِ پروموشن‌های فعال اعمال می‌شود.</p>
        {can("inventory.price.manage") ? (
          <Button onClick={() => setEditing("new")}>
            <Plus /> پروموشن جدید
          </Button>
        ) : null}
      </div>
      <div className="surface overflow-hidden rounded-2xl">
        {list.isLoading ? (
          <Spinner />
        ) : !list.data?.length ? (
          <EmptyState icon={ReceiptText} title="پروموشنی تعریف نشده" />
        ) : (
          <Table>
            <thead>
              <tr>
                <Th>عنوان</Th>
                <Th>کالا / گروه</Th>
                <Th>تخفیف</Th>
                <Th>بازه</Th>
                <Th>وضعیت</Th>
              </tr>
            </thead>
            <tbody>
              {list.data.map((p) => {
                const live = p.is_active && p.starts_on <= today && p.ends_on >= today;
                return (
                  <Tr key={p.id} className={can("inventory.price.manage") ? "cursor-pointer" : ""} onClick={() => can("inventory.price.manage") && setEditing(p)}>
                    <Td className="font-medium">{p.name}</Td>
                    <Td>{p.scope === "group" ? `گروه ${p.target_name}` : p.target_name}</Td>
                    <Td className="tabular">{p.kind === "percent" ? `${toFaDigits(trimQty(p.value))}٪` : `${formatMoney(p.value, currency)} برای هر واحد`}</Td>
                    <Td className="tabular text-ink-soft">{isoToJalaliFa(p.starts_on)} تا {isoToJalaliFa(p.ends_on)}</Td>
                    <Td>{live ? <Badge tone="success">فعال</Badge> : <Badge tone="neutral">{p.is_active ? "خارج از بازه" : "غیرفعال"}</Badge>}</Td>
                  </Tr>
                );
              })}
            </tbody>
          </Table>
        )}
      </div>
      {editing ? <PromotionDialog promotion={editing === "new" ? null : editing} onClose={() => setEditing(null)} /> : null}
    </Card>
  );
}

function PromotionDialog({ promotion, onClose }: { promotion: Promotion | null; onClose: () => void }) {
  const qc = useQueryClient();
  const currency = useCurrency();
  const groups = useGroups();
  const keyRef = React.useRef(newIdempotencyKey());
  const [name, setName] = React.useState(promotion?.name ?? "");
  const [kind, setKind] = React.useState<Promotion["kind"]>(promotion?.kind ?? "percent");
  const [scope, setScope] = React.useState<Promotion["scope"]>(promotion?.scope ?? "item");
  const [item, setItem] = React.useState<{ id: string; name: string } | null>(promotion?.item_id ? { id: promotion.item_id, name: promotion.target_name } : null);
  const [group, setGroup] = React.useState(promotion?.group_id ?? "");
  const [value, setValue] = React.useState(promotion ? (promotion.kind === "percent" ? trimQty(promotion.value) : rialsToInput(promotion.value, currency)) : "");
  const [start, setStart] = React.useState<string | null>(promotion?.starts_on ?? todayIso());
  const [end, setEnd] = React.useState<string | null>(promotion?.ends_on ?? null);
  const [active, setActive] = React.useState(promotion?.is_active ?? true);
  const save = useMutation({
    mutationFn: () => {
      const v = kind === "percent" ? toEnDigits(value) : inputToRials(value, currency);
      if (!v) throw new ApiError(0, "invalid", "مقدار تخفیف نامعتبر است");
      const body = {
        name: name.trim(),
        kind,
        scope,
        item_id: scope === "item" ? item?.id ?? null : null,
        group_id: scope === "group" ? group || null : null,
        value: v,
        starts_on: start,
        ends_on: end,
        is_active: active,
      };
      return promotion
        ? api.put(`/sales/promotions/${promotion.id}`, body, promotion.row_version)
        : api.post("/sales/promotions", body, { idempotencyKey: keyRef.current });
    },
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["sales", "promotions"] });
      toast.success("پروموشن ذخیره شد");
      onClose();
    },
    onError,
  });
  return (
    <Dialog open onOpenChange={(o) => !o && onClose()}>
      <DialogContent title={promotion ? "ویرایش پروموشن" : "پروموشن جدید"} className="max-w-xl">
        <div className="grid grid-cols-2 gap-3">
          <Field label="عنوان" className="col-span-2">
            <Input value={name} onChange={(e) => setName(e.target.value)} />
          </Field>
          <Field label="روی">
            <Select value={scope} onChange={(e) => setScope(e.target.value as Promotion["scope"])}>
              <option value="item">یک کالا</option>
              <option value="group">یک گروه کالا</option>
            </Select>
          </Field>
          {scope === "item" ? (
            <Field label={item ? `کالا: ${item.name}` : "کالا"}>
              <ItemSearch onPick={(p) => setItem({ id: p.item_id, name: p.name })} placeholder="جست‌وجوی کالا" />
            </Field>
          ) : (
            <Field label="گروه">
              <Select value={group} onChange={(e) => setGroup(e.target.value)}>
                <option value="">انتخاب کنید</option>
                {groups.data?.map((g) => (
                  <option key={g.id} value={g.id}>{g.name}</option>
                ))}
              </Select>
            </Field>
          )}
          <Field label="نوع تخفیف">
            <Select value={kind} onChange={(e) => setKind(e.target.value as Promotion["kind"])}>
              <option value="percent">درصد</option>
              <option value="amount">مبلغ برای هر واحد</option>
            </Select>
          </Field>
          <Field label={kind === "percent" ? "درصد" : `مبلغ (${currency === "IRT" ? "تومان" : "ریال"})`}>
            {kind === "percent" ? <Input dir="ltr" value={value} onChange={(e) => setValue(e.target.value)} /> : <MoneyInput value={value} onChange={setValue} />}
          </Field>
          <Field label="از تاریخ">
            <JalaliDateInput value={start} onChange={setStart} />
          </Field>
          <Field label="تا تاریخ">
            <JalaliDateInput value={end} onChange={setEnd} />
          </Field>
          <label className="col-span-2 flex items-center gap-2 text-sm text-ink-soft">
            <Checkbox checked={active} onCheckedChange={(c) => setActive(c === true)} /> فعال
          </label>
        </div>
        <DialogFooter>
          <Button loading={save.isPending} disabled={name.trim().length < 2 || !value || !start || !end || (scope === "item" ? !item : !group)} onClick={() => save.mutate()}>
            ذخیره
          </Button>
          <Button variant="ghost" onClick={onClose}>انصراف</Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}

// --- unresolved card transactions ---------------------------------------------------------

export function CardTransactionsPage() {
  const qc = useQueryClient();
  const currency = useCurrency();
  const list = useQuery({ queryKey: ["payments", "unresolved"], queryFn: () => api.get<TerminalTx[]>("/payments/terminal-transactions") });
  const [resolving, setResolving] = React.useState<TerminalTx | null>(null);
  const inquire = useMutation({
    mutationFn: (t: TerminalTx) => api.post<TerminalTx>(`/payments/terminal-transactions/${t.id}/inquire`),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["payments"] }),
    onError,
  });
  return (
    <Card className="p-2">
      <p className="p-3 text-sm text-ink-soft">
        تراکنشی که پاسخ کارت‌خوان به آن نرسیده «نامشخص» است و هرگز بدون استعلام یا تطبیق با گزارش بانک دوباره دریافت نمی‌شود.
      </p>
      <div className="surface overflow-hidden rounded-2xl">
        {list.isLoading ? (
          <Spinner />
        ) : !list.data?.length ? (
          <EmptyState icon={ReceiptText} title="تراکنش نامشخصی وجود ندارد" />
        ) : (
          <Table>
            <thead>
              <tr>
                <Th>زمان</Th>
                <Th>مبلغ</Th>
                <Th>وضعیت</Th>
                <Th className="w-56" />
              </tr>
            </thead>
            <tbody>
              {list.data.map((t) => (
                <Tr key={t.id}>
                  <Td className="text-ink-soft">{formatDateTime(t.created_at)}{t.is_simulated ? " · آزمایشی" : ""}</Td>
                  <Td className="tabular">{formatMoney(t.amount, currency)}</Td>
                  <Td><Badge tone="warning">{TX_LABEL[t.status]}</Badge></Td>
                  <Td className="flex gap-2">
                    <Button size="sm" variant="outline" loading={inquire.isPending} onClick={() => inquire.mutate(t)}>استعلام</Button>
                    <Button size="sm" onClick={() => setResolving(t)}>تطبیق دستی</Button>
                  </Td>
                </Tr>
              ))}
            </tbody>
          </Table>
        )}
      </div>
      {resolving ? <ResolveDialog tx={resolving} onClose={() => setResolving(null)} /> : null}
    </Card>
  );
}

function ResolveDialog({ tx, onClose }: { tx: TerminalTx; onClose: () => void }) {
  const qc = useQueryClient();
  const [status, setStatus] = React.useState<"Approved" | "Declined">("Declined");
  const [rrn, setRrn] = React.useState("");
  const [note, setNote] = React.useState("");
  const save = useMutation({
    mutationFn: () => api.post(`/payments/terminal-transactions/${tx.id}/resolve`, { status, rrn: rrn ? toEnDigits(rrn) : null, note }, { version: tx.row_version }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["payments"] });
      toast.success("تراکنش تطبیق شد");
      onClose();
    },
    onError,
  });
  return (
    <Dialog open onOpenChange={(o) => !o && onClose()}>
      <DialogContent title="تطبیق با گزارش بانک" description="فقط بر اساس گزارش رسمی پذیرنده/بانک.">
        <div className="flex flex-col gap-3">
          <Field label="نتیجه در گزارش بانک">
            <Select value={status} onChange={(e) => setStatus(e.target.value as "Approved" | "Declined")}>
              <option value="Declined">در گزارش نیست / رد شده</option>
              <option value="Approved">موفق (مبلغ کسر شده)</option>
            </Select>
          </Field>
          {status === "Approved" ? (
            <Field label="شماره مرجع (RRN)">
              <Input dir="ltr" value={rrn} onChange={(e) => setRrn(e.target.value)} />
            </Field>
          ) : null}
          <Field label="توضیح">
            <Input value={note} onChange={(e) => setNote(e.target.value)} />
          </Field>
        </div>
        <DialogFooter>
          <Button loading={save.isPending} disabled={note.trim().length < 2} onClick={() => save.mutate()}>ثبت</Button>
          <Button variant="ghost" onClick={onClose}>انصراف</Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
