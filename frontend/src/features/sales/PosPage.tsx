import { keepPreviousData, useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { ArrowRight, CheckCircle2, Minus, MonitorSmartphone, PauseCircle, Plus, Printer, ShoppingCart, Trash2 } from "lucide-react";
import * as React from "react";
import { Link } from "react-router";
import { toast } from "sonner";
import { Logo } from "@/components/layout/Logo";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { Badge, EmptyState, ErrorBox, Spinner } from "@/components/ui/feedback";
import { Field } from "@/components/ui/form-controls";
import { MoneyInput } from "@/features/accounting/inputs";
import { useMe } from "@/features/auth/auth";
import { trimQty } from "@/features/inventory/api";
import { ItemSearch, type Picked } from "@/features/inventory/ItemSearch";
import type { Branch, CashRegister } from "@/features/settings/types";
import { ApiError, api, newIdempotencyKey } from "@/lib/api";
import { type DisplayCurrency, formatLongDate, formatMoney, formatTime, toFaDigits } from "@/lib/format";
import { inputToRials, sumRials } from "@/lib/money";
import { addQty, fromQtyUnits, qtyUnits } from "@/lib/qty";
import { cn } from "@/lib/utils";
import { type ApprovalAction, ApprovalDialog } from "./ApprovalDialog";
import { type CartLine, type Invoice, type Quote, type RegisterState, storedRegister, storeRegister } from "./api";
import { type PayMode, PaymentDialog, type PayResult } from "./PaymentDialog";
import { CloseShiftDialog, DiscountDialog, HeldDialog, HoldDialog, QtyDialog } from "./PosDialogs";
import { printReceipt, Receipt } from "./Receipt";

// --- shell -------------------------------------------------------------------

function useClock() {
  const [now, setNow] = React.useState(() => new Date());
  React.useEffect(() => {
    const t = setInterval(() => setNow(new Date()), 30_000);
    return () => clearInterval(t);
  }, []);
  return now;
}

function StatusChip({ ok, label }: { ok: boolean; label: string }) {
  return (
    <span className={cn("inline-flex items-center gap-1.5 rounded-full px-3 py-1 text-xs font-medium", ok ? "bg-success/10 text-success" : "bg-danger/10 text-danger")}>
      <span className={cn("size-2 rounded-full", ok ? "bg-success" : "bg-danger")} aria-hidden />
      {label}
    </span>
  );
}

function PosFrame({ state, children }: { state?: RegisterState; children: React.ReactNode }) {
  const me = useMe();
  const now = useClock();
  const health = useQuery({
    queryKey: ["system", "health"],
    queryFn: () => api.get<{ status: string }>("/system/health"),
    refetchInterval: 15_000,
    retry: false,
  });
  const online = health.isSuccess && !health.isError;
  return (
    <div className="flex h-dvh flex-col gap-3 p-3" data-pos>
      <header className="glass no-print flex flex-wrap items-center gap-3 rounded-2xl px-4 py-2.5">
        <Logo size={36} />
        <div className="min-w-0">
          <div className="font-extrabold text-ink">{state ? state.register_name : "صندوق فروش"}</div>
          <div className="text-xs text-ink-faint">{state ? `${state.branch_name} · ${state.organization_name}` : "انتخاب صندوق"}</div>
        </div>
        {me.data ? <Badge tone="neutral" icon={false}>صندوق‌دار: {me.data.full_name || me.data.username}</Badge> : null}
        <div className="flex-1" />
        <StatusChip ok={online} label={online ? "متصل به سرور" : "قطع ارتباط با سرور"} />
        {state ? (
          <StatusChip
            ok
            label={state.terminal ? `${state.terminal.label}${state.terminal.verified ? "" : " (آزمایش‌نشده)"}` : "کارت‌خوان: ثبت دستی شماره پیگیری"}
          />
        ) : null}
        <span className="rounded-full bg-black/5 px-3 py-1 text-xs text-ink-soft dark:bg-white/10">
          {formatLongDate(now)} · {formatTime(now)}
        </span>
        <Button asChild variant="ghost" size="sm">
          <Link to="/">
            <ArrowRight /> پیشخوان
          </Link>
        </Button>
      </header>
      {children}
    </div>
  );
}

// --- register picker / open shift -------------------------------------------

function RegisterPicker({ onPick }: { onPick: (id: string) => void }) {
  const branches = useQuery({ queryKey: ["branches"], queryFn: () => api.get<Branch[]>("/organization/branches") });
  const registers = useQuery({
    queryKey: ["registers", branches.data?.map((b) => b.id).join()],
    enabled: !!branches.data,
    queryFn: async () => {
      const all = await Promise.all((branches.data ?? []).map((b) => api.get<CashRegister[]>(`/organization/branches/${b.id}/cash-registers`)));
      return all.flat().filter((r) => r.is_active);
    },
  });
  return (
    <Card className="mx-auto mt-10 w-full max-w-xl p-6">
      <h1 className="mb-1 text-lg font-bold text-ink">این رایانه کدام صندوق است؟</h1>
      <p className="mb-4 text-sm text-ink-faint">این انتخاب روی همین مرورگر ذخیره می‌شود و فقط یک بار لازم است.</p>
      {registers.isLoading || branches.isLoading ? (
        <Spinner />
      ) : !registers.data?.length ? (
        <EmptyState icon={MonitorSmartphone} title="صندوقی تعریف نشده" description="مدیر سیستم ابتدا در «تنظیمات» صندوق تعریف کند." />
      ) : (
        <div className="grid grid-cols-2 gap-3">
          {registers.data.map((r) => (
            <button
              key={r.id}
              type="button"
              onClick={() => onPick(r.id)}
              className="surface rounded-2xl p-4 text-start transition hover:ring-2 hover:ring-brand-400 focus:ring-2 focus:ring-brand-500 focus:outline-none"
            >
              <div className="font-bold text-ink">{r.name}</div>
              <div className="text-xs text-ink-faint">{branches.data?.find((b) => b.id === r.branch_id)?.name}</div>
            </button>
          ))}
        </div>
      )}
    </Card>
  );
}

function OpenShift({ state, onChangeRegister }: { state: RegisterState; onChangeRegister: () => void }) {
  const qc = useQueryClient();
  const [cash, setCash] = React.useState("");
  const keyRef = React.useRef(newIdempotencyKey());
  const canOpen = state.permissions.includes("sales.shift.open");
  const open = useMutation({
    mutationFn: () => {
      const rials = inputToRials(cash || "0", state.display_currency);
      if (rials === null) throw new ApiError(0, "invalid", "مبلغ نامعتبر است");
      return api.post("/sales/shifts/open", { cash_register_id: state.cash_register_id, opening_cash: rials }, { idempotencyKey: keyRef.current });
    },
    onSuccess: () => {
      keyRef.current = newIdempotencyKey();
      qc.invalidateQueries({ queryKey: ["sales", "register"] });
      toast.success("شیفت باز شد");
    },
    onError: (e) => toast.error(e instanceof ApiError ? e.message : "خطا"),
  });
  return (
    <Card className="mx-auto mt-10 w-full max-w-md p-6">
      <h1 className="mb-1 text-lg font-bold text-ink">شروع شیفت — {state.register_name}</h1>
      {state.other_shift_user ? (
        <p className="mb-4 rounded-xl bg-warning/15 p-3 text-sm text-ink">
          شیفت «{state.other_shift_user}» روی این صندوق باز است. تا آن شیفت بسته نشود، شیفت جدید باز نمی‌شود.
        </p>
      ) : (
        <p className="mb-4 text-sm text-ink-faint">موجودی نقد داخل کشو در شروع شیفت را وارد کنید.</p>
      )}
      <form
        className="flex flex-col gap-4"
        onSubmit={(e) => {
          e.preventDefault();
          open.mutate();
        }}
      >
        <Field label="موجودی اول شیفت">
          <MoneyInput autoFocus value={cash} onChange={setCash} className="h-12 text-xl" disabled={!canOpen || !!state.other_shift_user} />
        </Field>
        <Button type="submit" size="lg" loading={open.isPending} disabled={!canOpen || !!state.other_shift_user}>
          باز کردن شیفت
        </Button>
        {!canOpen ? <p className="text-sm text-danger">مجوز باز کردن شیفت را ندارید.</p> : null}
        <Button type="button" variant="ghost" size="sm" onClick={onChangeRegister}>
          تغییر صندوق این رایانه
        </Button>
      </form>
    </Card>
  );
}

export function PosPage() {
  const [registerId, setRegisterId] = React.useState(storedRegister);
  const state = useQuery({
    queryKey: ["sales", "register", registerId],
    queryFn: () => api.get<RegisterState>(`/sales/registers/${registerId}/state`),
    enabled: !!registerId,
    retry: false,
  });
  const choose = (id: string | null) => {
    storeRegister(id);
    setRegisterId(id);
  };
  React.useEffect(() => {
    if (state.error instanceof ApiError && state.error.status === 404) choose(null);
  }, [state.error]);

  if (!registerId) {
    return (
      <PosFrame>
        <RegisterPicker onPick={choose} />
      </PosFrame>
    );
  }
  if (state.isLoading) return <PosFrame><Spinner /></PosFrame>;
  if (state.isError || !state.data) return <PosFrame><ErrorBox error={state.error} /></PosFrame>;
  return (
    <PosFrame state={state.data}>
      {state.data.shift ? <Workspace state={state.data} /> : <OpenShift state={state.data} onChangeRegister={() => choose(null)} />}
    </PosFrame>
  );
}

// --- workspace ----------------------------------------------------------------

type Cart = { id: string; lines: CartLine[]; discount: string };
const newCart = (): Cart => ({ id: crypto.randomUUID(), lines: [], discount: "0" });

function useCart(registerId: string) {
  const key = `nc.cart.${registerId}`;
  const [cart, setCart] = React.useState<Cart>(() => {
    try {
      const raw = localStorage.getItem(key);
      if (raw) return JSON.parse(raw) as Cart;
    } catch {
      /* ignore */
    }
    return newCart();
  });
  React.useEffect(() => {
    try {
      // Survives a refresh or a browser crash mid-sale (the server never saw this cart).
      localStorage.setItem(key, JSON.stringify(cart));
    } catch {
      /* private mode */
    }
  }, [key, cart]);
  return [cart, setCart] as const;
}

type DialogState =
  | null
  | { kind: "pay"; mode: PayMode }
  | { kind: "qty"; index: number }
  | { kind: "discount" }
  | { kind: "hold" }
  | { kind: "held" }
  | { kind: "close" }
  | { kind: "approval"; action: ApprovalAction; detail: string; then: (approvalId: string) => void };

const PAY_KEYS: Record<string, PayMode> = { F8: "cash", F9: "card", F10: "split", F11: "credit" };

function Workspace({ state }: { state: RegisterState }) {
  const qc = useQueryClient();
  const currency: DisplayCurrency = state.display_currency;
  const can = (p: string) => state.permissions.includes(p);
  const reg = state.cash_register_id;
  const [cart, setCart] = useCart(reg);
  const [selected, setSelected] = React.useState(0);
  const [dialog, setDialog] = React.useState<DialogState>(null);
  const [lastAdded, setLastAdded] = React.useState<string | null>(null);
  const [lastInvoice, setLastInvoice] = React.useState<Invoice | null>(null);
  const [discountApproval, setDiscountApproval] = React.useState<string | null>(null);
  const [autoPrint, setAutoPrint] = React.useState(() => localStorage.getItem("nc.autoprint") !== "0");
  const scanRef = React.useRef<HTMLInputElement>(null);
  const payKey = React.useRef(newIdempotencyKey());
  const money = (v: string) => formatMoney(v, currency);

  const payload = {
    cash_register_id: reg,
    lines: cart.lines.map((l) => ({
      item_id: l.item_id,
      unit_id: l.unit_id ?? null,
      qty: l.qty,
      barcode: l.barcode ?? null,
      manual_discount: l.manual_discount ?? "0",
    })),
    discount: cart.discount,
  };
  const quote = useQuery({
    queryKey: ["sales", "quote", JSON.stringify(payload)],
    queryFn: () => api.post<Quote>("/sales/quote", payload),
    enabled: cart.lines.length > 0,
    placeholderData: keepPreviousData,
    retry: false,
    staleTime: 60_000,
  });
  const q = cart.lines.length && quote.data && quote.data.lines.length === cart.lines.length ? quote.data : null;

  // A line the server cannot price (no price, inactive…) was never part of a sale: drop it.
  React.useEffect(() => {
    if (!(quote.error instanceof ApiError) || !lastAdded) return;
    const e = quote.error;
    if (["no_price", "item_inactive", "bad_unit", "fraction_qty", "label_mismatch"].includes(e.code)) {
      toast.error(e.message);
      setCart((c) => ({ ...c, lines: c.lines.filter((l) => l.key !== lastAdded) }));
      setLastAdded(null);
    }
  }, [quote.error, lastAdded, setCart]);

  const focusScan = () => setTimeout(() => scanRef.current?.focus(), 0);
  React.useEffect(() => {
    if (!dialog) focusScan();
  }, [dialog]);

  const add = (p: Picked) => {
    const fixed = p.source === "scale_weight" || p.source === "scale_price";
    setLastInvoice(null);
    setCart((c) => {
      const idx = fixed ? -1 : c.lines.findIndex((l) => !l.fixed && l.item_id === p.item_id && (l.unit_id ?? null) === (p.unit_id ?? null) && !l.manual_discount);
      if (idx >= 0) {
        const lines = c.lines.map((l, i) => (i === idx ? { ...l, qty: addQty(l.qty, p.qty ?? "1") } : l));
        setSelected(idx);
        setLastAdded(null);
        return { ...c, lines };
      }
      const line: CartLine = {
        key: crypto.randomUUID(),
        item_id: p.item_id,
        code: p.code,
        name: p.name,
        unit_id: p.unit_id,
        qty: p.qty ?? "1",
        barcode: fixed ? p.barcode : undefined,
        fixed,
      };
      setSelected(c.lines.length);
      setLastAdded(line.key);
      return { ...c, lines: [...c.lines, line] };
    });
    toast.success(`افزوده شد: ${p.name}`, { duration: 1200 });
  };

  /** Removing scanned goods is audited; a cashier needs a supervisor's approval. */
  const removeScanned = (index: number, removeQty: string, apply: () => void) => {
    const line = cart.lines[index];
    const ql = q?.lines[index];
    const lineTotal = ql ? ql.line_total : "0";
    const record = (approvalId?: string) =>
      api
        .post("/sales/line-removals", {
          cash_register_id: reg,
          item_id: line.item_id,
          qty: removeQty,
          line_total: lineTotal,
          approval_id: approvalId ?? null,
        })
        .then(apply)
        .catch((e) => toast.error(e instanceof ApiError ? e.message : "خطا"));
    if (can("sales.invoice.line_delete_after_scan")) void record();
    else
      setDialog({
        kind: "approval",
        action: "line_delete",
        detail: `${line.name} — ${toFaDigits(trimQty(removeQty))} ${ql?.unit_name ?? ""}`,
        then: (id) => void record(id),
      });
  };

  const deleteLine = (index: number) => {
    const line = cart.lines[index];
    if (!line) return;
    removeScanned(index, line.qty, () => {
      setCart((c) => ({ ...c, lines: c.lines.filter((_, i) => i !== index) }));
      setSelected((s) => Math.max(0, Math.min(s, cart.lines.length - 2)));
    });
  };

  const setQty = (index: number, qty: string) => {
    const line = cart.lines[index];
    if (!line || line.fixed) return;
    const cur = qtyUnits(line.qty);
    const next = qtyUnits(qty);
    if (next === cur || next <= 0n) return;
    const apply = () => setCart((c) => ({ ...c, lines: c.lines.map((l, i) => (i === index ? { ...l, qty } : l)) }));
    if (next > cur) apply();
    else removeScanned(index, fromQtyUnits(cur - next), apply);
  };

  const reset = () => {
    setCart(newCart());
    setSelected(0);
    setLastAdded(null);
    setDiscountApproval(null);
    payKey.current = newIdempotencyKey();
  };

  const checkout = useMutation({
    mutationFn: (r: PayResult) =>
      api.post<Invoice>(
        "/sales/invoices",
        { ...payload, id: cart.id, payments: r.payments, cash_tendered: r.cash_tendered ?? null, customer_id: r.customer_id ?? null, approval_id: discountApproval },
        { idempotencyKey: payKey.current },
      ),
    onSuccess: (inv) => {
      setDialog(null);
      setLastInvoice(inv);
      reset();
      for (const w of inv.warnings) toast.warning(w);
      toast.success(`فاکتور ${toFaDigits(inv.number ?? 0)} ثبت شد`);
      if (autoPrint) setTimeout(printReceipt, 50);
      qc.invalidateQueries({ queryKey: ["inventory"] });
    },
    onError: (e) => {
      // Same key on retry only if the request may not have reached the server.
      if (!(e instanceof ApiError && e.status === 0)) payKey.current = newIdempotencyKey();
      toast.error(e instanceof ApiError ? e.message : "ثبت فاکتور انجام نشد");
    },
  });

  const openPay = (mode: PayMode) => {
    if (!q || !cart.lines.length) return;
    if (q.needs_discount_approval && !can("sales.invoice.discount_over_limit") && !discountApproval) {
      setDialog({
        kind: "approval",
        action: "discount_over_limit",
        detail: `تخفیف ${toFaDigits(q.manual_discount_percent)}٪ (سقف ${toFaDigits(q.discount_limit_percent)}٪)`,
        then: (id) => {
          setDiscountApproval(id);
          setDialog({ kind: "pay", mode });
        },
      });
      return;
    }
    setDialog({ kind: "pay", mode });
  };

  const hold = useMutation({
    mutationFn: (note: string) => api.post<Invoice>("/sales/held", { ...payload, note: note || null }, { idempotencyKey: newIdempotencyKey() }),
    onSuccess: () => {
      setDialog(null);
      reset();
      qc.invalidateQueries({ queryKey: ["sales", "register"] });
      toast.success("فاکتور معلق شد");
    },
    onError: (e) => toast.error(e instanceof ApiError ? e.message : "خطا"),
  });

  const recall = useMutation({
    mutationFn: (id: string) => api.post<Invoice>(`/sales/held/${id}/recall`),
    onSuccess: (inv) => {
      setDialog(null);
      const discount = sumRials(inv.lines.map((l) => l.manual_discount));
      setCart({
        id: crypto.randomUUID(),
        discount: discount.split(".")[0],
        lines: inv.lines.map((l) => ({
          key: crypto.randomUUID(),
          item_id: l.item_id,
          code: l.item_code,
          name: l.item_name,
          unit_id: l.unit_id,
          qty: trimQty(l.qty),
          barcode: l.scanned_barcode ?? undefined,
          // The POS sends a barcode only for scale labels, whose quantity is fixed.
          fixed: !!l.scanned_barcode,
        })),
      });
      qc.invalidateQueries({ queryKey: ["sales", "register"] });
      toast.success("فاکتور معلق بازیابی شد");
    },
    onError: (e) => toast.error(e instanceof ApiError ? e.message : "خطا"),
  });

  // Keyboard-first: the scan field keeps focus; function keys drive the rest.
  React.useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (dialog) return;
      const inScan = document.activeElement === scanRef.current;
      const empty = !scanRef.current?.value;
      if (e.key in PAY_KEYS) {
        e.preventDefault();
        openPay(PAY_KEYS[e.key]);
      } else if (e.key === "F2") {
        e.preventDefault();
        if (cart.lines[selected] && !cart.lines[selected].fixed) setDialog({ kind: "qty", index: selected });
      } else if (e.key === "F3") {
        e.preventDefault();
        focusScan();
      } else if (e.key === "F4") {
        e.preventDefault();
        if (cart.lines.length) setDialog({ kind: "hold" });
      } else if (e.key === "F5") {
        e.preventDefault();
        if (cart.lines.length) toast.info("ابتدا فاکتور جاری را ثبت یا معلق کنید");
        else setDialog({ kind: "held" });
      } else if (e.key === "F6") {
        e.preventDefault();
        if (can("sales.invoice.discount") && q) setDialog({ kind: "discount" });
      } else if (e.key === "F12") {
        e.preventDefault();
        if (cart.lines.length) toast.info("فاکتور جاری خالی نیست");
        else setDialog({ kind: "close" });
      } else if (e.key === "Delete" && (!inScan || empty)) {
        e.preventDefault();
        deleteLine(selected);
      } else if ((e.key === "ArrowDown" || e.key === "ArrowUp") && empty) {
        e.preventDefault();
        setSelected((s) => Math.max(0, Math.min(cart.lines.length - 1, s + (e.key === "ArrowDown" ? 1 : -1))));
      } else if ((e.key === "+" || e.key === "-") && empty && cart.lines[selected] && !cart.lines[selected].fixed) {
        e.preventDefault();
        const l = cart.lines[selected];
        if (e.key === "+") setQty(selected, addQty(l.qty, "1"));
        else if (qtyUnits(l.qty) > 1000n) setQty(selected, addQty(l.qty, "-1"));
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  });

  const itemCount = cart.lines.length;

  return (
    <>
      <div className="grid min-h-0 flex-1 grid-cols-[minmax(0,1fr)_23rem] gap-3">
        <section className="flex min-h-0 flex-col gap-3">
          <div className="glass flex items-center gap-3 rounded-2xl p-3">
            <ItemSearch ref={scanRef} onPick={add} autoFocus className="flex-1" inputClassName="h-14 text-lg" placeholder="اسکن بارکد یا جست‌وجوی کالا… (F3)" />
          </div>
          {q?.warnings.length ? (
            <div className="rounded-xl bg-warning/15 px-4 py-2 text-sm text-ink" role="status">
              {q.warnings.join(" · ")}
            </div>
          ) : null}
          <div className="surface min-h-0 flex-1 overflow-y-auto rounded-2xl">
            {!cart.lines.length ? (
              lastInvoice ? (
                <LastSale invoice={lastInvoice} currency={currency} />
              ) : (
                <EmptyState icon={ShoppingCart} title="آماده فروش" description="کالا را اسکن کنید. F5 فاکتورهای معلق، F12 بستن شیفت." />
              )
            ) : (
              <table className="w-full text-sm">
                <thead className="sticky top-0 bg-[var(--surface)] text-xs text-ink-faint">
                  <tr>
                    <th className="w-10 px-3 py-3 text-start">#</th>
                    <th className="px-3 py-3 text-start">کالا</th>
                    <th className="w-36 px-3 py-3 text-start">مقدار</th>
                    <th className="w-32 px-3 py-3 text-start">فی</th>
                    <th className="w-28 px-3 py-3 text-start">تخفیف</th>
                    <th className="w-36 px-3 py-3 text-start">جمع</th>
                    <th className="w-12" />
                  </tr>
                </thead>
                <tbody>
                  {cart.lines.map((l, i) => {
                    const ql = q?.lines[i];
                    const disc = ql ? sumRials([ql.promotion_discount, ql.manual_discount]) : "0";
                    return (
                      <tr
                        key={l.key}
                        onClick={() => setSelected(i)}
                        className={cn("cursor-pointer border-t border-[var(--line)]", i === selected && "bg-brand-500/8 outline-2 -outline-offset-2 outline-brand-400/50")}
                        aria-selected={i === selected}
                      >
                        <td className="tabular px-3 py-2.5 text-ink-faint">{toFaDigits(i + 1)}</td>
                        <td className="px-3 py-2.5">
                          <div className="font-semibold text-ink">
                            {l.name}
                            {ql?.promotion_name ? <Badge tone="warning" icon={false} className="ms-2">{ql.promotion_name}</Badge> : null}
                          </div>
                          <div className="tabular text-xs text-ink-faint" dir="ltr">
                            {l.fixed ? "برچسب ترازو" : l.code}
                          </div>
                        </td>
                        <td className="px-3 py-2.5">
                          {l.fixed ? (
                            <span className="tabular">{toFaDigits(trimQty(ql?.qty ?? l.qty))} {ql?.unit_name}</span>
                          ) : (
                            <div className="inline-flex items-center gap-1 rounded-xl bg-[var(--surface-muted)] p-1">
                              <button type="button" aria-label={`کم کردن ${l.name}`} className="rounded-lg p-1 hover:bg-white dark:hover:bg-white/10" onClick={(e) => { e.stopPropagation(); if (qtyUnits(l.qty) > 1000n) setQty(i, addQty(l.qty, "-1")); else deleteLine(i); }}>
                                <Minus className="size-4" />
                              </button>
                              <button type="button" className="tabular min-w-8 text-center font-bold" onClick={(e) => { e.stopPropagation(); setDialog({ kind: "qty", index: i }); }}>
                                {toFaDigits(trimQty(l.qty))}
                              </button>
                              <button type="button" aria-label={`افزودن ${l.name}`} className="rounded-lg p-1 hover:bg-white dark:hover:bg-white/10" onClick={(e) => { e.stopPropagation(); setQty(i, addQty(l.qty, "1")); }}>
                                <Plus className="size-4" />
                              </button>
                              {ql && ql.unit_name ? <span className="px-1 text-xs text-ink-faint">{ql.unit_name}</span> : null}
                            </div>
                          )}
                        </td>
                        <td className="tabular px-3 py-2.5">{ql ? money(ql.unit_price) : "…"}</td>
                        <td className="tabular px-3 py-2.5 text-danger">{Number(disc) ? `−${money(disc)}` : "—"}</td>
                        <td className="tabular px-3 py-2.5 font-bold">{ql ? money(ql.line_total) : "…"}</td>
                        <td className="px-2">
                          <button type="button" aria-label={`حذف ${l.name}`} className="rounded-lg p-1.5 text-ink-faint hover:bg-danger/10 hover:text-danger" onClick={(e) => { e.stopPropagation(); deleteLine(i); }}>
                            <Trash2 className="size-4" />
                          </button>
                        </td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            )}
          </div>
        </section>

        <aside className="flex min-h-0 flex-col gap-3">
          <Card className="flex flex-col gap-2 p-4 text-sm">
            <SumRow label="تعداد اقلام" value={`${toFaDigits(itemCount)} قلم`} />
            <SumRow label="جمع کل" value={q ? money(q.subtotal) : "—"} />
            <SumRow label="تخفیف" value={q && Number(q.discount_total) ? `−${money(q.discount_total)}` : "—"} danger />
            <SumRow label="مالیات بر ارزش افزوده" value={q ? money(q.tax_total) : "—"} />
            <div className="mt-2 rounded-2xl bg-gradient-to-l from-brand-600 to-brand-500 p-4 text-white shadow-lg">
              <div className="text-xs opacity-80">مبلغ قابل پرداخت</div>
              <div className="tabular text-4xl leading-tight font-black" aria-live="polite">
                {q ? money(q.grand_total) : money("0")}
              </div>
              {quote.isFetching ? <div className="text-xs opacity-70">در حال محاسبه…</div> : null}
            </div>
          </Card>
          <Card className="grid grid-cols-2 gap-2 p-3">
            <PayButton tone="success" label="نقدی" k="F8" onClick={() => openPay("cash")} disabled={!q || !can("sales.payment.cash")} />
            <PayButton tone="brand" label="کارت‌خوان" k="F9" onClick={() => openPay("card")} disabled={!q || !can("sales.payment.card")} />
            <PayButton label="پرداخت ترکیبی" k="F10" onClick={() => openPay("split")} disabled={!q || !can("sales.payment.card")} />
            <PayButton label="نسیه" k="F11" onClick={() => openPay("credit")} disabled={!q || !can("sales.payment.credit")} />
          </Card>
          <Card className="grid grid-cols-2 gap-2 p-3 text-sm">
            <Button variant="outline" onClick={() => setDialog({ kind: "discount" })} disabled={!q || !can("sales.invoice.discount")}>تخفیف (F6)</Button>
            <Button variant="outline" onClick={() => cart.lines.length && setDialog({ kind: "hold" })} disabled={!cart.lines.length}>
              <PauseCircle /> تعلیق (F4)
            </Button>
            <Button variant="outline" onClick={() => setDialog({ kind: "held" })} disabled={!!cart.lines.length}>
              معلق‌ها (F5){state.held_count ? ` · ${toFaDigits(state.held_count)}` : ""}
            </Button>
            <Button variant="outline" onClick={() => setDialog({ kind: "close" })} disabled={!!cart.lines.length}>بستن شیفت (F12)</Button>
            <label className="col-span-2 flex items-center gap-2 px-1 text-xs text-ink-soft">
              <input
                type="checkbox"
                checked={autoPrint}
                onChange={(e) => {
                  setAutoPrint(e.target.checked);
                  localStorage.setItem("nc.autoprint", e.target.checked ? "1" : "0");
                }}
              />
              چاپ خودکار فیش پس از ثبت
            </label>
          </Card>
        </aside>
      </div>

      <footer className="glass no-print flex flex-wrap items-center gap-x-5 gap-y-1 rounded-2xl px-4 py-2 text-xs text-ink-soft">
        {[["F2", "تغییر مقدار"], ["F3", "جست‌وجو"], ["F4", "تعلیق"], ["F5", "معلق‌ها"], ["F6", "تخفیف"], ["Del", "حذف ردیف"], ["+/−", "مقدار ردیف"], ["F8–F11", "پرداخت"], ["F12", "بستن شیفت"]].map(([k, t]) => (
          <span key={k}>
            <kbd className="rounded-md bg-white px-1.5 py-0.5 font-mono text-[11px] font-bold text-ink shadow-sm dark:bg-white/15">{k}</kbd> {t}
          </span>
        ))}
        <span className="flex-1" />
        <span>شیفت از {formatTime(state.shift?.opened_at ?? new Date())}</span>
      </footer>

      {lastInvoice ? (
        <div className="print-area pointer-events-none fixed top-0 -left-[200mm] print:static">
          <Receipt invoice={lastInvoice} currency={currency} organization={state.organization_name} header={state.receipt_header} footer={state.receipt_footer} />
        </div>
      ) : null}

      {dialog?.kind === "pay" && q ? (
        <PaymentDialog
          initial={dialog.mode}
          due={q.grand_total}
          currency={currency}
          state={state}
          cartId={cart.id}
          busy={checkout.isPending}
          onSubmit={(r) => checkout.mutate(r)}
          onClose={() => setDialog(null)}
        />
      ) : null}
      {dialog?.kind === "qty" && cart.lines[dialog.index] ? (
        <QtyDialog
          name={cart.lines[dialog.index].name}
          qty={cart.lines[dialog.index].qty}
          onSave={(v) => {
            const idx = dialog.index;
            setDialog(null);
            setQty(idx, v);
          }}
          onClose={() => setDialog(null)}
        />
      ) : null}
      {dialog?.kind === "discount" && q ? (
        <DiscountDialog
          subtotal={sumRials([q.subtotal, `-${q.promotion_total}`])}
          current={cart.discount}
          limit={q.discount_limit_percent}
          currency={currency}
          onSave={(rials) => {
            setCart((c) => ({ ...c, discount: rials }));
            setDiscountApproval(null);
            setDialog(null);
          }}
          onClose={() => setDialog(null)}
        />
      ) : null}
      {dialog?.kind === "hold" ? <HoldDialog busy={hold.isPending} onSave={(n) => hold.mutate(n)} onClose={() => setDialog(null)} /> : null}
      {dialog?.kind === "held" ? <HeldDialog registerId={reg} currency={currency} onRecall={(id) => recall.mutate(id)} onClose={() => setDialog(null)} /> : null}
      {dialog?.kind === "close" && state.shift ? (
        <CloseShiftDialog
          shift={state.shift}
          currency={currency}
          onClose={() => setDialog(null)}
          onClosed={() => {
            setDialog(null);
            setLastInvoice(null);
            qc.invalidateQueries({ queryKey: ["sales", "register"] });
          }}
        />
      ) : null}
      {dialog?.kind === "approval" ? (
        <ApprovalDialog
          registerId={reg}
          action={dialog.action}
          detail={dialog.detail}
          onApproved={(id, who) => {
            const then = dialog.then;
            setDialog(null);
            toast.success(`تأیید شد: ${who}`);
            then(id);
          }}
          onClose={() => setDialog(null)}
        />
      ) : null}
    </>
  );
}

function SumRow({ label, value, danger }: { label: string; value: string; danger?: boolean }) {
  return (
    <div className="flex items-center justify-between">
      <span className="text-ink-soft">{label}</span>
      <span className={cn("tabular font-bold", danger ? "text-danger" : "text-ink")}>{value}</span>
    </div>
  );
}

function PayButton({ label, k, onClick, disabled, tone }: { label: string; k: string; onClick: () => void; disabled?: boolean; tone?: "success" | "brand" }) {
  return (
    <button
      type="button"
      onClick={onClick}
      disabled={disabled}
      className={cn(
        "flex h-20 flex-col items-center justify-center rounded-2xl text-lg font-extrabold transition disabled:opacity-40",
        tone === "success" && "bg-success text-white shadow-md hover:brightness-110",
        tone === "brand" && "bg-brand-600 text-white shadow-md hover:brightness-110",
        !tone && "surface text-ink ring-1 ring-[var(--line)] hover:ring-brand-400",
      )}
    >
      {label}
      <kbd className="text-[11px] font-normal opacity-75">{k}</kbd>
    </button>
  );
}

function LastSale({ invoice, currency }: { invoice: Invoice; currency: DisplayCurrency }) {
  const change = invoice.change_due && Number(invoice.change_due) ? invoice.change_due : null;
  return (
    <div className="flex h-full flex-col items-center justify-center gap-3 p-6 text-center">
      <CheckCircle2 className="size-14 text-success" />
      <div className="text-lg font-bold text-ink">فاکتور {toFaDigits(invoice.number ?? 0)} ثبت شد — {formatMoney(invoice.grand_total, currency)}</div>
      {change ? (
        <div className="rounded-2xl bg-success/10 px-6 py-3 text-success">
          <div className="text-sm">باقی‌مانده برای مشتری</div>
          <div className="tabular text-3xl font-black">{formatMoney(change, currency)}</div>
        </div>
      ) : null}
      <Button variant="outline" onClick={printReceipt}>
        <Printer /> چاپ دوباره فیش
      </Button>
      <p className="text-sm text-ink-faint">برای فروش بعدی کالا را اسکن کنید.</p>
    </div>
  );
}
