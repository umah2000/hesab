import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { ArrowRight, Ban, CheckCheck, FileInput, Lock, Save, Trash2 } from "lucide-react";
import * as React from "react";
import { Link, useNavigate, useParams } from "react-router";
import { toast } from "sonner";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { Badge, ErrorBox, Spinner } from "@/components/ui/feedback";
import { Field, Input, Select } from "@/components/ui/form-controls";
import { useCurrency } from "@/features/accounting/api";
import { JalaliDateInput, MoneyInput } from "@/features/accounting/inputs";
import { trimQty, useUnits, useWarehouses } from "@/features/inventory/api";
import { ItemSearch, type Picked } from "@/features/inventory/ItemSearch";
import { usePartyOptions } from "@/features/parties/api";
import { ApiError, api, newIdempotencyKey } from "@/lib/api";
import { formatMoney, toEnDigits, toFaDigits } from "@/lib/format";
import { isoToJalaliFa, todayIso } from "@/lib/jalali";
import { inputToRials, rialsToInput } from "@/lib/money";
import { addQty, qtyUnits } from "@/lib/qty";
import type { Order, OrderIn, OrderLine } from "./api";
import { parseQty, previewInvoice } from "./preview";
import { fetchItem, onError, OrderStatusBadge, PartyPicker, rejected, unitOptions, useItemsMeta } from "./shared";

export function PurchaseOrderPage() {
  const { id } = useParams();
  const isNew = !id || id === "new";
  const order = useQuery({
    queryKey: ["purchasing", "order", id],
    queryFn: () => api.get<Order>(`/purchasing/orders/${id}`),
    enabled: !isNew,
  });
  if (!isNew && order.isLoading) return <Spinner />;
  if (!isNew && order.isError) return <ErrorBox error={order.error} />;
  return <OrderForm key={order.data?.row_version ?? "new"} order={order.data} />;
}

type Row = {
  key: string;
  item_id: string;
  code: string;
  name: string;
  unit_id: string;
  unit_name: string;
  qty: string;
  cost: string; // display currency, optional
};

function ReceivedBadge({ line }: { line: OrderLine }) {
  const got = qtyUnits(line.received_base_qty);
  if (got <= 0n) return <Badge tone="neutral">دریافت‌نشده</Badge>;
  if (got >= qtyUnits(line.base_qty)) return <Badge tone="success">کامل</Badge>;
  return <Badge tone="warning">ناقص</Badge>;
}

