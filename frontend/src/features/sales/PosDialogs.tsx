import { useMutation, useQuery } from "@tanstack/react-query";
import { Lock, PauseCircle, Percent } from "lucide-react";
import * as React from "react";
import { Button } from "@/components/ui/button";
import { Dialog, DialogContent, DialogFooter } from "@/components/ui/dialog";
import { EmptyState, Spinner } from "@/components/ui/feedback";
import { Field, Input } from "@/components/ui/form-controls";
import { MoneyInput } from "@/features/accounting/inputs";
import { ApiError, api } from "@/lib/api";
import { type DisplayCurrency, formatDateTime, formatMoney, toEnDigits, toFaDigits } from "@/lib/format";
import { compareRials, inputToRials } from "@/lib/money";
import { cn } from "@/lib/utils";
import { type InvoiceSummary, METHOD_LABEL, type Shift, type ShiftReport } from "./api";

export function QtyDialog({ name, qty, onSave, onClose }: { name: string; qty: string; onSave: (q: string) => void; onClose: () => void }) {
  const [v, setV] = React.useState(qty);
  const valid = /^\d+(\.\d{1,3})?$/.test(toEnDigits(v)) && Number(toEnDigits(v)) > 0;
  return (
    <Dialog open onOpenChange={(o) => !o && onClose()}>
      <DialogContent title="تغییر مقدار" description={name}>
        <form
          onSubmit={(e) => {
            e.preventDefault();
            if (valid) onSave(toEnDigits(v));
          }}
          className="flex flex-col gap-4"
        >
          <Input autoFocus dir="ltr" inputMode="decimal" className="tabular h-14 text-center text-2xl" value={v} onChange={(e) => setV(e.target.value)} aria-label="مقدار" onFocus={(e) => e.target.select()} />
          <DialogFooter>
            <Button type="submit" disabled={!valid}>ثبت (Enter)</Button>
            <Button type="button" variant="ghost" onClick={onClose}>انصراف</Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  );
}

/** Invoice discount as an amount or a percent of the subtotal; returns rials. */
export function DiscountDialog({
  subtotal,
  current,
  limit,
  currency,
  onSave,
  onClose,
}: {
  subtotal: string;
  current: string;
  limit: string;
  currency: DisplayCurrency;
  onSave: (rials: string) => void;
  onClose: () => void;
}) {
  const [kind, setKind] = React.useState<"amount" | "percent">("amount");
  const [amount, setAmount] = React.useState("");
  const [percent, setPercent] = React.useState("");
  const rials = (() => {
    if (kind === "amount") return inputToRials(amount, currency);
    const p = toEnDigits(percent).trim();
    if (!/^\d{1,3}(\.\d{1,2})?$/.test(p) || Number(p) > 100) return null;
    const [i, f = ""] = p.split(".");
    const hundredths = BigInt(i) * 100n + BigInt((f + "00").slice(0, 2));
    const sub = BigInt(subtotal.split(".")[0]);
    return String((sub * hundredths + 5000n) / 10000n);
  })();
  const over = rials !== null && compareRials(rials, subtotal) > 0;
  return (
    <Dialog open onOpenChange={(o) => !o && onClose()}>
      <DialogContent title="تخفیف فاکتور" description={`سقف تخفیف بدون تأیید سرپرست: ${toFaDigits(limit)}٪ جمع فاکتور`}>
        <form
          onSubmit={(e) => {
            e.preventDefault();
            if (rials !== null && !over) onSave(rials);
          }}
          className="flex flex-col gap-4"
        >
          <div className="grid grid-cols-2 gap-2">
            {(["amount", "percent"] as const).map((k) => (
              <button
                key={k}
                type="button"
                onClick={() => setKind(k)}
                className={cn(
                  "rounded-xl border px-3 py-2 text-sm font-bold",
                  kind === k ? "border-brand-500 bg-brand-500/10 text-brand-700 dark:text-brand-200" : "border-[var(--line)] text-ink-soft",
                )}
              >
                {k === "amount" ? "مبلغ" : "درصد"}
              </button>
            ))}
          </div>
          {kind === "amount" ? (
            <Field label={`مبلغ تخفیف (${currency === "IRT" ? "تومان" : "ریال"})`}>
              <MoneyInput autoFocus value={amount} onChange={setAmount} />
            </Field>
          ) : (
            <Field label="درصد تخفیف">
              <Input autoFocus dir="ltr" inputMode="decimal" value={percent} onChange={(e) => setPercent(e.target.value)} />
            </Field>
          )}
          <p className="text-sm text-ink-soft">
            جمع فاکتور {formatMoney(subtotal, currency)}
            {rials ? ` — تخفیف ${formatMoney(rials, currency)}` : ""}
            {Number(current) ? ` (تخفیف فعلی ${formatMoney(current, currency)})` : ""}
          </p>
          {over ? <p role="alert" className="text-sm text-danger">تخفیف از جمع فاکتور بیشتر است</p> : null}
          <DialogFooter>
            <Button type="submit" disabled={rials === null || over}>
              <Percent /> اعمال
            </Button>
            {Number(current) ? (
              <Button type="button" variant="outline" onClick={() => onSave("0")}>
                حذف تخفیف
              </Button>
            ) : null}
            <Button type="button" variant="ghost" onClick={onClose}>انصراف</Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  );
}

