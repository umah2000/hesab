import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { AlertTriangle, ArrowRight, CheckCheck, History, Plus, Save, Trash2, Undo2 } from "lucide-react";
import * as React from "react";
import { Link, useNavigate, useParams, useSearchParams } from "react-router";
import { toast } from "sonner";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { Dialog, DialogContent, DialogFooter } from "@/components/ui/dialog";
import { Badge, ErrorBox, Spinner } from "@/components/ui/feedback";
import { Field, Input, Select } from "@/components/ui/form-controls";
import { useCurrency } from "@/features/accounting/api";
import { JalaliDateInput, MoneyInput } from "@/features/accounting/inputs";
import { trimQty, useUnits, useWarehouses } from "@/features/inventory/api";
import { ItemSearch, type Picked } from "@/features/inventory/ItemSearch";
import { usePartyOptions } from "@/features/parties/api";
import { ApiError, api, newIdempotencyKey } from "@/lib/api";
import { type DisplayCurrency, formatMoney, toEnDigits, toFaDigits } from "@/lib/format";
import { isoToJalaliFa, todayIso } from "@/lib/jalali";
import { compareRials, inputToRials, rialsToInput } from "@/lib/money";
import { addQty, qtyUnits } from "@/lib/qty";
import { type Invoice, type InvoiceIn, type Order, type ReturnIn, useDefaultVatRate, usePriceHistory } from "./api";
import { parseQty, previewInvoice, remainingOrderQty, resolveVatRate } from "./preview";
import { DocLink, fetchItem, InvoiceStatusBadge, KindBadge, onError, PartyPicker, rejected, unitOptions, useItemsMeta } from "./shared";

const curLabel = (c: DisplayCurrency) => (c === "IRT" ? "تومان" : "ریال");

export function PurchaseInvoicePage() {
  const { id } = useParams();
  const isNew = !id || id === "new";
  const [params] = useSearchParams();
  const orderId = isNew ? params.get("order") : null;
  // Price-deviation warnings come only with the save response; keep them across the remount.
  const [warnings, setWarnings] = React.useState<{ id: string; list: string[] } | null>(null);
  const inv = useQuery({
    queryKey: ["purchasing", "invoice", id],
    queryFn: () => api.get<Invoice>(`/purchasing/invoices/${id}`),
    enabled: !isNew,
  });
  const order = useQuery({
    queryKey: ["purchasing", "order", orderId],
    queryFn: () => api.get<Order>(`/purchasing/orders/${orderId}`),
    enabled: !!orderId,
  });
  if ((!isNew && inv.isLoading) || (orderId && order.isLoading)) return <Spinner />;
  if (!isNew && inv.isError) return <ErrorBox error={inv.error} />;
  if (orderId && order.isError) return <ErrorBox error={order.error} />;
  if (inv.data?.status === "final") return <InvoiceView inv={inv.data} />;
  return (
    <InvoiceForm
      key={inv.data?.row_version ?? `new-${orderId ?? ""}`}
      inv={inv.data}
      order={isNew ? order.data : undefined}
      warnings={warnings && warnings.id === inv.data?.id ? warnings.list : []}
      onSaved={(saved) => setWarnings({ id: saved.id, list: saved.warnings ?? [] })}
    />
  );
}

// --- draft editor ---------------------------------------------------------------

type Row = {
  key: string;
  item_id: string;
  code: string;
  name: string;
  unit_id: string;
  unit_name: string;
  qty: string;
  cost: string; // display currency per line unit
  discount: string; // display currency
  vat: string; // override %, empty = item/organisation rate
  expiry: string | null;
  order_line_id: string | null;
};

type ChargeRow = { key: string; description: string; amount: string; payee_id: string | null };

function initialRows(inv: Invoice | undefined, order: Order | undefined, currency: DisplayCurrency): Row[] {
  if (inv) {
    return inv.lines.map((l) => ({
      key: l.id,
      item_id: l.item_id,
      code: l.item_code,
      name: l.item_name,
      unit_id: l.unit_id,
      unit_name: l.unit_name,
      qty: trimQty(l.qty),
      cost: rialsToInput(l.unit_cost, currency),
      discount: compareRials(l.discount, "0") === 0 ? "" : rialsToInput(l.discount, currency),
      vat: trimQty(l.vat_rate),
      expiry: l.expiry_date,
      order_line_id: l.order_line_id,
    }));
  }
  if (order) {
    return order.lines.flatMap((l) => {
      const left = remainingOrderQty(l.qty, l.base_qty, l.received_base_qty);
      if (qtyUnits(left) <= 0n) return [];
      return [
        {
          key: crypto.randomUUID(),
          item_id: l.item_id,
          code: l.item_code,
          name: l.item_name,
          unit_id: l.unit_id,
          unit_name: l.unit_name,
          qty: left,
          cost: l.unit_cost ? rialsToInput(l.unit_cost, currency) : "",
          discount: "",
          vat: "",
          expiry: null,
          order_line_id: l.id,
        },
      ];
    });
  }
  return [];
}