function OrderForm({ order }: { order?: Order }) {
  const qc = useQueryClient();
  const navigate = useNavigate();
  const currency = useCurrency();
  const units = useUnits();
  const warehouses = useWarehouses();
  const suppliers = usePartyOptions("supplier");
  const readOnly = !!order && order.status !== "draft";
  const [dirty, setDirty] = React.useState(!order);
  const [warehouse, setWarehouse] = React.useState(order?.warehouse_id ?? "");
  const [supplier, setSupplier] = React.useState<string | null>(order?.supplier_id ?? null);
  const [date, setDate] = React.useState<string | null>(order?.order_date ?? todayIso());
  const [expected, setExpected] = React.useState<string | null>(order?.expected_date ?? null);
  const [note, setNote] = React.useState(order?.note ?? "");
  const [rows, setRows] = React.useState<Row[]>(() =>
    (order?.lines ?? []).map((l) => ({
      key: l.id,
      item_id: l.item_id,
      code: l.item_code,
      name: l.item_name,
      unit_id: l.unit_id,
      unit_name: l.unit_name,
      qty: trimQty(l.qty),
      cost: l.unit_cost ? rialsToInput(l.unit_cost, currency) : "",
    })),
  );
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

  React.useEffect(() => {
    if (!readOnly && !warehouse && warehouses.data?.length) setWarehouse(warehouses.data.find((w) => w.is_active)?.id ?? warehouses.data[0].id);
  }, [warehouses.data, warehouse, readOnly]);

  const addItem = async (p: Picked) => {
    const existing = rows.find((r) => r.item_id === p.item_id && (!p.unit_id || r.unit_id === p.unit_id));
    if (existing) {
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
      },
    ]);
    setDirty(true);
  };

  const estimate = previewInvoice(
    rows
      .filter((r) => r.cost.trim())
      .map((r) => ({ qty: toEnDigits(r.qty), unitCost: inputToRials(r.cost, currency) ?? "x", discount: "0", vatRate: "0" })),
    [],
  );

  const payload = (): OrderIn => {
    if (!warehouse) throw new ApiError(0, "warehouse", "انبار را انتخاب کنید");
    if (!supplier) throw new ApiError(0, "supplier", "تأمین‌کننده را انتخاب کنید");
    if (!date) throw new ApiError(0, "date", "تاریخ سفارش نامعتبر است");
    if (!rows.length) throw new ApiError(0, "lines", "حداقل یک کالا اضافه کنید");
    return {
      warehouse_id: warehouse,
      supplier_id: supplier,
      order_date: date,
      expected_date: expected,
      note: note.trim() || null,
      lines: rows.map((r, i) => {
        const n = toFaDigits(i + 1);
        const qty = toEnDigits(r.qty).trim();
        if (parseQty(qty) === null) throw new ApiError(0, "qty", `ردیف ${n}: مقدار نامعتبر است`);
        const cost = r.cost.trim() ? inputToRials(r.cost, currency) : null;
        if (r.cost.trim() && cost === null) throw new ApiError(0, "cost", `ردیف ${n}: بها نامعتبر است`);
        return { item_id: r.item_id, unit_id: r.unit_id, qty, unit_cost: cost };
      }),
    };
  };

  const done = (d: Order) => {
    qc.setQueryData(["purchasing", "order", d.id], d);
    qc.invalidateQueries({ queryKey: ["purchasing"], predicate: (q) => !(q.queryKey[1] === "order" && q.queryKey[2] === d.id) });
  };

  const save = useMutation({
    mutationFn: () => {
      const body = payload();
      return order
        ? api.put<Order>(`/purchasing/orders/${order.id}`, body, order.row_version)
        : api.post<Order>("/purchasing/orders", body, { idempotencyKey: keyRef.current });
    },
    onSuccess: (d) => {
      done(d);
      toast.success("سفارش ذخیره شد");
      if (!order) navigate(`/purchasing/orders/${d.id}`, { replace: true });
    },
    onError: (e) => {
      if (rejected(e)) keyRef.current = newIdempotencyKey();
      onError(e);
    },
  });
  const action = useMutation({
    mutationFn: (a: "approve" | "cancel" | "close") => api.post<Order>(`/purchasing/orders/${order!.id}/${a}`, undefined, { version: order!.row_version }),
    onSuccess: (d, a) => {
      done(d);
      toast.success(a === "approve" ? `سفارش شماره ${toFaDigits(d.number ?? 0)} تأیید شد` : a === "cancel" ? "سفارش لغو شد" : "سفارش بسته شد");
    },
    onError,
  });
  const busy = save.isPending || action.isPending;
  const supplierName = order?.supplier_name;

  return (
    <div className="flex flex-col gap-4">
      <div className="flex flex-wrap items-center gap-3">
        <Button variant="ghost" size="icon" asChild aria-label="بازگشت">
          <Link to="/purchasing/orders">
            <ArrowRight />
          </Link>
        </Button>
        <h1 className="text-xl font-extrabold text-ink">
          {order ? "سفارش خرید" : "سفارش خرید جدید"} {order?.number ? `شماره ${toFaDigits(order.number)}` : ""}
        </h1>
        <OrderStatusBadge status={order?.status ?? "draft"} />
        <div className="flex-1" />
        {order?.status === "approved" ? (
          <Button asChild>
            <Link to={`/purchasing/invoices/new?order=${order.id}`}>
              <FileInput /> ثبت فاکتور دریافت
            </Link>
          </Button>
        ) : null}
      </div>

      <Card className="grid gap-4 p-5 md:grid-cols-3 xl:grid-cols-5">
        <Field label="تاریخ سفارش">
          {readOnly ? <p className="tabular py-2">{isoToJalaliFa(order!.order_date)}</p> : <JalaliDateInput value={date} onChange={touch(setDate)} />}
        </Field>
        <Field label="تاریخ تحویل مورد انتظار">
          {readOnly ? (
            <p className="tabular py-2">{order!.expected_date ? isoToJalaliFa(order!.expected_date) : "—"}</p>
          ) : (
            <JalaliDateInput value={expected} onChange={touch(setExpected)} />
          )}
        </Field>
        <Field label="انبار">
          {readOnly ? (
            <p className="py-2">{order!.warehouse_name}</p>
          ) : (
            <Select value={warehouse} onChange={(e) => touch(setWarehouse)(e.target.value)}>
              {warehouses.data?.filter((w) => w.is_active || w.id === warehouse).map((w) => (
                <option key={w.id} value={w.id}>{w.name}</option>
              ))}
            </Select>
          )}
        </Field>
        <Field label="تأمین‌کننده" className="xl:col-span-2">
          <PartyPicker options={suppliers.data ?? []} value={supplier} onChange={touch(setSupplier)} ariaLabel="تأمین‌کننده" placeholder="کد یا نام تأمین‌کننده" disabled={readOnly} fallbackName={supplierName} />
        </Field>
        <Field label="یادداشت" className="md:col-span-3 xl:col-span-5">
          {readOnly ? <p className="py-2">{order!.note || "—"}</p> : <Input maxLength={500} value={note} onChange={(e) => touch(setNote)(e.target.value)} />}
        </Field>
      </Card>

      {!readOnly ? (
        <Card className="p-4">
          <ItemSearch ref={searchRef} autoFocus onPick={(p) => void addItem(p).then(() => searchRef.current?.focus()).catch(onError)} />
          <p className="mt-2 text-xs text-ink-faint">بهای مورد انتظار اختیاری است و فقط برای برآورد مبلغ سفارش به کار می‌رود.</p>
        </Card>
      ) : null}

      <Card className="p-2">
        <div className="surface overflow-x-auto rounded-2xl">
          <table className="w-full min-w-[52rem] text-sm">
            <thead>
              <tr className="text-xs text-ink-faint">
                <th className="w-10 px-2 py-3">#</th>
                <th className="px-2 py-3 text-start">کالا</th>
                <th className="w-32 px-2 py-3 text-start">واحد</th>
                <th className="w-28 px-2 py-3 text-start">مقدار</th>
                <th className="w-40 px-2 py-3 text-start">بهای مورد انتظار ({currency === "IRT" ? "تومان" : "ریال"})</th>
                {order ? <th className="w-48 px-2 py-3 text-start">دریافت‌شده / سفارش (واحد پایه)</th> : null}
                {!readOnly ? <th className="w-10" /> : null}
              </tr>
            </thead>
            <tbody>
              {readOnly
                ? order!.lines.map((l) => (
                    <tr key={l.id} className="border-t border-[var(--line)]">
                      <td className="tabular px-2 py-2.5 text-center text-ink-faint">{toFaDigits(l.line_no)}</td>
                      <td className="px-2 py-2.5">
                        <span className="tabular text-ink-faint" dir="ltr">{l.item_code}</span> {l.item_name}
                      </td>
                      <td className="px-2 py-2.5">{l.unit_name}</td>
                      <td className="tabular px-2 py-2.5">{toFaDigits(trimQty(l.qty))}</td>
                      <td className="tabular px-2 py-2.5">{l.unit_cost ? formatMoney(l.unit_cost, currency) : "—"}</td>
                      <td className="px-2 py-2.5">
                        <span className="tabular">
                          {toFaDigits(trimQty(l.received_base_qty))} / {toFaDigits(trimQty(l.base_qty))} {meta[l.item_id]?.base_unit_name ?? ""}
                        </span>{" "}
                        <ReceivedBadge line={l} />
                      </td>
                    </tr>
                  ))
                : rows.map((r, i) => {
                    const line = order?.lines.find((l) => l.id === r.key);
                    return (
                      <tr key={r.key} className="border-t border-[var(--line)]">
                        <td className="tabular px-2 py-2 text-center text-ink-faint">{toFaDigits(i + 1)}</td>
                        <td className="px-2 py-2">
                          <span className="tabular text-ink-faint" dir="ltr">{r.code}</span> {r.name}
                        </td>
                        <td className="px-2 py-2">
                          <Select className="h-9" aria-label={`واحد ردیف ${i + 1}`} value={r.unit_id} onChange={(e) => patch(r.key, { unit_id: e.target.value })}>
                            {unitOptions(meta[r.item_id], unitName, { id: r.unit_id, name: r.unit_name }).map((u) => (
                              <option key={u.id} value={u.id}>{u.name}</option>
                            ))}
                          </Select>
                        </td>
                        <td className="px-2 py-2">
                          <Input className="h-9 text-end" dir="ltr" inputMode="decimal" aria-label={`مقدار ردیف ${i + 1}`} value={r.qty} onChange={(e) => patch(r.key, { qty: e.target.value })} />
                        </td>
                        <td className="px-2 py-2">
                          <MoneyInput compact className="h-9" aria-label={`بهای ردیف ${i + 1}`} value={r.cost} onChange={(v) => patch(r.key, { cost: v })} />
                        </td>
                        {order ? (
                          <td className="tabular px-2 py-2 text-ink-faint">
                            {line ? `${toFaDigits(trimQty(line.received_base_qty))} / ${toFaDigits(trimQty(line.base_qty))}` : "—"}
                          </td>
                        ) : null}
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
              {!readOnly && rows.length === 0 ? (
                <tr>
                  <td colSpan={7} className="py-10 text-center text-sm text-ink-faint">کالایی اضافه نشده است — بارکد را اسکن کنید</td>
                </tr>
              ) : null}
            </tbody>
            <tfoot>
              <tr className="border-t-2 border-[var(--line)] bg-[var(--surface-muted)] font-bold">
                <td colSpan={4} className="px-2 py-3 text-end">
                  برآورد مبلغ سفارش{" "}
                  {order && !dirty ? null : <span className="text-xs font-normal text-ink-faint">(پیش‌نمایش؛ مبلغ نهایی را سرور محاسبه می‌کند)</span>}
                </td>
                <td colSpan={3} className="tabular px-2 py-3">
                  {formatMoney(order && !dirty ? order.estimated_total : estimate.subtotal, currency)}
                </td>
              </tr>
            </tfoot>
          </table>
        </div>
      </Card>

      <div className="flex flex-wrap items-center gap-2">
        {!readOnly ? (
          <>
            <Button onClick={() => save.mutate()} loading={save.isPending} disabled={busy || !rows.length} variant={dirty ? "primary" : "outline"}>
              <Save /> ذخیره پیش‌نویس
            </Button>
            <Button variant={dirty ? "outline" : "primary"} onClick={() => action.mutate("approve")} loading={action.isPending && action.variables === "approve"} disabled={busy || !order || dirty}>
              <CheckCheck /> تأیید سفارش
            </Button>
            {order && dirty ? <span className="text-xs text-ink-faint">برای تأیید ابتدا تغییرات را ذخیره کنید.</span> : null}
          </>
        ) : null}
        <div className="flex-1" />
        {order?.status === "approved" ? (
          <Button
            variant="outline"
            onClick={() => {
              if (window.confirm("سفارش با دریافت ناقص بسته شود؟ پس از بستن، دریافت دیگری روی آن ثبت نمی‌شود.")) action.mutate("close");
            }}
            loading={action.isPending && action.variables === "close"}
            disabled={busy}
          >
            <Lock /> بستن سفارش
          </Button>
        ) : null}
        {order && (order.status === "draft" || order.status === "approved") ? (
          <Button
            variant="ghost"
            className="text-danger"
            onClick={() => {
              if (window.confirm("سفارش لغو شود؟ سفارشی که بخشی از آن دریافت شده لغو نمی‌شود؛ آن را ببندید.")) action.mutate("cancel");
            }}
            loading={action.isPending && action.variables === "cancel"}
            disabled={busy}
          >
            <Ban /> لغو سفارش
          </Button>
        ) : null}
      </div>
    </div>
  );
}
