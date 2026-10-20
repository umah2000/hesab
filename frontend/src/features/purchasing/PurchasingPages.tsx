import { keepPreviousData, useQuery } from "@tanstack/react-query";
import { CalendarClock, ClipboardList, FilePlus2, ReceiptText } from "lucide-react";
import * as React from "react";
import { Link, NavLink, Outlet, useNavigate } from "react-router";
import { PageTitle } from "@/components/layout/AppShell";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { Badge, EmptyState, ErrorBox, Spinner } from "@/components/ui/feedback";
import { Field, Input, Select } from "@/components/ui/form-controls";
import { Pagination, Table, Td, Th, Tr } from "@/components/ui/table";
import { useCurrency } from "@/features/accounting/api";
import { JalaliDateInput } from "@/features/accounting/inputs";
import { useCan } from "@/features/auth/auth";
import { usePartyOptions } from "@/features/parties/api";
import { api, type Page } from "@/lib/api";
import { formatMoney, toEnDigits, toFaDigits } from "@/lib/format";
import { isoToJalaliFa, todayIso } from "@/lib/jalali";
import { cn } from "@/lib/utils";
import { type InvoiceSummary, ORDER_STATUS, type OrderStatus, type OrderSummary, PERM, useDues } from "./api";
import { DocLink, InvoiceStatusBadge, KindBadge, OrderStatusBadge, PartyPicker } from "./shared";

export { PurchaseInvoicePage } from "./InvoiceEditor";
export { PurchaseOrderPage } from "./OrderEditor";

const TABS = [
  { to: "/purchasing/invoices", label: "فاکتورهای خرید" },
  { to: "/purchasing/orders", label: "سفارش‌های خرید" },
  { to: "/purchasing/dues", label: "سررسید بدهی‌ها" },
];