function InvoiceForm({
  inv,
  order,
  warnings,
  onSaved,
}: {
  inv?: Invoice;
  order?: Order;
  warnings: string[];
  onSaved: (saved: Invoice) => void;
}) {
  const qc = useQueryClient();
  const navigate = useNavigate();
  const currency = useCurrency();
  const orgVat = useDefaultVatRate();
  const units = useUnits();
  const warehouses = useWarehouses();
  const suppliers = usePartyOptions("supplier");
  const parties = usePartyOptions();
  const [dirty, setDirty] = React.useState(!inv);
  const [warehouse, setWarehouse] = React.useState(inv?.warehouse_id ?? order?.warehouse_id ?? "");
  const [supplier, setSupplier] = React.useState<string | null>(inv?.supplier_id ?? order?.supplier_id ?? null);
  const [date, setDate] = React.useState<string | null>(inv?.document_date ?? todayIso());
  const [supNo, setSupNo] = React.useState(inv?.supplier_invoice_no ?? "");
  const [supDate, setSupDate] = React.useState<string | null>(inv?.supplier_invoice_date ?? null);
  const [due, setDue] = React.useState<string | null>(inv?.due_date ?? null);
  const [note, setNote] = React.useState(inv?.note ?? "");
  const orderId = inv?.order_id ?? order?.id ?? null;
  const orderNumber = inv?.order_number ?? order?.number ?? null;
  const [rows, setRows] = React.useState<Row[]>(() => initialRows(inv, order, currency));
  const [charges, setCharges] = React.useState<ChargeRow[]>(() =>
    (inv?.charges ?? []).map((c) => ({ key: c.id, description: c.description, amount: rialsToInput(c.amount, currency), payee_id: c.payee_id })),
  );
  const [confirmOpen, setConfirmOpen] = React.useState(false);
  const keyRef = React.useRef(newIdempotencyKey());
  const searchRef = React.useRef<HTMLInputElement>(null);
  const meta = useItemsMeta(rows.map((r) => r.item_id));
  const unitName = (uid: string) => units.data?.find((u) => u.id === uid)?.name ?? "";

  const touch = <T,>(fn: (v: T) => void) => (v: T) => {
    fn(v);
    setDirty(true);
  };
  const patch = (key: string, p: Partial<Row>) => {
    setRows((rs) => rs.map((r) => (r.key === key ? { ...r, ...p } : r)));
    setDirty(true);
  };
  const patchCharge = (key: string, p: Partial<ChargeRow>) => {
    setCharges((cs) => cs.map((c) => (c.key === key ? { ...c, ...p } : c)));
    setDirty(true);
  };

  React.useEffect(() => {
    if (!warehouse && warehouses.data?.length) setWarehouse(warehouses.data.find((w) => w.is_active)?.id ?? warehouses.data[0].id);
  }, [warehouses.data, warehouse]);

  const addItem = async (p: Picked) => {
    const existing = rows.find((r) => r.item_id === p.item_id && !r.order_line_id && (!p.unit_id || r.unit_id === p.unit_id));
    if (existing) {
      // Decimal string math: scanning again adds to the same row (0.1 + 0.2 stays 0.3).
      const q = parseQty(existing.qty) !== null ? existing.qty : "0";
      patch(existing.key, { qty: addQty(toEnDigits(q), toEnDigits(p.qty ?? "1")) });
      return;
    }
    const item = await fetchItem(qc, p.item_id);
    const unit = p.unit_id ?? item.base_unit_id;
    setRows((rs) => [
      ...rs,
      {
        key: crypto.randomUUID(),
        item_id: item.id,
        code: item.code,
        name: item.name,
        unit_id: unit,
        unit_name: unit === item.base_unit_id ? item.base_unit_name : unitName(unit),
        qty: p.qty ?? "1",
        cost: "",
        discount: "",
        vat: "",
        expiry: null,
        order_line_id: null,
      },
    ]);
    setDirty(true);
  };

  const factorOf = (r: Row) => unitOptions(meta[r.item_id], unitName).find((u) => u.id === r.unit_id)?.factor ?? "1";
  const preview = previewInvoice(
    rows.map((r) => ({
      qty: toEnDigits(r.qty),
      unitCost: (r.cost.trim() ? inputToRials(r.cost, currency) : null) ?? "x",
      discount: r.discount.trim() ? (inputToRials(r.discount, currency) ?? "x") : "0",
      vatRate: resolveVatRate(r.vat, meta[r.item_id]?.vat_rate ?? null, meta[r.item_id]?.vat_exempt ?? false, orgVat),
      factor: factorOf(r),
    })),
    charges.map((c) => inputToRials(c.amount, currency) ?? "x"),
  );
  const server = inv && !dirty ? inv : null;
  const fig = (i: number) => (server ? server.lines[i] : preview.lines[i]);

  const payload = (): InvoiceIn => {
    if (!warehouse) throw new ApiError(0, "warehouse", "انبار را انتخاب کنید");
    if (!supplier) throw new ApiError(0, "supplier", "تأمین‌کننده را انتخاب کنید");
    if (!date) throw new ApiError(0, "date", "تاریخ سند نامعتبر است");
    if (!rows.length) throw new ApiError(0, "lines", "حداقل یک کالا اضافه کنید");
    return {
      warehouse_id: warehouse,
      supplier_id: supplier,
      document_date: date,
      supplier_invoice_no: supNo.trim() ? toEnDigits(supNo.trim()) : null,
      supplier_invoice_date: supDate,
      due_date: due,
      order_id: orderId,
      note: note.trim() || null,
      lines: rows.map((r, i) => {
        const n = toFaDigits(i + 1);
        const qty = toEnDigits(r.qty).trim();
        if (parseQty(qty) === null) throw new ApiError(0, "qty", `ردیف ${n}: مقدار نامعتبر است`);
        const cost = r.cost.trim() ? inputToRials(r.cost, currency) : null;
        if (cost === null) throw new ApiError(0, "cost", `ردیف ${n}: بهای واحد را وارد کنید`);
        const discount = r.discount.trim() ? inputToRials(r.discount, currency) : "0";
        if (discount === null) throw new ApiError(0, "discount", `ردیف ${n}: تخفیف نامعتبر است`);
        const vat = toEnDigits(r.vat).trim();
        return {
          item_id: r.item_id,
          unit_id: r.unit_id,
          qty,
          unit_cost: cost,
          discount,
          vat_rate: vat || null,
          expiry_date: r.expiry,
          order_line_id: r.order_line_id,
        };
      }),
      charges: charges.map((c, i) => {
        const amount = inputToRials(c.amount, currency);
        if (!amount || compareRials(amount, "0") <= 0) throw new ApiError(0, "charge", `هزینه جانبی ${toFaDigits(i + 1)}: مبلغ نامعتبر است`);
        return { description: c.description.trim(), amount, payee_id: c.payee_id };
      }),
    };
  };

  const saved = (d: Invoice) => {
    onSaved(d);
    qc.setQueryData(["purchasing", "invoice", d.id], d);
    qc.invalidateQueries({ queryKey: ["purchasing"], predicate: (q) => !(q.queryKey[1] === "invoice" && q.queryKey[2] === d.id) });
  };

  const save = useMutation({
    mutationFn: () => {
      const body = payload();
      return inv
        ? api.put<Invoice>(`/purchasing/invoices/${inv.id}`, body, inv.row_version)
        : api.post<Invoice>("/purchasing/invoices", body, { idempotencyKey: keyRef.current });
    },
    onSuccess: (d) => {
      saved(d);
      toast.success("پیش‌نویس ذخیره شد؛ مبالغ را سرور محاسبه کرد");
      if (!inv) navigate(`/purchasing/invoices/${d.id}`, { replace: true });
    },
    onError: (e) => {
      if (rejected(e)) keyRef.current = newIdempotencyKey();
      onError(e);
    },
  });
  const finalize = useMutation({
    mutationFn: () => api.post<Invoice>(`/purchasing/invoices/${inv!.id}/finalize`, undefined, { version: inv!.row_version }),
    onSuccess: (d) => {
      setConfirmOpen(false);
      saved(d);
      qc.invalidateQueries({ queryKey: ["inventory"] });
      qc.invalidateQueries({ queryKey: ["accounting"] });
      qc.invalidateQueries({ queryKey: ["parties"] });
      toast.success(`فاکتور خرید شماره ${toFaDigits(d.number ?? 0)} قطعی شد`);
    },
    onError,
  });
  const remove = useMutation({
    mutationFn: () => api.del(`/purchasing/invoices/${inv!.id}`, inv!.row_version),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["purchasing"] });
      toast.success("پیش‌نویس حذف شد");
      navigate("/purchasing/invoices");
    },
    onError,
  });
  const busy = save.isPending || finalize.isPending || remove.isPending;
  const supplierName = inv?.supplier_name ?? order?.supplier_name;

  return (
    <div className="flex flex-col gap-4">
      <div className="flex flex-wrap items-center gap-3">
        <Button variant="ghost" size="icon" asChild aria-label="بازگشت">
          <Link to="/purchasing/invoices">
            <ArrowRight />
          </Link>
        </Button>
        <h1 className="text-xl font-extrabold text-ink">{inv ? "پیش‌نویس فاکتور خرید" : "فاکتور خرید جدید"}</h1>
        <InvoiceStatusBadge status="draft" />
        {orderId ? <DocLink to={`/purchasing/orders/${orderId}`}>دریافت سفارش {orderNumber ? toFaDigits(orderNumber) : ""}</DocLink> : null}
      </div>

      <Card className="grid gap-4 p-5 md:grid-cols-3 xl:grid-cols-4">
        <Field label="تاریخ سند">
          <JalaliDateInput value={date} onChange={touch(setDate)} />
        </Field>
        <Field label="انبار">
          <Select value={warehouse} onChange={(e) => touch(setWarehouse)(e.target.value)}>
            {warehouses.data?.filter((w) => w.is_active || w.id === warehouse).map((w) => (
              <option key={w.id} value={w.id}>{w.name}</option>
            ))}
          </Select>
        </Field>
        <Field label="تأمین‌کننده" className="md:col-span-2" hint={orderId ? "تأمین‌کننده سفارش ثابت است" : undefined}>
          <PartyPicker
            options={suppliers.data ?? []}
            value={supplier}
            onChange={touch(setSupplier)}
            ariaLabel="تأمین‌کننده"
            placeholder="کد یا نام تأمین‌کننده"
            disabled={!!orderId}
            fallbackName={supplierName}
          />
        </Field>
        <Field label="شماره فاکتور فروشنده">
          <Input dir="ltr" maxLength={40} value={supNo} onChange={(e) => touch(setSupNo)(e.target.value)} />
        </Field>
        <Field label="تاریخ فاکتور فروشنده">
          <JalaliDateInput value={supDate} onChange={touch(setSupDate)} />
        </Field>
        <Field label="سررسید پرداخت" hint="خالی = تاریخ سند + مهلت پرداخت تأمین‌کننده">
          <JalaliDateInput value={due} onChange={touch(setDue)} />
        </Field>
        <Field label="یادداشت">
          <Input maxLength={500} value={note} onChange={(e) => touch(setNote)(e.target.value)} />
        </Field>
      </Card>

      <Card className="p-4">
        <ItemSearch ref={searchRef} autoFocus={!order} onPick={(p) => void addItem(p).then(() => searchRef.current?.focus()).catch(onError)} />
        <p className="mt-2 text-xs text-ink-faint">
          بها بدون مالیات بر ارزش افزوده و به ازای واحد همان ردیف وارد شود. خالی گذاشتن نرخ مالیات یعنی نرخ کالا (یا پیش‌فرض سازمان)؛ کالای معاف همیشه صفر است.
        </p>
      </Card>

      <Card className="p-2">
        <div className="surface overflow-x-auto rounded-2xl">
          <table className="w-full min-w-[86rem] text-sm">
            <thead>
              <tr className="text-xs text-ink-faint">
                <th className="w-10 px-2 py-3">#</th>
                <th className="px-2 py-3 text-start">کالا</th>
                <th className="w-28 px-2 py-3 text-start">واحد</th>
                <th className="w-24 px-2 py-3 text-start">مقدار</th>
                <th className="w-36 px-2 py-3 text-start">بهای واحد ({curLabel(currency)})</th>
                <th className="w-32 px-2 py-3 text-start">تخفیف ({curLabel(currency)})</th>
                <th className="w-20 px-2 py-3 text-start">مالیات٪</th>
                <th className="w-32 px-2 py-3 text-start">انقضا</th>
                <th className="w-32 px-2 py-3 text-start">ناخالص</th>
                <th className="w-32 px-2 py-3 text-start">خالص</th>
                <th className="w-28 px-2 py-3 text-start">مالیات</th>
                <th className="w-28 px-2 py-3 text-start">هزینه جانبی</th>
                <th className="w-32 px-2 py-3 text-start">بهای تمام‌شده</th>
                <th className="w-10" />
              </tr>
            </thead>
            <tbody>
              {rows.map((r, i) => {
                const m = meta[r.item_id];
                const f = fig(i);
                const opts = unitOptions(m, unitName, { id: r.unit_id, name: r.unit_name });
                return (
                  <tr key={r.key} className="border-t border-[var(--line)] align-top">
                    <td className="tabular px-2 py-2 text-center text-ink-faint">{toFaDigits(i + 1)}</td>
                    <td className="px-2 py-2">
                      <div className="flex items-center gap-1">
                        <PriceHistoryButton itemId={r.item_id} name={r.name} />
                        <span>
                          <span className="tabular text-ink-faint" dir="ltr">{r.code}</span> {r.name}
                        </span>
                      </div>
                      {r.order_line_id ? <span className="text-[11px] text-ink-faint">از سفارش</span> : null}
                    </td>
                    <td className="px-2 py-2">
                      <Select className="h-9" aria-label={`واحد ردیف ${i + 1}`} value={r.unit_id} onChange={(e) => patch(r.key, { unit_id: e.target.value })}>
                        {opts.map((u) => (
                          <option key={u.id} value={u.id}>{u.name}</option>
                        ))}
                      </Select>
                    </td>
                    <td className="px-2 py-2">
                      <Input className="h-9 text-end" dir="ltr" inputMode="decimal" aria-label={`مقدار ردیف ${i + 1}`} value={r.qty} onChange={(e) => patch(r.key, { qty: e.target.value })} />
                    </td>
                    <td className="px-2 py-2">
                      <MoneyInput compact className="h-9" aria-label={`بهای واحد ردیف ${i + 1}`} value={r.cost} onChange={(v) => patch(r.key, { cost: v })} />
                    </td>
                    <td className="px-2 py-2">
                      <MoneyInput compact className="h-9" aria-label={`تخفیف ردیف ${i + 1}`} value={r.discount} onChange={(v) => patch(r.key, { discount: v })} />
                    </td>
                    <td className="px-2 py-2">
                      {m?.vat_exempt ? (
                        <span className="py-2 text-xs text-ink-faint">معاف</span>
                      ) : (
                        <Input
                          className="h-9 text-end"
                          dir="ltr"
                          inputMode="decimal"
                          aria-label={`نرخ مالیات ردیف ${i + 1}`}
                          placeholder={toFaDigits(trimQty(m?.vat_rate ?? orgVat))}
                          value={r.vat}
                          onChange={(e) => patch(r.key, { vat: e.target.value })}
                        />
                      )}
                    </td>
                    <td className="px-2 py-2">
                      {m?.track_expiry || r.expiry ? (
                        <JalaliDateInput className="h-9" value={r.expiry} onChange={(v) => patch(r.key, { expiry: v })} invalid={m?.track_expiry && !r.expiry} />
                      ) : (
                        <span className="text-ink-faint">—</span>
                      )}
                    </td>
                    <Fig v={f?.gross} currency={currency} />
                    <Fig v={f?.net} currency={currency} />
                    <Fig v={f?.tax} currency={currency} />
                    <Fig v={f?.landed} currency={currency} />
                    <Fig v={f?.total_cost} currency={currency} strong />
                    <td className="px-1 py-2">
                      <Button
                        variant="ghost"
                        size="icon"
                        aria-label={`حذف ردیف ${i + 1}`}
                        onClick={() => {
                          setRows((rs) => rs.filter((x) => x.key !== r.key));
                          setDirty(true);
                        }}
                      >
                        <Trash2 />
                      </Button>
                    </td>
                  </tr>
                );
              })}
              {rows.length === 0 ? (
                <tr>
                  <td colSpan={14} className="py-10 text-center text-sm text-ink-faint">کالایی اضافه نشده است — بارکد را اسکن کنید</td>
                </tr>
              ) : null}
            </tbody>
          </table>
        </div>
      </Card>

      <Card className="p-4">
        <div className="mb-3 flex flex-wrap items-center gap-3">
          <h2 className="font-bold text-ink">هزینه‌های جانبی</h2>
          <Button
            variant="outline"
            size="sm"
            disabled={charges.length >= 20}
            onClick={() => {
              setCharges((cs) => [...cs, { key: crypto.randomUUID(), description: "", amount: "", payee_id: null }]);
              setDirty(true);
            }}
          >
            <Plus /> افزودن هزینه
          </Button>
          <p className="text-xs text-ink-faint">
            حمل، تخلیه و… به نسبت مبلغ خالص بین ردیف‌ها سرشکن و به بهای کالا اضافه می‌شود. طرف‌حساب خالی یعنی بدهی به همین تأمین‌کننده.
          </p>
        </div>
        {charges.length ? (
          <div className="surface flex flex-col gap-2 rounded-2xl p-3">
            {charges.map((c, i) => (
              <div key={c.key} className="grid items-center gap-2 md:grid-cols-[1fr_12rem_18rem_2.5rem]">
                <Input aria-label={`شرح هزینه ${i + 1}`} placeholder="شرح (مثلاً کرایه حمل)" maxLength={200} value={c.description} onChange={(e) => patchCharge(c.key, { description: e.target.value })} />
                <MoneyInput compact aria-label={`مبلغ هزینه ${i + 1}`} placeholder={curLabel(currency)} value={c.amount} onChange={(v) => patchCharge(c.key, { amount: v })} />
                <PartyPicker options={parties.data ?? []} value={c.payee_id} onChange={(v) => patchCharge(c.key, { payee_id: v })} ariaLabel={`طرف‌حساب هزینه ${i + 1}`} placeholder="همان تأمین‌کننده" />
                <Button
                  variant="ghost"
                  size="icon"
                  aria-label={`حذف هزینه ${i + 1}`}
                  onClick={() => {
                    setCharges((cs) => cs.filter((x) => x.key !== c.key));
                    setDirty(true);
                  }}
                >
                  <Trash2 />
                </Button>
              </div>
            ))}
          </div>
        ) : null}
      </Card>

      {server && warnings.length ? (
        <div role="alert" className="flex flex-col gap-2 rounded-2xl bg-warning/12 p-4 text-sm">
          {warnings.map((w) => (
            <p key={w} className="flex items-start gap-2">
              <AlertTriangle className="mt-0.5 size-4 shrink-0 text-warning" aria-hidden />
              <span>{toFaDigits(w)}</span>
            </p>
          ))}
        </div>
      ) : null}

      <Totals
        t={server ?? preview}
        currency={currency}
        badge={
          server ? (
            <Badge tone="success">محاسبه سرور</Badge>
          ) : (
            <Badge tone="info">پیش‌نمایش؛ مبلغ نهایی را سرور محاسبه می‌کند</Badge>
          )
        }
        note={!server && !preview.complete ? "برخی ردیف‌ها یا هزینه‌ها ناقص‌اند و در پیش‌نمایش حساب نشده‌اند." : undefined}
      />

      <div className="flex flex-wrap items-center gap-2">
        <Button onClick={() => save.mutate()} loading={save.isPending} disabled={busy || !rows.length} variant={dirty ? "primary" : "outline"}>
          <Save /> ذخیره پیش‌نویس
        </Button>
        <Button variant={dirty ? "outline" : "primary"} onClick={() => setConfirmOpen(true)} disabled={busy || !inv || dirty}>
          <CheckCheck /> قطعی کردن
        </Button>
        {inv && dirty ? <span className="text-xs text-ink-faint">برای قطعی کردن ابتدا تغییرات را ذخیره کنید.</span> : null}
        <div className="flex-1" />
        {inv ? (
          <Button
            variant="ghost"
            className="text-danger"
            onClick={() => {
              if (window.confirm("پیش‌نویس فاکتور حذف شود؟")) remove.mutate();
            }}
            loading={remove.isPending}
            disabled={busy}
          >
            <Trash2 /> حذف پیش‌نویس
          </Button>
        ) : null}
      </div>

      {inv ? (
        <Dialog open={confirmOpen} onOpenChange={setConfirmOpen}>
          <DialogContent title="قطعی کردن فاکتور خرید" description="پس از قطعی شدن، فاکتور قابل ویرایش یا حذف نیست و اصلاح فقط با برگشت از خرید ممکن است.">
            <ul className="flex list-disc flex-col gap-2 ps-5 text-sm text-ink-soft">
              <li>کالاها به بهای خالص به‌اضافه سهم هزینه‌های جانبی وارد انبار «{inv.warehouse_name}» می‌شوند و میانگین بها به‌روز می‌شود.</li>
              <li>سند حسابداری خودکار ثبت و بدهی به «{inv.supplier_name}» و طرف‌حساب‌های هزینه شناسایی می‌شود.</li>
            </ul>
            <div className="surface mt-4 grid grid-cols-2 gap-2 rounded-2xl p-3 text-sm">
              <span className="text-ink-faint">مبلغ کل فاکتور</span>
              <span className="tabular font-bold">{formatMoney(inv.grand_total, currency)}</span>
              <span className="text-ink-faint">بهای ورود به انبار</span>
              <span className="tabular">{formatMoney(inv.cost_total, currency)}</span>
            </div>
            <DialogFooter>
              <Button onClick={() => finalize.mutate()} loading={finalize.isPending}>
                <CheckCheck /> قطعی شود
              </Button>
              <Button variant="ghost" onClick={() => setConfirmOpen(false)}>
                انصراف
              </Button>
            </DialogFooter>
          </DialogContent>
        </Dialog>
      ) : null}
    </div>
  );
}