export function HeldDialog({
  registerId,
  currency,
  onRecall,
  onClose,
}: {
  registerId: string;
  currency: DisplayCurrency;
  onRecall: (id: string) => void;
  onClose: () => void;
}) {
  const held = useQuery({
    queryKey: ["sales", "held", registerId],
    queryFn: () => api.get<InvoiceSummary[]>(`/sales/held?cash_register_id=${registerId}`),
  });
  return (
    <Dialog open onOpenChange={(o) => !o && onClose()}>
      <DialogContent title="فاکتورهای معلق" description="فاکتورهای معلق همه صندوق‌های این شعبه" className="max-w-xl">
        {held.isLoading ? (
          <Spinner />
        ) : !held.data?.length ? (
          <EmptyState icon={PauseCircle} title="فاکتور معلقی نیست" />
        ) : (
          <ul className="flex flex-col gap-2">
            {held.data.map((h, i) => (
              <li key={h.id}>
                <button
                  autoFocus={i === 0}
                  type="button"
                  onClick={() => onRecall(h.id)}
                  className="surface flex w-full items-center gap-3 rounded-xl px-4 py-3 text-start hover:ring-2 hover:ring-brand-400 focus:ring-2 focus:ring-brand-500 focus:outline-none"
                >
                  <div className="flex-1">
                    <div className="font-semibold text-ink">{h.note || `${toFaDigits(h.line_count)} قلم`}</div>
                    <div className="text-xs text-ink-faint">
                      {h.register_name} · {h.cashier_name} · {formatDateTime(h.created_at)}
                    </div>
                  </div>
                  <span className="tabular font-bold">{formatMoney(h.grand_total, currency)}</span>
                </button>
              </li>
            ))}
          </ul>
        )}
      </DialogContent>
    </Dialog>
  );
}

export function HoldDialog({ onSave, onClose, busy }: { onSave: (note: string) => void; onClose: () => void; busy: boolean }) {
  const [note, setNote] = React.useState("");
  return (
    <Dialog open onOpenChange={(o) => !o && onClose()}>
      <DialogContent title="تعلیق فاکتور" description="فاکتور کنار گذاشته می‌شود و از هر صندوق این شعبه قابل بازیابی است.">
        <form
          onSubmit={(e) => {
            e.preventDefault();
            onSave(note.trim());
          }}
          className="flex flex-col gap-4"
        >
          <Field label="یادداشت (مثلاً نام مشتری)">
            <Input autoFocus value={note} maxLength={300} onChange={(e) => setNote(e.target.value)} />
          </Field>
          <DialogFooter>
            <Button type="submit" loading={busy}>
              <PauseCircle /> تعلیق
            </Button>
            <Button type="button" variant="ghost" onClick={onClose}>انصراف</Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  );
}