export function PurchasingLayout() {
  const can = useCan();
  return (
    <>
      <PageTitle title="خرید" subtitle="سفارش خرید، فاکتور و برگشت از خرید، سررسید بدهی به تأمین‌کنندگان" />
      {can(PERM) ? (
        <nav className="no-print glass mb-4 flex gap-1 overflow-x-auto rounded-2xl p-1.5" aria-label="بخش‌های خرید">
          {TABS.map((t) => (
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
      ) : null}
      <Outlet />
    </>
  );
}

// --- invoices -------------------------------------------------------------------

export function PurchaseInvoicesPage() {
  const currency = useCurrency();
  const nav = useNavigate();
  const suppliers = usePartyOptions("supplier");
  const [page, setPage] = React.useState(1);
  const [kind, setKind] = React.useState("");
  const [status, setStatus] = React.useState("");
  const [supplier, setSupplier] = React.useState<string | null>(null);
  const [from, setFrom] = React.useState<string | null>(null);
  const [to, setTo] = React.useState<string | null>(null);
  const [q, setQ] = React.useState("");
  const reset = <T,>(fn: (v: T) => void) => (v: T) => {
    fn(v);
    setPage(1);
  };
  const params = new URLSearchParams({ page: String(page), page_size: "50" });
  if (kind) params.set("kind", kind);
  if (status) params.set("status", status);
  if (supplier) params.set("supplier_id", supplier);
  if (from) params.set("date_from", from);
  if (to) params.set("date_to", to);
  if (q.trim()) params.set("q", toEnDigits(q.trim()));
  const list = useQuery({
    queryKey: ["purchasing", "invoices", params.toString()],
    queryFn: () => api.get<Page<InvoiceSummary>>(`/purchasing/invoices?${params}`),
    placeholderData: keepPreviousData,
  });

  return (
    <Card>
      <div className="flex flex-wrap items-end gap-3 p-4">
        <Field label="نوع">
          <Select className="w-36" value={kind} onChange={(e) => reset(setKind)(e.target.value)}>
            <option value="">خرید و برگشت</option>
            <option value="invoice">خرید</option>
            <option value="return">برگشت از خرید</option>
          </Select>
        </Field>
        <Field label="وضعیت">
          <Select className="w-32" value={status} onChange={(e) => reset(setStatus)(e.target.value)}>
            <option value="">همه</option>
            <option value="draft">پیش‌نویس</option>
            <option value="final">قطعی</option>
          </Select>
        </Field>
        <Field label="تأمین‌کننده" className="w-72">
          <PartyPicker options={suppliers.data ?? []} value={supplier} onChange={reset(setSupplier)} ariaLabel="تأمین‌کننده" placeholder="همه تأمین‌کنندگان" />
        </Field>
        <Field label="از تاریخ">
          <JalaliDateInput className="w-32" value={from} onChange={reset(setFrom)} />
        </Field>
        <Field label="تا تاریخ">
          <JalaliDateInput className="w-32" value={to} onChange={reset(setTo)} />
        </Field>
        <Field label="شماره / شماره فاکتور فروشنده">
          <Input className="w-40" dir="ltr" value={q} onChange={(e) => reset(setQ)(e.target.value)} />
        </Field>
        <div className="flex-1" />
        <Button asChild>
          <Link to="/purchasing/invoices/new">
            <FilePlus2 /> فاکتور خرید جدید
          </Link>
        </Button>
      </div>
      <div className="surface mx-4 mb-4 overflow-hidden rounded-2xl">
        {list.isLoading ? (
          <Spinner />
        ) : list.isError ? (
          <ErrorBox error={list.error} />
        ) : !list.data?.items.length ? (
          <EmptyState icon={ReceiptText} title="فاکتور خریدی یافت نشد" description="فاکتور تأمین‌کننده را ثبت کنید؛ کالا با قطعی شدن فاکتور وارد انبار می‌شود." />
        ) : (
          <>
            <Table>
              <thead>
                <tr>
                  <Th className="w-24">شماره</Th>
                  <Th className="w-32">نوع</Th>
                  <Th className="w-28">وضعیت</Th>
                  <Th>تأمین‌کننده</Th>
                  <Th className="w-36">ش. فاکتور فروشنده</Th>
                  <Th className="w-28">تاریخ</Th>
                  <Th className="w-28">سررسید</Th>
                  <Th className="w-40">مبلغ کل</Th>
                </tr>
              </thead>
              <tbody>
                {list.data.items.map((i) => (
                  <Tr key={i.id} className="cursor-pointer" onClick={() => nav(`/purchasing/invoices/${i.id}`)}>
                    <Td className="tabular font-bold">{i.number ? toFaDigits(i.number) : <span className="font-normal text-ink-faint">پیش‌نویس</span>}</Td>
                    <Td><KindBadge kind={i.kind} /></Td>
                    <Td><InvoiceStatusBadge status={i.status} /></Td>
                    <Td>{i.supplier_name}</Td>
                    <Td className="tabular text-ink-soft" dir="ltr">{i.supplier_invoice_no ? toFaDigits(i.supplier_invoice_no) : "—"}</Td>
                    <Td className="tabular text-ink-soft">{isoToJalaliFa(i.document_date)}</Td>
                    <Td className="tabular text-ink-soft">{i.due_date ? isoToJalaliFa(i.due_date) : "—"}</Td>
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

// --- orders ---------------------------------------------------------------------

export function PurchaseOrdersPage() {
  const currency = useCurrency();
  const nav = useNavigate();
  const suppliers = usePartyOptions("supplier");
  const [page, setPage] = React.useState(1);
  const [status, setStatus] = React.useState("");
  const [supplier, setSupplier] = React.useState<string | null>(null);
  const params = new URLSearchParams({ page: String(page), page_size: "50" });
  if (status) params.set("status", status);
  if (supplier) params.set("supplier_id", supplier);
  const list = useQuery({
    queryKey: ["purchasing", "orders", params.toString()],
    queryFn: () => api.get<Page<OrderSummary>>(`/purchasing/orders?${params}`),
    placeholderData: keepPreviousData,
  });

  return (
    <Card>
      <div className="flex flex-wrap items-end gap-3 p-4">
        <Field label="وضعیت">
          <Select className="w-36" value={status} onChange={(e) => { setStatus(e.target.value); setPage(1); }}>
            <option value="">همه وضعیت‌ها</option>
            {(Object.keys(ORDER_STATUS) as OrderStatus[]).map((s) => (
              <option key={s} value={s}>{ORDER_STATUS[s].label}</option>
            ))}
          </Select>
        </Field>
        <Field label="تأمین‌کننده" className="w-72">
          <PartyPicker options={suppliers.data ?? []} value={supplier} onChange={(v) => { setSupplier(v); setPage(1); }} ariaLabel="تأمین‌کننده" placeholder="همه تأمین‌کنندگان" />
        </Field>
        <div className="flex-1" />
        <Button asChild>
          <Link to="/purchasing/orders/new">
            <FilePlus2 /> سفارش جدید
          </Link>
        </Button>
      </div>
      <div className="surface mx-4 mb-4 overflow-hidden rounded-2xl">
        {list.isLoading ? (
          <Spinner />
        ) : list.isError ? (
          <ErrorBox error={list.error} />
        ) : !list.data?.items.length ? (
          <EmptyState icon={ClipboardList} title="سفارش خریدی یافت نشد" />
        ) : (
          <>
            <Table>
              <thead>
                <tr>
                  <Th className="w-24">شماره</Th>
                  <Th className="w-28">وضعیت</Th>
                  <Th>تأمین‌کننده</Th>
                  <Th>انبار</Th>
                  <Th className="w-28">تاریخ سفارش</Th>
                  <Th className="w-28">تاریخ تحویل</Th>
                  <Th className="w-40">برآورد مبلغ</Th>
                </tr>
              </thead>
              <tbody>
                {list.data.items.map((o) => (
                  <Tr key={o.id} className="cursor-pointer" onClick={() => nav(`/purchasing/orders/${o.id}`)}>
                    <Td className="tabular font-bold">{o.number ? toFaDigits(o.number) : <span className="font-normal text-ink-faint">پیش‌نویس</span>}</Td>
                    <Td><OrderStatusBadge status={o.status} /></Td>
                    <Td>{o.supplier_name}</Td>
                    <Td className="text-ink-soft">{o.warehouse_name}</Td>
                    <Td className="tabular text-ink-soft">{isoToJalaliFa(o.order_date)}</Td>
                    <Td className="tabular text-ink-soft">{o.expected_date ? isoToJalaliFa(o.expected_date) : "—"}</Td>
                    <Td className="tabular font-semibold">{formatMoney(o.estimated_total, currency)}</Td>
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

// --- dues -----------------------------------------------------------------------

export function PurchaseDuesPage() {
  const currency = useCurrency();
  const [days, setDays] = React.useState(7);
  const dues = useDues(days);
  const today = todayIso();

  return (
    <Card>
      <div className="flex flex-wrap items-end gap-3 p-4">
        <Field label="بازه">
          <Select className="w-56" value={days} onChange={(e) => setDays(Number(e.target.value))}>
            <option value={0}>فقط سررسیدشده تا امروز</option>
            <option value={7}>تا ۷ روز آینده</option>
            <option value={30}>تا ۳۰ روز آینده</option>
          </Select>
        </Field>
        <p className="max-w-xl pb-2 text-xs text-ink-faint">
          پرداخت‌ها به فاکتور تخصیص داده نمی‌شوند؛ مانده باز با فرض تسویه قدیمی‌ترین فاکتورها برآورد شده است.
        </p>
      </div>
      <div className="surface mx-4 mb-4 overflow-x-auto rounded-2xl">
        {dues.isLoading ? (
          <Spinner />
        ) : dues.isError ? (
          <ErrorBox error={dues.error} />
        ) : !dues.data?.length ? (
          <EmptyState icon={CalendarClock} title="بدهی سررسیدی در این بازه نیست" />
        ) : (
          <Table>
            <thead>
              <tr>
                <Th>تأمین‌کننده</Th>
                <Th className="w-24">فاکتور</Th>
                <Th className="w-32">ش. فاکتور فروشنده</Th>
                <Th className="w-28">تاریخ</Th>
                <Th className="w-28">سررسید</Th>
                <Th className="w-40">وضعیت</Th>
                <Th className="w-36">مبلغ فاکتور</Th>
                <Th className="w-36">مانده باز</Th>
                <Th className="w-36">مانده تأمین‌کننده</Th>
              </tr>
            </thead>
            <tbody>
              {dues.data.map((d) => (
                <Tr key={d.invoice_id}>
                  <Td>{d.supplier_name}</Td>
                  <Td className="tabular">
                    <DocLink to={`/purchasing/invoices/${d.invoice_id}`}>{d.number ? toFaDigits(d.number) : "مشاهده"}</DocLink>
                  </Td>
                  <Td className="tabular text-ink-soft" dir="ltr">{d.supplier_invoice_no ? toFaDigits(d.supplier_invoice_no) : "—"}</Td>
                  <Td className="tabular text-ink-soft">{isoToJalaliFa(d.document_date)}</Td>
                  <Td className="tabular">{isoToJalaliFa(d.due_date)}</Td>
                  <Td>
                    {d.overdue_days > 0 ? (
                      <Badge tone="danger">سررسید گذشته · {toFaDigits(d.overdue_days)} روز</Badge>
                    ) : d.due_date === today ? (
                      <Badge tone="warning">سررسید امروز</Badge>
                    ) : (
                      <Badge tone="info">سررسید نزدیک</Badge>
                    )}
                  </Td>
                  <Td className="tabular text-ink-soft">{formatMoney(d.grand_total, currency)}</Td>
                  <Td className="tabular font-semibold">{formatMoney(d.outstanding, currency)}</Td>
                  <Td className="tabular text-ink-soft">{formatMoney(d.supplier_balance, currency)}</Td>
                </Tr>
              ))}
            </tbody>
          </Table>
        )}
      </div>
    </Card>
  );
}
