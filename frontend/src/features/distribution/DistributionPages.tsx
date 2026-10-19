import { keepPreviousData, useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { MapPinned, Plus, ShieldAlert, Smartphone, Trash2, Truck, UserPlus } from "lucide-react";
import * as React from "react";
import { Link, NavLink, Outlet, useNavigate, useParams } from "react-router";
import { toast } from "sonner";
import { PageTitle } from "@/components/layout/AppShell";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { Dialog, DialogContent, DialogFooter } from "@/components/ui/dialog";
import { Badge, EmptyState, ErrorBox, Spinner } from "@/components/ui/feedback";
import { Field, Input, Select } from "@/components/ui/form-controls";
import { Pagination, Table, Td, Th, Tr } from "@/components/ui/table";
import { useCurrency } from "@/features/accounting/api";
import { useCan } from "@/features/auth/auth";
import type { PartySummary } from "@/features/parties/api";
import type { Branch, CashRegister } from "@/features/settings/types";
import { ApiError, api, type Page } from "@/lib/api";
import { formatDateTime, formatMoney, toFaDigits } from "@/lib/format";
import { cn } from "@/lib/utils";
import {
  type AssignedCustomer,
  type Candidate,
  ORDER_STATUS,
  type Order,
  type OrderStatus,
  type OrderSummary,
  OUTCOME_LABEL,
  type Visit,
  type Visitor,
  WEEKDAYS,
} from "./api";

const MANAGE = "distribution.manage";
const onError = (e: unknown) => toast.error(e instanceof ApiError ? e.message : "خطا");

const TABS = [
  { to: "/distribution/orders", label: "سفارش‌ها" },
  { to: "/distribution/visitors", label: "ویزیتورها و مسیر" },
  { to: "/distribution/visits", label: "بازدیدها" },
];

export function DistributionLayout() {
  const can = useCan();
  return (
    <>
      <PageTitle
        title="ویزیتور و توزیع"
        subtitle="سفارش‌های اپلیکیشن ویزیتور، تأیید و فاکتور، مشتریان هر ویزیتور و بازدیدها"
        actions={
          can("reports.dashboard") || can(MANAGE) ? (
            <Button asChild variant="outline">
              <Link to="/reports/visitor-performance">عملکرد ویزیتورها</Link>
            </Button>
          ) : null
        }
      />
      {can(MANAGE) ? (
        <>
          <nav className="no-print glass mb-4 flex gap-1 overflow-x-auto rounded-2xl p-1.5" aria-label="بخش‌های توزیع">
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
          <Outlet />
        </>
      ) : (
        <Card>
          <EmptyState icon={ShieldAlert} title="دسترسی ندارید" description="برای این بخش مجوز «distribution.manage» لازم است." />
        </Card>
      )}
    </>
  );
}

export function OrderStatusBadge({ status }: { status: OrderStatus }) {
  const s = ORDER_STATUS[status];
  return <Badge tone={s.tone}>{s.label}</Badge>;
}

// --- orders -----------------------------------------------------------------------------

export function OrdersPage() {
  const currency = useCurrency();
  const nav = useNavigate();
  const [status, setStatus] = React.useState("open");
  const [page, setPage] = React.useState(1);
  const params = new URLSearchParams({ page: String(page), page_size: "50" });
  if (status) params.set("status", status);
  const list = useQuery({
    queryKey: ["distribution", "orders", params.toString()],
    queryFn: () => api.get<Page<OrderSummary>>(`/distribution/orders?${params}`),
    placeholderData: keepPreviousData,
    refetchInterval: 30_000,
  });
  return (
    <Card>
      <div className="flex flex-wrap items-end gap-3 p-4">
        <Field label="وضعیت">
          <Select value={status} onChange={(e) => { setStatus(e.target.value); setPage(1); }}>
            <option value="open">نیازمند اقدام (بررسی‌نشده و تأییدشده)</option>
            {Object.entries(ORDER_STATUS).map(([k, v]) => (
              <option key={k} value={k}>{v.label}</option>
            ))}
            <option value="">همه</option>
          </Select>
        </Field>
        <p className="max-w-2xl text-sm text-ink-soft">
          قیمت هر سفارش را سرور هنگام رسیدن تعیین می‌کند. سفارش موجودی و دفاتر را تغییر نمی‌دهد؛ «صدور فاکتور» آن را به فاکتور فروش نسیه تبدیل می‌کند.
        </p>
      </div>
      <div className="surface mx-4 mb-4 overflow-hidden rounded-2xl">
        {list.isLoading ? (
          <Spinner />
        ) : list.isError ? (
          <ErrorBox error={list.error} />
        ) : !list.data?.items.length ? (
          <EmptyState icon={Truck} title={status === "open" ? "سفارشی منتظر اقدام نیست" : "سفارشی یافت نشد"} />
        ) : (
          <>
            <Table>
              <thead>
                <tr>
                  <Th className="w-20">شماره</Th>
                  <Th>مشتری</Th>
                  <Th>ویزیتور</Th>
                  <Th>زمان ثبت</Th>
                  <Th className="w-40">مبلغ</Th>
                  <Th>وضعیت</Th>
                </tr>
              </thead>
              <tbody>
                {list.data.items.map((o) => (
                  <Tr key={o.id} className="cursor-pointer" onClick={() => nav(`/distribution/orders/${o.id}`)}>
                    <Td className="tabular font-bold">{toFaDigits(o.number ?? 0)}</Td>
                    <Td className="font-medium">{o.customer_name}</Td>
                    <Td className="text-ink-soft">{o.visitor_name}</Td>
                    <Td className="text-ink-soft">{formatDateTime(o.ordered_at)}</Td>
                    <Td className="tabular font-semibold">
                      {formatMoney(o.grand_total, currency)}
                      {o.price_changed ? <div className="text-xs font-normal text-warning">قیمت با برآورد گوشی فرق داشت</div> : null}
                    </Td>
                    <Td>
                      <OrderStatusBadge status={o.status} />
                      {o.invoice_number ? <span className="ms-2 text-xs text-ink-faint">فاکتور {toFaDigits(o.invoice_number)}</span> : null}
                    </Td>
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

export function OrderPage() {
  const { id = "" } = useParams();
  const currency = useCurrency();
  const order = useQuery({ queryKey: ["distribution", "order", id], queryFn: () => api.get<Order>(`/distribution/orders/${id}`) });
  const [dialog, setDialog] = React.useState<null | "approve" | "reject" | "invoice" | "deliver">(null);
  if (order.isLoading) return <Spinner />;
  if (order.isError || !order.data) return <ErrorBox error={order.error} />;
  const o = order.data;
  return (
    <div className="flex flex-col gap-4">
      <Card className="p-5">
        <div className="flex flex-wrap items-start justify-between gap-3">
          <div>
            <div className="flex items-center gap-2">
              <h2 className="text-lg font-extrabold text-ink">سفارش {toFaDigits(o.number ?? 0)} — {o.customer_name}</h2>
              <OrderStatusBadge status={o.status} />
            </div>
            <p className="mt-1 text-sm text-ink-soft">
              ویزیتور {o.visitor_name} · ثبت روی گوشی {formatDateTime(o.ordered_at)} · رسیدن به سرور {formatDateTime(o.received_at)}
            </p>
            {o.note ? <p className="mt-1 text-sm">توضیح: {o.note}</p> : null}
            {o.decided_by_name ? (
              <p className="mt-1 text-sm text-ink-soft">
                تصمیم: {o.decided_by_name} {o.decided_at ? `(${formatDateTime(o.decided_at)})` : ""}
                {o.decision_note ? ` — ${o.decision_note}` : ""}
              </p>
            ) : null}
            {o.invoice_id ? (
              <Link className="mt-1 inline-block text-sm text-brand-600 underline" to={`/sales/invoices/${o.invoice_id}`}>
                فاکتور فروش {toFaDigits(o.invoice_number ?? 0)}
              </Link>
            ) : null}
            {o.delivered_at ? <p className="mt-1 text-sm text-ink-soft">تحویل: {formatDateTime(o.delivered_at)}</p> : null}
          </div>
          <div className="flex flex-wrap gap-2">
            {o.status === "submitted" ? <Button onClick={() => setDialog("approve")}>تأیید سفارش</Button> : null}
            {o.status === "approved" ? <Button onClick={() => setDialog("invoice")}>صدور فاکتور</Button> : null}
            {o.status === "invoiced" ? <Button onClick={() => setDialog("deliver")}>ثبت تحویل</Button> : null}
            {o.status === "submitted" || o.status === "approved" ? (
              <Button variant="outline" onClick={() => setDialog("reject")}>رد سفارش</Button>
            ) : null}
          </div>
        </div>
      </Card>
      <Card>
        <div className="surface m-4 overflow-hidden rounded-2xl">
          <Table>
            <thead>
              <tr>
                <Th className="w-12">#</Th>
                <Th>کالا</Th>
                <Th>مقدار</Th>
                <Th>فی</Th>
                <Th>تخفیف</Th>
                <Th>مالیات</Th>
                <Th className="w-40">مبلغ</Th>
              </tr>
            </thead>
            <tbody>
              {o.lines.map((l) => (
                <Tr key={l.line_no}>
                  <Td className="tabular">{toFaDigits(l.line_no)}</Td>
                  <Td>
                    <div className="font-medium">{l.item_name}</div>
                    {l.promotion_name ? <div className="text-xs text-ink-faint">پروموشن: {l.promotion_name}</div> : null}
                  </Td>
                  <Td className="tabular">{toFaDigits(Number(l.qty))} {l.unit_name}</Td>
                  <Td className="tabular">{formatMoney(l.unit_price, currency)}</Td>
                  <Td className="tabular">{formatMoney(l.promotion_discount, currency)}</Td>
                  <Td className="tabular">{formatMoney(l.tax, currency)}</Td>
                  <Td className="tabular font-semibold">{formatMoney(l.line_total, currency)}</Td>
                </Tr>
              ))}
            </tbody>
          </Table>
          <div className="flex flex-col items-end gap-1 p-4 text-sm">
            <div>جمع: <span className="tabular">{formatMoney(o.subtotal, currency)}</span></div>
            <div>تخفیف: <span className="tabular">{formatMoney(o.discount_total, currency)}</span></div>
            <div>مالیات: <span className="tabular">{formatMoney(o.tax_total, currency)}</span></div>
            <div className="text-base font-extrabold">قابل پرداخت: <span className="tabular">{formatMoney(o.grand_total, currency)}</span></div>
            {o.price_changed && o.client_total ? (
              <div className="text-ink-soft">برآوردی که ویزیتور دیده بود: {formatMoney(o.client_total, currency)}</div>
            ) : null}
          </div>
        </div>
      </Card>
      {dialog ? <DecisionDialog order={o} kind={dialog} onClose={() => setDialog(null)} /> : null}
    </div>
  );
}

function DecisionDialog({ order, kind, onClose }: { order: Order; kind: "approve" | "reject" | "invoice" | "deliver"; onClose: () => void }) {
  const qc = useQueryClient();
  const [note, setNote] = React.useState("");
  const [register, setRegister] = React.useState(() => localStorage.getItem("nc.distribution.register") ?? "");
  const registers = useQuery({
    queryKey: ["registers", order.branch_id],
    enabled: kind === "invoice",
    queryFn: () => api.get<CashRegister[]>(`/organization/branches/${order.branch_id}/cash-registers`),
  });
  const save = useMutation({
    mutationFn: () => {
      const body = kind === "invoice" ? { cash_register_id: register } : { note: note.trim() || null };
      return api.post<Order>(`/distribution/orders/${order.id}/${kind}`, body, { version: order.row_version });
    },
    onSuccess: (o) => {
      if (kind === "invoice") {
        try { localStorage.setItem("nc.distribution.register", register); } catch { /* per-browser convenience only */ }
      }
      qc.invalidateQueries({ queryKey: ["distribution"] });
      toast.success(kind === "invoice" ? `فاکتور ${toFaDigits(o.invoice_number ?? 0)} صادر شد` : "ثبت شد");
      onClose();
    },
    onError,
  });
  const title = { approve: "تأیید سفارش", reject: "رد سفارش", invoice: "صدور فاکتور فروش نسیه", deliver: "ثبت تحویل" }[kind];
  const valid = kind === "reject" ? note.trim().length >= 2 : kind === "invoice" ? !!register : true;
  return (
    <Dialog open onOpenChange={(o) => !o && onClose()}>
      <DialogContent title={title} description={`${order.customer_name} — سفارش ${toFaDigits(order.number ?? 0)}`}>
        <div className="flex flex-col gap-3 text-sm">
          {kind === "approve" ? <p className="text-ink-soft">سقف اعتبار مشتری با بدهی فعلی و سفارش‌های تأییدشده‌ی دیگر بررسی می‌شود.</p> : null}
          {kind === "invoice" ? (
            <>
              <p className="text-ink-soft">
                با همین قیمت‌های تأییدشده فاکتور فروش نسیه صادر می‌شود: خروج کالا از انبار شعبه، سند حسابداری و شماره‌ی فاکتور. صندوقی را انتخاب کنید که این فروش در گزارش آن بیاید (مثلاً «فروش ویزیتوری»).
              </p>
              <Field label="صندوق">
                <Select value={register} onChange={(e) => setRegister(e.target.value)}>
                  <option value="">انتخاب کنید</option>
                  {registers.data?.filter((r) => r.is_active).map((r) => (
                    <option key={r.id} value={r.id}>{r.name}</option>
                  ))}
                </Select>
              </Field>
            </>
          ) : (
            <Field label={kind === "reject" ? "علت (به ویزیتور نمایش داده می‌شود)" : "توضیح (اختیاری)"}>
              <Input value={note} onChange={(e) => setNote(e.target.value)} />
            </Field>
          )}
        </div>
        <DialogFooter>
          <Button loading={save.isPending} disabled={!valid} onClick={() => save.mutate()}>{title}</Button>
          <Button variant="ghost" onClick={onClose}>انصراف</Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}

// --- visitors ---------------------------------------------------------------------------

export function VisitorsPage() {
  const nav = useNavigate();
  const list = useQuery({ queryKey: ["distribution", "visitors"], queryFn: () => api.get<Visitor[]>("/distribution/visitors") });
  const [creating, setCreating] = React.useState(false);
  return (
    <Card>
      <div className="flex flex-wrap items-center justify-between gap-3 p-4">
        <p className="max-w-2xl text-sm text-ink-soft">
          ویزیتور کاربری با نقش «ویزیتور» است که با اپلیکیشن اندروید وارد می‌شود و فقط مشتریان تخصیص‌یافته به خودش را می‌بیند.
        </p>
        <Button onClick={() => setCreating(true)}><UserPlus /> ویزیتور جدید</Button>
      </div>
      <div className="surface mx-4 mb-4 overflow-hidden rounded-2xl">
        {list.isLoading ? (
          <Spinner />
        ) : !list.data?.length ? (
          <EmptyState icon={Smartphone} title="هنوز ویزیتوری تعریف نشده" description="ابتدا در «کاربران» کاربری با نقش ویزیتور بسازید." />
        ) : (
          <Table>
            <thead>
              <tr>
                <Th>ویزیتور</Th>
                <Th>کد</Th>
                <Th>شعبه</Th>
                <Th>مشتریان</Th>
                <Th>آخرین استفاده از اپ</Th>
                <Th>وضعیت</Th>
              </tr>
            </thead>
            <tbody>
              {list.data.map((v) => (
                <Tr key={v.id} className="cursor-pointer" onClick={() => nav(`/distribution/visitors/${v.id}`)}>
                  <Td className="font-medium">{v.name} <span className="text-xs text-ink-faint" dir="ltr">({v.username})</span></Td>
                  <Td className="latin-digits">{v.code}</Td>
                  <Td>{v.branch_name}</Td>
                  <Td className="tabular">{toFaDigits(v.customer_count)}</Td>
                  <Td className="text-ink-soft">{v.last_seen_at ? formatDateTime(v.last_seen_at) : "—"}</Td>
                  <Td>{v.is_active ? <Badge tone="success">فعال</Badge> : <Badge tone="neutral">غیرفعال</Badge>}</Td>
                </Tr>
              ))}
            </tbody>
          </Table>
        )}
      </div>
      {creating ? <NewVisitorDialog onClose={() => setCreating(false)} /> : null}
    </Card>
  );
}

function NewVisitorDialog({ onClose }: { onClose: () => void }) {
  const qc = useQueryClient();
  const cands = useQuery({ queryKey: ["distribution", "candidates"], queryFn: () => api.get<Candidate[]>("/distribution/candidates") });
  const branches = useQuery({ queryKey: ["branches"], queryFn: () => api.get<Branch[]>("/organization/branches") });
  const [user, setUser] = React.useState("");
  const [branch, setBranch] = React.useState("");
  const [code, setCode] = React.useState("");
  const save = useMutation({
    mutationFn: () => api.post<Visitor>("/distribution/visitors", { user_id: user, branch_id: branch, code: code.trim() }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["distribution"] });
      toast.success("ویزیتور تعریف شد");
      onClose();
    },
    onError,
  });
  const free = cands.data?.filter((c) => !c.visitor_id) ?? [];
  return (
    <Dialog open onOpenChange={(o) => !o && onClose()}>
      <DialogContent title="ویزیتور جدید" description="کاربر باید نقش «ویزیتور» داشته باشد.">
        <div className="flex flex-col gap-3">
          <Field label="کاربر">
            <Select value={user} onChange={(e) => setUser(e.target.value)}>
              <option value="">{free.length ? "انتخاب کنید" : "کاربر بدون ویزیتور با نقش ویزیتور نیست"}</option>
              {free.map((c) => (
                <option key={c.user_id} value={c.user_id}>{c.full_name} ({c.username})</option>
              ))}
            </Select>
          </Field>
          <Field label="شعبه">
            <Select value={branch} onChange={(e) => setBranch(e.target.value)}>
              <option value="">انتخاب کنید</option>
              {branches.data?.map((b) => <option key={b.id} value={b.id}>{b.name}</option>)}
            </Select>
          </Field>
          <Field label="کد ویزیتور" hint="حروف و رقم لاتین، مثلاً V01">
            <Input dir="ltr" value={code} onChange={(e) => setCode(e.target.value)} />
          </Field>
        </div>
        <DialogFooter>
          <Button loading={save.isPending} disabled={!user || !branch || !code.trim()} onClick={() => save.mutate()}>تعریف</Button>
          <Button variant="ghost" onClick={onClose}>انصراف</Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}

type Row = { customer_id: string; name: string; code: string; visit_weekday: number | null };

export function VisitorPage() {
  const { id = "" } = useParams();
  const qc = useQueryClient();
  const currency = useCurrency();
  const visitor = useQuery({ queryKey: ["distribution", "visitor", id], queryFn: () => api.get<Visitor>(`/distribution/visitors/${id}`) });
  const assigned = useQuery({
    queryKey: ["distribution", "visitor", id, "customers"],
    queryFn: () => api.get<AssignedCustomer[]>(`/distribution/visitors/${id}/customers`),
  });
  const [rows, setRows] = React.useState<Row[] | null>(null);
  const [q, setQ] = React.useState("");
  const search = useQuery({
    queryKey: ["parties", "customers", q],
    enabled: q.trim().length >= 2,
    queryFn: () => api.get<Page<PartySummary>>(`/parties?role=customer&active=true&page_size=10&q=${encodeURIComponent(q.trim())}`),
  });
  const current: Row[] =
    rows ?? (assigned.data ?? []).map((c) => ({ customer_id: c.customer_id, name: c.name, code: c.code, visit_weekday: c.visit_weekday }));
  const byId = new Map((assigned.data ?? []).map((c) => [c.customer_id, c]));
  const save = useMutation({
    mutationFn: () =>
      api.put<AssignedCustomer[]>(
        `/distribution/visitors/${id}/customers`,
        { customers: current.map((r) => ({ customer_id: r.customer_id, visit_weekday: r.visit_weekday })) },
        "",
      ),
    onSuccess: () => {
      setRows(null);
      qc.invalidateQueries({ queryKey: ["distribution"] });
      toast.success("مشتریان ویزیتور ذخیره شد");
    },
    onError,
  });
  const toggle = useMutation({
    mutationFn: (v: Visitor) =>
      api.put<Visitor>(`/distribution/visitors/${v.id}`, { branch_id: v.branch_id, is_active: !v.is_active, note: v.note }, v.row_version),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["distribution"] }),
    onError,
  });
  if (visitor.isLoading || assigned.isLoading) return <Spinner />;
  if (!visitor.data) return <ErrorBox error={visitor.error} />;
  const v = visitor.data;
  const update = (next: Row[]) => setRows(next);
  return (
    <div className="flex flex-col gap-4">
      <Card className="flex flex-wrap items-center justify-between gap-3 p-5">
        <div>
          <h2 className="text-lg font-extrabold text-ink">{v.name} <span className="latin-digits text-sm text-ink-faint">{v.code}</span></h2>
          <p className="text-sm text-ink-soft">{v.branch_name} · آخرین استفاده از اپ: {v.last_seen_at ? formatDateTime(v.last_seen_at) : "—"}</p>
        </div>
        <Button variant="outline" loading={toggle.isPending} onClick={() => toggle.mutate(v)}>
          {v.is_active ? "غیرفعال کردن" : "فعال کردن"}
        </Button>
      </Card>
      <Card>
        <div className="flex flex-wrap items-end gap-3 p-4">
          <Field label="افزودن مشتری">
            <Input className="w-72" placeholder="نام یا کد مشتری" value={q} onChange={(e) => setQ(e.target.value)} />
          </Field>
          {search.data?.items.length ? (
            <div className="flex flex-wrap gap-2">
              {search.data.items
                .filter((p) => !current.some((r) => r.customer_id === p.id))
                .map((p) => (
                  <Button
                    key={p.id}
                    size="sm"
                    variant="outline"
                    onClick={() => {
                      update([...current, { customer_id: p.id, name: p.name, code: p.code, visit_weekday: null }]);
                      setQ("");
                    }}
                  >
                    <Plus /> {p.name}
                  </Button>
                ))}
            </div>
          ) : null}
          <div className="flex-1" />
          <Button disabled={rows === null} loading={save.isPending} onClick={() => save.mutate()}>ذخیره‌ی مشتریان و مسیر</Button>
        </div>
        <div className="surface mx-4 mb-4 overflow-hidden rounded-2xl">
          {!current.length ? (
            <EmptyState icon={MapPinned} title="مشتری‌ای تخصیص داده نشده" description="ویزیتور فقط مشتریان همین فهرست را در اپ می‌بیند." />
          ) : (
            <Table>
              <thead>
                <tr>
                  <Th>مشتری</Th>
                  <Th>روز بازدید</Th>
                  <Th>مانده</Th>
                  <Th>اعتبار باقی‌مانده</Th>
                  <Th className="w-12" />
                </tr>
              </thead>
              <tbody>
                {current.map((r, i) => {
                  const info = byId.get(r.customer_id);
                  return (
                    <Tr key={r.customer_id}>
                      <Td className="font-medium">{r.name} <span className="text-xs text-ink-faint">{toFaDigits(r.code)}</span></Td>
                      <Td>
                        <Select
                          aria-label={`روز بازدید ${r.name}`}
                          value={r.visit_weekday ?? ""}
                          onChange={(e) =>
                            update(current.map((x, j) => (j === i ? { ...x, visit_weekday: e.target.value === "" ? null : Number(e.target.value) } : x)))
                          }
                        >
                          <option value="">بدون روز ثابت</option>
                          {WEEKDAYS.map((d, n) => <option key={d} value={n}>{d}</option>)}
                        </Select>
                      </Td>
                      <Td className="tabular">{info ? formatMoney(info.balance, currency) : "—"}</Td>
                      <Td className="tabular">{info?.available ? formatMoney(info.available, currency) : info ? "نسیه تعریف نشده" : "—"}</Td>
                      <Td>
                        <Button size="sm" variant="ghost" aria-label={`حذف ${r.name}`} onClick={() => update(current.filter((_, j) => j !== i))}>
                          <Trash2 />
                        </Button>
                      </Td>
                    </Tr>
                  );
                })}
              </tbody>
            </Table>
          )}
        </div>
      </Card>
    </div>
  );
}

// --- visits -----------------------------------------------------------------------------

export function VisitsPage() {
  const visits = useQuery({ queryKey: ["distribution", "visits"], queryFn: () => api.get<Visit[]>("/distribution/visits") });
  return (
    <Card>
      <div className="surface m-4 overflow-hidden rounded-2xl">
        {visits.isLoading ? (
          <Spinner />
        ) : !visits.data?.length ? (
          <EmptyState icon={MapPinned} title="بازدیدی ثبت نشده" />
        ) : (
          <Table>
            <thead>
              <tr>
                <Th>زمان</Th>
                <Th>ویزیتور</Th>
                <Th>مشتری</Th>
                <Th>نتیجه</Th>
                <Th>توضیح</Th>
              </tr>
            </thead>
            <tbody>
              {visits.data.map((v) => (
                <Tr key={v.id}>
                  <Td className="text-ink-soft">{formatDateTime(v.visited_at)}</Td>
                  <Td>{v.visitor_name}</Td>
                  <Td className="font-medium">{v.customer_name}</Td>
                  <Td>
                    {v.outcome === "order" ? (
                      <Badge tone="success">{OUTCOME_LABEL.order}</Badge>
                    ) : (
                      <Badge tone="neutral">{OUTCOME_LABEL[v.outcome] ?? v.outcome}</Badge>
                    )}
                    {v.order_id ? (
                      <Link className="ms-2 text-xs text-brand-600 underline" to={`/distribution/orders/${v.order_id}`}>سفارش</Link>
                    ) : null}
                  </Td>
                  <Td className="text-ink-soft">{v.note ?? "—"}</Td>
                </Tr>
              ))}
            </tbody>
          </Table>
        )}
      </div>
    </Card>
  );
}
