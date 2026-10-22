import { useMutation, useQuery } from "@tanstack/react-query";
import { CreditCard, Search, Wallet } from "lucide-react";
import * as React from "react";
import { Button } from "@/components/ui/button";
import { Dialog, DialogContent, DialogFooter } from "@/components/ui/dialog";
import { Badge } from "@/components/ui/feedback";
import { Field, Input, Select } from "@/components/ui/form-controls";
import { MoneyInput } from "@/features/accounting/inputs";
import { ApiError, api } from "@/lib/api";
import { type DisplayCurrency, formatMoney, toEnDigits } from "@/lib/format";
import { compareRials, inputToRials, rialsToInput, subRials } from "@/lib/money";
import { cn } from "@/lib/utils";
import { type Customer, type Payment, type RegisterState, type TerminalTx, TX_LABEL } from "./api";

export type PayMode = "cash" | "card" | "split" | "credit";
export type PayResult = { payments: Payment[]; cash_tendered?: string; customer_id?: string };

const MODES: { mode: PayMode; label: string; key: string; perm: string }[] = [
  { mode: "cash", label: "نقدی", key: "F8", perm: "sales.payment.cash" },
  { mode: "card", label: "کارت‌خوان", key: "F9", perm: "sales.payment.card" },
  { mode: "split", label: "ترکیبی", key: "F10", perm: "sales.payment.card" },
  { mode: "credit", label: "نسیه", key: "F11", perm: "sales.payment.credit" },
];