function Fig({ v, currency, strong }: { v: string | undefined; currency: DisplayCurrency; strong?: boolean }) {
  return <td className={`tabular px-2 py-3 whitespace-nowrap ${strong ? "font-semibold" : "text-ink-soft"}`}>{v ? formatMoney(v, currency) : "—"}</td>;
}

type TotalsData = {
  subtotal: string;
  discount_total: string;
  tax_total: string;
  charges_total: string;
  grand_total: string;
  cost_total: string;
};

function Totals({ t, currency, badge, note }: { t: TotalsData; currency: DisplayCurrency; badge?: React.ReactNode; note?: string }) {
  const rows: [string, string, boolean?][] = [
    ["جمع ناخالص", t.subtotal],
    ["تخفیف", t.discount_total],
    ["مالیات بر ارزش افزوده", t.tax_total],
    ["هزینه‌های جانبی", t.charges_total],
    ["مبلغ کل فاکتور", t.grand_total, true],
    ["بهای ورود به انبار", t.cost_total],
  ];
  return (
    <Card className="p-4">
      <div className="mb-3 flex flex-wrap items-center gap-2">
        <h2 className="font-bold text-ink">جمع فاکتور</h2>
        {badge}
      </div>
      <dl className="surface grid gap-x-6 gap-y-2 rounded-2xl p-4 text-sm sm:grid-cols-2 lg:grid-cols-3">
        {rows.map(([label, value, strong]) => (
          <div key={label} className="flex items-center justify-between gap-3">
            <dt className="text-ink-faint">{label}</dt>
            <dd className={`tabular ${strong ? "text-base font-extrabold text-ink" : "font-medium"}`}>{formatMoney(value, currency)}</dd>
          </div>
        ))}
      </dl>
      {note ? <p className="mt-2 text-xs text-ink-faint">{note}</p> : null}
    </Card>
  );
}