/** Blind count: the cashier counts first; expected cash and the difference are shown after closing. */
export function CloseShiftDialog({
  shift,
  currency,
  onClosed,
  onClose,
}: {
  shift: Shift;
  currency: DisplayCurrency;
  onClosed: () => void;
  onClose: () => void;
}) {
  const [counted, setCounted] = React.useState("");
  const [note, setNote] = React.useState("");
  const [error, setError] = React.useState<string | null>(null);
  const [result, setResult] = React.useState<ShiftReport | null>(null);
  const money = (v: string) => formatMoney(v, currency);
  const close = useMutation({
    mutationFn: async () => {
      const rials = inputToRials(counted, currency);
      if (rials === null) throw new ApiError(0, "invalid", "مبلغ شمارش نامعتبر است");
      await api.post<Shift>(`/sales/shifts/${shift.id}/close`, { counted_cash: rials, note: note || null }, { version: shift.row_version });
      return api.get<ShiftReport>(`/sales/shifts/${shift.id}/report`);
    },
    onSuccess: setResult,
    onError: (e) => setError(e instanceof ApiError ? e.message : "بستن شیفت انجام نشد"),
  });

  if (result) {
    const diff = result.shift.difference ?? "0";
    const sign = compareRials(diff, "0");
    return (
      <Dialog open onOpenChange={(o) => !o && onClosed()}>
        <DialogContent title="شیفت بسته شد" className="max-w-lg">
          <div className="print-area flex flex-col gap-2 text-sm">
            <Row label="تعداد فروش" value={toFaDigits(result.sale_count)} />
            <Row label="جمع فروش" value={money(result.sales_total)} />
            <Row label="جمع برگشت" value={money(result.returns_total)} />
            {result.by_method.map((m) => (
              <Row key={m.method} label={`دریافت ${METHOD_LABEL[m.method]}`} value={money(m.sales)} />
            ))}
            <Row label="موجودی اول شیفت" value={money(result.shift.opening_cash)} />
            <Row label="نقد مورد انتظار" value={money(result.shift.expected_cash ?? "0")} />
            <Row label="نقد شمارش‌شده" value={money(result.shift.counted_cash ?? "0")} />
            <div className={cn("mt-2 rounded-xl p-3 text-center text-lg font-black", sign === 0 ? "bg-success/10 text-success" : "bg-danger/10 text-danger")}>
              {sign === 0 ? "صندوق تراز است" : sign < 0 ? `کسری ${money(diff.replace("-", ""))}` : `اضافه ${money(diff)}`}
            </div>
          </div>
          <DialogFooter>
            <Button onClick={() => window.print()} variant="outline">چاپ گزارش</Button>
            <Button onClick={onClosed}>پایان</Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    );
  }
  return (
    <Dialog open onOpenChange={(o) => !o && onClose()}>
      <DialogContent title="بستن شیفت" description="وجه نقد داخل کشو را بشمارید و مبلغ را وارد کنید.">
        <form
          onSubmit={(e) => {
            e.preventDefault();
            setError(null);
            close.mutate();
          }}
          className="flex flex-col gap-4"
        >
          <Field label="نقد شمارش‌شده" error={error ?? undefined}>
            <MoneyInput autoFocus value={counted} onChange={setCounted} className="h-12 text-xl" />
          </Field>
          <Field label="توضیح (اختیاری)">
            <Input value={note} maxLength={500} onChange={(e) => setNote(e.target.value)} />
          </Field>
          <DialogFooter>
            <Button type="submit" variant="danger" loading={close.isPending} disabled={!counted}>
              <Lock /> بستن شیفت
            </Button>
            <Button type="button" variant="ghost" onClick={onClose}>انصراف</Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  );
}

function Row({ label, value }: { label: string; value: string }) {
  return (
    <div className="flex justify-between border-b border-[var(--line)] py-1">
      <span className="text-ink-soft">{label}</span>
      <span className="tabular font-semibold">{value}</span>
    </div>
  );
}