export function PaymentDialog({
  initial,
  due,
  currency,
  state,
  cartId,
  busy,
  onSubmit,
  onClose,
}: {
  initial: PayMode;
  due: string;
  currency: DisplayCurrency;
  state: RegisterState;
  cartId: string;
  busy: boolean;
  onSubmit: (r: PayResult) => void;
  onClose: () => void;
}) {
  const can = (p: string) => state.permissions.includes(p);
  const [mode, setMode] = React.useState<PayMode>(initial);
  const [tendered, setTendered] = React.useState(rialsToInput(due, currency));
  const [cardRef, setCardRef] = React.useState("");
  const [splitCash, setSplitCash] = React.useState("");
  const [tx, setTx] = React.useState<TerminalTx | null>(null);
  const [scenario, setScenario] = React.useState("approve");
  const [customer, setCustomer] = React.useState<Customer | null>(null);
  const [q, setQ] = React.useState("");
  const [error, setError] = React.useState<string | null>(null);
  const money = (v: string) => formatMoney(v, currency);

  const splitCashRials = inputToRials(splitCash, currency) ?? "0";
  const cardAmount = mode === "split" ? subRials(due, splitCashRials) : due;
  const tenderedRials = inputToRials(tendered, currency);
  const change = tenderedRials ? subRials(tenderedRials, due) : "0";

  React.useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      const m = MODES.find((x) => x.key === e.key);
      if (m && can(m.perm)) {
        e.preventDefault();
        setMode(m.mode);
        setError(null);
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  });

  const startTx = useMutation({
    mutationFn: () =>
      api.post<TerminalTx>("/payments/terminal-transactions", {
        cash_register_id: state.cash_register_id,
        cart_id: cartId,
        amount: cardAmount,
        scenario: state.terminal?.simulated ? scenario : undefined,
      }),
    onSuccess: setTx,
    onError: (e) => setError(e instanceof ApiError ? e.message : "خطای کارت‌خوان"),
  });
  const inquire = useMutation({
    mutationFn: () => api.post<TerminalTx>(`/payments/terminal-transactions/${tx?.id}/inquire`),
    onSuccess: setTx,
    onError: (e) => setError(e instanceof ApiError ? e.message : "استعلام انجام نشد"),
  });
  const customers = useQuery({
    queryKey: ["sales", "customers", q],
    queryFn: () => api.get<Customer[]>(`/sales/customers?q=${encodeURIComponent(q)}`),
    enabled: mode === "credit",
    staleTime: 10_000,
  });

  const card = (amount: string): Payment =>
    tx?.status === "Approved" && compareRials(tx.amount, amount) === 0
      ? { method: "card", amount, terminal_transaction_id: tx.id }
      : { method: "card", amount, card_reference: toEnDigits(cardRef.trim()) };

  const submit = () => {
    setError(null);
    if (mode === "cash") {
      if (!tenderedRials || compareRials(tenderedRials, due) < 0) return setError("وجه دریافتی کمتر از مبلغ قابل پرداخت است");
      return onSubmit({ payments: [{ method: "cash", amount: due }], cash_tendered: tenderedRials });
    }
    const unresolved = tx && ["Pending", "Unknown", "ReconciliationRequired"].includes(tx.status);
    if (unresolved) return setError("وضعیت تراکنش کارت‌خوان نامشخص است؛ ابتدا استعلام کنید");
    const hasTx = tx?.status === "Approved";
    if ((mode === "card" || mode === "split") && !hasTx && !/^\d{4,32}$/.test(toEnDigits(cardRef.trim())))
      return setError("شماره پیگیری رسید کارت‌خوان را وارد کنید");
    if (mode === "card") return onSubmit({ payments: [card(due)] });
    if (mode === "split") {
      if (compareRials(splitCashRials, "0") <= 0 || compareRials(cardAmount, "0") <= 0)
        return setError("سهم نقد و کارت هر دو باید بیشتر از صفر باشند");
      return onSubmit({ payments: [{ method: "cash", amount: splitCashRials }, card(cardAmount)] });
    }
    if (!customer) return setError("مشتری را انتخاب کنید");
    return onSubmit({ payments: [{ method: "credit", amount: due }], customer_id: customer.id });
  };

  return (
    <Dialog open onOpenChange={(o) => !o && !busy && onClose()}>
      <DialogContent title="دریافت وجه" className="max-w-2xl">
        <div className="mb-4 rounded-2xl bg-gradient-to-l from-brand-600 to-brand-500 p-4 text-white">
          <div className="text-sm opacity-80">مبلغ قابل پرداخت</div>
          <div className="tabular text-3xl font-black">{money(due)}</div>
        </div>
        <div className="mb-4 grid grid-cols-4 gap-2" role="tablist">
          {MODES.map((m) => (
            <button
              key={m.mode}
              type="button"
              role="tab"
              aria-selected={mode === m.mode}
              disabled={!can(m.perm)}
              onClick={() => {
                setMode(m.mode);
                setError(null);
              }}
              className={cn(
                "flex flex-col items-center rounded-xl border px-2 py-2 text-sm font-bold transition disabled:opacity-40",
                mode === m.mode ? "border-brand-500 bg-brand-500/10 text-brand-700 dark:text-brand-200" : "border-[var(--line)] text-ink-soft",
              )}
            >
              {m.label}
              <kbd className="text-[10px] font-normal opacity-70">{m.key}</kbd>
            </button>
          ))}
        </div>

        <form
          onSubmit={(e) => {
            e.preventDefault();
            submit();
          }}
          className="flex flex-col gap-4"
        >
          {mode === "cash" ? (
            <div className="grid grid-cols-2 items-end gap-3">
              <Field label="وجه دریافتی از مشتری">
                <MoneyInput autoFocus value={tendered} onChange={setTendered} className="h-12 text-xl" aria-label="وجه دریافتی" />
              </Field>
              <div className="surface rounded-xl p-3 text-center">
                <div className="text-xs text-ink-faint">باقی‌مانده برای مشتری</div>
                <div className={cn("tabular text-xl font-black", compareRials(change, "0") < 0 ? "text-danger" : "text-success")}>
                  {compareRials(change, "0") < 0 ? "کسری" : money(change)}
                </div>
              </div>
            </div>
          ) : null}

          {mode === "split" ? (
            <div className="grid grid-cols-2 gap-3">
              <Field label="سهم نقد">
                <MoneyInput autoFocus value={splitCash} onChange={setSplitCash} aria-label="سهم نقد" />
              </Field>
              <Field label="سهم کارت">
                <Input readOnly value={money(cardAmount)} className="tabular" />
              </Field>
            </div>
          ) : null}

          {mode === "card" || mode === "split" ? (
            <div className="surface flex flex-col gap-3 rounded-2xl p-4">
              {state.terminal ? (
                <div className="flex flex-wrap items-center gap-2">
                  <CreditCard className="size-5 text-brand-500" />
                  <span className="text-sm font-semibold">{state.terminal.label}</span>
                  {!state.terminal.verified ? <Badge tone="warning">آزمایش‌نشده</Badge> : null}
                  {state.terminal.simulated ? (
                    <Select className="w-44" value={scenario} onChange={(e) => setScenario(e.target.value)} aria-label="سناریوی آزمایشی">
                      {state.terminal.scenarios.map((s) => (
                        <option key={s} value={s}>{s}</option>
                      ))}
                    </Select>
                  ) : null}
                  <Button type="button" size="sm" variant="secondary" loading={startTx.isPending} disabled={!!tx && tx.status !== "Declined"} onClick={() => startTx.mutate()}>
                    ارسال مبلغ به دستگاه
                  </Button>
                  {tx ? (
                    <Badge tone={tx.status === "Approved" ? "success" : tx.status === "Declined" ? "danger" : "warning"}>{TX_LABEL[tx.status]}</Badge>
                  ) : null}
                  {tx && (tx.status === "Unknown" || tx.status === "Pending") ? (
                    <Button type="button" size="sm" loading={inquire.isPending} onClick={() => inquire.mutate()}>
                      استعلام
                    </Button>
                  ) : null}
                </div>
              ) : (
                <p className="text-sm text-ink-soft">
                  کارت‌خوان هنوز به نرم‌افزار وصل نیست. مبلغ را روی دستگاه وارد کنید و پس از تأیید، شماره پیگیری رسید را این‌جا بنویسید.
                </p>
              )}
              {!tx || tx.status === "Declined" ? (
                <Field label="شماره پیگیری رسید کارت‌خوان">
                  <Input
                    autoFocus={mode === "card"}
                    dir="ltr"
                    inputMode="numeric"
                    className="tabular h-12 text-lg"
                    value={cardRef}
                    onChange={(e) => setCardRef(toEnDigits(e.target.value).replace(/\D/g, ""))}
                    aria-label="شماره پیگیری"
                  />
                </Field>
              ) : null}
            </div>
          ) : null}

          {mode === "credit" ? (
            <div className="flex flex-col gap-2">
              <div className="relative">
                <Search className="pointer-events-none absolute top-1/2 right-3 size-4 -translate-y-1/2 text-ink-faint" />
                <Input autoFocus className="ps-9" placeholder="نام یا کد مشتری" value={q} onChange={(e) => setQ(e.target.value)} aria-label="جست‌وجوی مشتری" />
              </div>
              <ul className="surface max-h-56 overflow-y-auto rounded-xl">
                {customers.data?.map((c) => {
                  const enough = c.credit_unlimited || (c.available !== null && compareRials(c.available, due) >= 0);
                  return (
                    <li key={c.id}>
                      <button
                        type="button"
                        onClick={() => setCustomer(c)}
                        className={cn(
                          "flex w-full items-center gap-3 px-3 py-2 text-start text-sm hover:bg-brand-500/5",
                          customer?.id === c.id && "bg-brand-500/10",
                        )}
                      >
                        <span className="flex-1 font-medium">{c.name}</span>
                        {c.credit_unlimited ? (
                          <Badge tone="success">اعتبار نامحدود</Badge>
                        ) : c.credit_limit === null ? (
                          <Badge tone="neutral">بدون اعتبار</Badge>
                        ) : (
                          <span className={cn("tabular text-xs", enough ? "text-success" : "text-danger")}>
                            اعتبار مانده: {money(c.available ?? "0")}
                          </span>
                        )}
                      </button>
                    </li>
                  );
                })}
              </ul>
            </div>
          ) : null}

          {error ? (
            <p role="alert" className="text-sm text-danger">
              {error}
            </p>
          ) : null}
          <DialogFooter>
            <Button type="submit" size="lg" loading={busy}>
              <Wallet /> ثبت و چاپ (Enter)
            </Button>
            <Button type="button" variant="ghost" onClick={onClose} disabled={busy}>
              بازگشت (Esc)
            </Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  );
}