// --- price history --------------------------------------------------------------

function PriceHistoryButton({ itemId, name }: { itemId: string; name: string }) {
  const [open, setOpen] = React.useState(false);
  const currency = useCurrency();
  const history = usePriceHistory(open ? itemId : null);
  return (
    <Dialog open={open} onOpenChange={setOpen}>
      <Button variant="ghost" size="icon" className="size-8" aria-label={`سابقه قیمت خرید ${name}`} title="سابقه قیمت خرید" onClick={() => setOpen(true)}>
        <History />
      </Button>
      <DialogContent title={`سابقه خرید «${name}»`} description="آخرین خریدهای قطعی؛ بهای واحد پایه پس از تخفیف و هزینه‌های جانبی است." className="max-w-3xl">
        {history.isLoading ? (
          <Spinner />
        ) : history.isError ? (
          <ErrorBox error={history.error} />
        ) : !history.data?.length ? (
          <p className="py-8 text-center text-sm text-ink-faint">خرید قطعی‌ای برای این کالا ثبت نشده است.</p>
        ) : (
          <div className="surface overflow-x-auto rounded-2xl">
            <table className="w-full text-sm">
              <thead>
                <tr className="text-xs text-ink-faint">
                  <th className="px-2 py-2 text-start">تاریخ</th>
                  <th className="px-2 py-2 text-start">فاکتور</th>
                  <th className="px-2 py-2 text-start">تأمین‌کننده</th>
                  <th className="px-2 py-2 text-start">مقدار</th>
                  <th className="px-2 py-2 text-start">بهای واحد</th>
                  <th className="px-2 py-2 text-start">بهای واحد پایه</th>
                </tr>
              </thead>
              <tbody>
                {history.data.map((h) => (
                  <tr key={`${h.invoice_id}-${h.qty}-${h.unit_cost}`} className="border-t border-[var(--line)]">
                    <td className="tabular px-2 py-2">{isoToJalaliFa(h.document_date)}</td>
                    <td className="tabular px-2 py-2">
                      <DocLink to={`/purchasing/invoices/${h.invoice_id}`}>{h.number ? toFaDigits(h.number) : "مشاهده"}</DocLink>
                    </td>
                    <td className="px-2 py-2">{h.supplier_name}</td>
                    <td className="tabular px-2 py-2">{toFaDigits(trimQty(h.qty))} {h.unit_name}</td>
                    <td className="tabular px-2 py-2">{formatMoney(h.unit_cost, currency)}</td>
                    <td className="tabular px-2 py-2 font-semibold">{formatMoney(h.base_unit_cost, currency)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </DialogContent>
    </Dialog>
  );
}

// --- final (read-only) view -------------------------------------------------------

function InvoiceView({ inv }: { inv: Invoice }) {
  const currency = useCurrency();
  const [returnOpen, setReturnOpen] = React.useState(false);
  const isInvoice = inv.kind === "invoice";
  const returnable = isInvoice && inv.lines.some((l) => l.returnable_qty && qtyUnits(l.returnable_qty) > 0n);
  const title = isInvoice ? "فاکتور خرید" : "برگشت از خرید";

  return (
    <div className="flex flex-col gap-4">
      <div className="flex flex-wrap items-center gap-3">
        <Button variant="ghost" size="icon" asChild aria-label="بازگشت">
          <Link to="/purchasing/invoices">
            <ArrowRight />
          </Link>
        </Button>
        <h1 className="text-xl font-extrabold text-ink">
          {title} {inv.number ? `شماره ${toFaDigits(inv.number)}` : ""}
        </h1>
        <KindBadge kind={inv.kind} />
        <InvoiceStatusBadge status={inv.status} />
        {inv.voucher_id ? <DocLink to={`/accounting/vouchers/${inv.voucher_id}`}>سند حسابداری</DocLink> : null}
        {inv.order_id ? <DocLink to={`/purchasing/orders/${inv.order_id}`}>سفارش {inv.order_number ? toFaDigits(inv.order_number) : ""}</DocLink> : null}
        {inv.original_invoice_id ? (
          <DocLink to={`/purchasing/invoices/${inv.original_invoice_id}`}>فاکتور خرید اصلی {inv.original_number ? toFaDigits(inv.original_number) : ""}</DocLink>
        ) : null}
        <div className="flex-1" />
        {returnable ? (
          <Button variant="outline" onClick={() => setReturnOpen(true)}>
            <Undo2 /> برگشت از خرید
          </Button>
        ) : null}
      </div>

      <Card className="grid gap-4 p-5 text-sm sm:grid-cols-2 lg:grid-cols-4">
        <Info label="تاریخ سند" value={isoToJalaliFa(inv.document_date)} tabular />
        <Info label="تأمین‌کننده" value={inv.supplier_name} />
        <Info label="انبار" value={inv.warehouse_name} />
        <Info label="سررسید پرداخت" value={inv.due_date ? isoToJalaliFa(inv.due_date) : "—"} tabular />
        <Info label="شماره فاکتور فروشنده" value={inv.supplier_invoice_no ? toFaDigits(inv.supplier_invoice_no) : "—"} tabular />
        <Info label="تاریخ فاکتور فروشنده" value={inv.supplier_invoice_date ? isoToJalaliFa(inv.supplier_invoice_date) : "—"} tabular />
        <Info label="یادداشت" value={inv.note || "—"} className="lg:col-span-2" />
      </Card>

      <Card className="p-2">
        <div className="surface overflow-x-auto rounded-2xl">
          <table className="w-full min-w-[80rem] text-sm">
            <thead>
              <tr className="text-xs text-ink-faint">
                <th className="w-10 px-2 py-3">#</th>
                <th className="px-2 py-3 text-start">کالا</th>
                <th className="px-2 py-3 text-start">مقدار</th>
                <th className="px-2 py-3 text-start">بهای واحد</th>
                <th className="px-2 py-3 text-start">ناخالص</th>
                <th className="px-2 py-3 text-start">تخفیف</th>
                <th className="px-2 py-3 text-start">خالص</th>
                <th className="px-2 py-3 text-start">مالیات</th>
                <th className="px-2 py-3 text-start">هزینه جانبی</th>
                <th className="px-2 py-3 text-start">بهای تمام‌شده</th>
                <th className="px-2 py-3 text-start">انقضا</th>
                {isInvoice ? <th className="px-2 py-3 text-start">قابل برگشت</th> : null}
              </tr>
            </thead>
            <tbody>
              {inv.lines.map((l) => (
                <tr key={l.id} className="border-t border-[var(--line)]">
                  <td className="tabular px-2 py-2.5 text-center text-ink-faint">{toFaDigits(l.line_no)}</td>
                  <td className="px-2 py-2.5">
                    <span className="tabular text-ink-faint" dir="ltr">{l.item_code}</span> {l.item_name}
                  </td>
                  <td className="tabular px-2 py-2.5 whitespace-nowrap">{toFaDigits(trimQty(l.qty))} {l.unit_name}</td>
                  <Fig v={l.unit_cost} currency={currency} />
                  <Fig v={l.gross} currency={currency} />
                  <Fig v={l.discount} currency={currency} />
                  <Fig v={l.net} currency={currency} />
                  <td className="tabular px-2 py-3 whitespace-nowrap text-ink-soft">
                    {formatMoney(l.tax, currency)} <span className="text-xs text-ink-faint">({toFaDigits(trimQty(l.vat_rate))}٪)</span>
                  </td>
                  <Fig v={l.landed} currency={currency} />
                  <Fig v={l.total_cost} currency={currency} strong />
                  <td className="tabular px-2 py-2.5">{l.expiry_date ? isoToJalaliFa(l.expiry_date) : "—"}</td>
                  {isInvoice ? <td className="tabular px-2 py-2.5">{toFaDigits(trimQty(l.returnable_qty))}</td> : null}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </Card>

      {inv.charges.length ? (
        <Card className="p-4">
          <h2 className="mb-3 font-bold text-ink">هزینه‌های جانبی</h2>
          <ul className="surface flex flex-col divide-y divide-[var(--line)] rounded-2xl text-sm">
            {inv.charges.map((c) => (
              <li key={c.id} className="flex flex-wrap items-center justify-between gap-2 px-4 py-2.5">
                <span>{c.description}</span>
                <span className="text-ink-faint">{c.payee_name || inv.supplier_name}</span>
                <span className="tabular font-medium">{formatMoney(c.amount, currency)}</span>
              </li>
            ))}
          </ul>
        </Card>
      ) : null}

      <Totals t={inv} currency={currency} />

      {returnable ? <ReturnDialog inv={inv} open={returnOpen} onOpenChange={setReturnOpen} /> : null}
    </div>
  );
}

function Info({ label, value, tabular, className }: { label: string; value: string; tabular?: boolean; className?: string }) {
  return (
    <div className={className}>
      <p className="text-xs text-ink-faint">{label}</p>
      <p className={`mt-1 ${tabular ? "tabular" : ""}`}>{value}</p>
    </div>
  );
}

// --- return ---------------------------------------------------------------------

function ReturnDialog({ inv, open, onOpenChange }: { inv: Invoice; open: boolean; onOpenChange: (v: boolean) => void }) {
  const qc = useQueryClient();
  const navigate = useNavigate();
  const [qty, setQty] = React.useState<Record<string, string>>({});
  const [date, setDate] = React.useState<string | null>(todayIso());
  const [reason, setReason] = React.useState("");
  const keyRef = React.useRef(newIdempotencyKey());
  const lines = inv.lines.filter((l) => l.returnable_qty && qtyUnits(l.returnable_qty) > 0n);

  const errorOf = (lineId: string, max: string): string | null => {
    const v = toEnDigits(qty[lineId] ?? "").trim();
    if (!v) return null;
    const u = parseQty(v);
    if (u === null) return "مقدار نامعتبر";
    if (u > qtyUnits(max)) return "بیش از مقدار قابل برگشت";
    return null;
  };

  const submit = useMutation({
    mutationFn: () => {
      if (!date) throw new ApiError(0, "date", "تاریخ برگشت نامعتبر است");
      if (reason.trim().length < 2) throw new ApiError(0, "reason", "علت برگشت را بنویسید");
      const picked = lines.filter((l) => toEnDigits(qty[l.id] ?? "").trim());
      if (!picked.length) throw new ApiError(0, "lines", "مقدار حداقل یک ردیف را وارد کنید");
      for (const l of picked) {
        const err = errorOf(l.id, l.returnable_qty!);
        if (err) throw new ApiError(0, "qty", `ردیف ${toFaDigits(l.line_no)}: ${err}`);
      }
      const body: ReturnIn = {
        document_date: date,
        reason: reason.trim(),
        lines: picked.map((l) => ({ original_line_id: l.id, qty: toEnDigits(qty[l.id]).trim() })),
      };
      return api.post<Invoice>(`/purchasing/invoices/${inv.id}/returns`, body, { idempotencyKey: keyRef.current });
    },
    onSuccess: (d) => {
      qc.setQueryData(["purchasing", "invoice", d.id], d);
      qc.invalidateQueries({ queryKey: ["purchasing"], predicate: (q) => !(q.queryKey[1] === "invoice" && q.queryKey[2] === d.id) });
      qc.invalidateQueries({ queryKey: ["inventory"] });
      qc.invalidateQueries({ queryKey: ["accounting"] });
      qc.invalidateQueries({ queryKey: ["parties"] });
      toast.success(`برگشت از خرید شماره ${toFaDigits(d.number ?? 0)} ثبت شد`);
      onOpenChange(false);
      navigate(`/purchasing/invoices/${d.id}`);
    },
    onError: (e) => {
      if (rejected(e)) keyRef.current = newIdempotencyKey();
      onError(e);
    },
  });

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent
        title={`برگشت از خرید — فاکتور ${toFaDigits(inv.number ?? 0)}`}
        description="کالا به همان بهایی که وارد انبار شده خارج می‌شود و بدهی تأمین‌کننده و مالیات به نسبت کاهش می‌یابد. سهم هزینه‌های جانبی که بازپرداخت نمی‌شود به‌عنوان تفاوت بها ثبت می‌شود. برگشت بلافاصله قطعی است."
        className="max-w-2xl"
      >
        <div className="grid gap-3 sm:grid-cols-[10rem_1fr]">
          <Field label="تاریخ برگشت">
            <JalaliDateInput value={date} onChange={setDate} />
          </Field>
          <Field label="علت برگشت">
            <Input maxLength={500} value={reason} onChange={(e) => setReason(e.target.value)} aria-invalid={reason !== "" && reason.trim().length < 2 ? true : undefined} />
          </Field>
        </div>
        <div className="surface mt-4 overflow-x-auto rounded-2xl">
          <table className="w-full text-sm">
            <thead>
              <tr className="text-xs text-ink-faint">
                <th className="px-2 py-2 text-start">کالا</th>
                <th className="px-2 py-2 text-start">قابل برگشت</th>
                <th className="w-32 px-2 py-2 text-start">مقدار برگشتی</th>
              </tr>
            </thead>
            <tbody>
              {lines.map((l) => {
                const err = errorOf(l.id, l.returnable_qty!);
                return (
                  <tr key={l.id} className="border-t border-[var(--line)] align-top">
                    <td className="px-2 py-2">{l.item_name}</td>
                    <td className="tabular px-2 py-2 whitespace-nowrap">{toFaDigits(trimQty(l.returnable_qty))} {l.unit_name}</td>
                    <td className="px-2 py-2">
                      <Input
                        className="h-9 text-end"
                        dir="ltr"
                        inputMode="decimal"
                        aria-label={`مقدار برگشتی ${l.item_name}`}
                        aria-invalid={err ? true : undefined}
                        value={qty[l.id] ?? ""}
                        onChange={(e) => setQty((q) => ({ ...q, [l.id]: e.target.value }))}
                      />
                      {err ? <p className="mt-1 text-xs text-danger">{err}</p> : null}
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
        <DialogFooter>
          <Button onClick={() => submit.mutate()} loading={submit.isPending}>
            <Undo2 /> ثبت برگشت
          </Button>
          <Button variant="ghost" onClick={() => onOpenChange(false)}>
            انصراف
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
