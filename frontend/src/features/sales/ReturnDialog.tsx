import { useMutation, useQueryClient } from "@tanstack/react-query";
import { Minus, Plus, Undo2 } from "lucide-react";
import * as React from "react";
import { toast } from "sonner";
import { Button } from "@/components/ui/button";
import { Dialog, DialogContent, DialogFooter } from "@/components/ui/dialog";
import { Field, Input, Select } from "@/components/ui/form-controls";
import { trimQty } from "@/features/inventory/api";
import { ApiError, api, newIdempotencyKey } from "@/lib/api";
import { type DisplayCurrency, formatMoney, toEnDigits, toFaDigits } from "@/lib/format";
import { addQty, qtyUnits, subQty } from "@/lib/qty";
import { cn } from "@/lib/utils";
import { type Invoice, type Method, storedRegister } from "./api";
import { ApprovalDialog } from "./ApprovalDialog";

const valid = (v: string) => /^\d+(\.\d{1,3})?$/.test(v) && qtyUnits(v) > 0n;

/**
 * Returning goods of a final sale: a return document against it (the sale itself never
 * changes, ADR-0013); the goods go back to stock at the sale's cost. A cashier without the
 * return permission gets a supervisor's approval on the register first (ADR-0029).
 */
export function ReturnDialog({
  invoice,
  currency,
  registerId,
  canReturn = true,
  onClose,
  onDone,
}: {
  invoice: Invoice;
  currency: DisplayCurrency;
  registerId?: string | null;
  canReturn?: boolean;
  onClose: () => void;
  onDone?: (ret: Invoice) => void;
}) {
  const qc = useQueryClient();
  const register = registerId ?? storedRegister();
  const [qty, setQty] = React.useState<Record<string, string>>({});
  const [reason, setReason] = React.useState("");
  const [method, setMethod] = React.useState<Method>("cash");
  const [cardRef, setCardRef] = React.useState("");
  const [asking, setAsking] = React.useState(false);
  const keyRef = React.useRef(newIdempotencyKey());
  const lines = invoice.lines
    .map((l) => ({ l, max: subQty(l.qty, l.returned_qty) }))
    .filter((x) => qtyUnits(x.max) > 0n);
  const chosen = lines.filter(({ l }) => valid(toEnDigits(qty[l.id] ?? "").trim()));
  const over = chosen.some(({ l, max }) => qtyUnits(toEnDigits(qty[l.id])) > qtyUnits(max));
  // Preview only: the server computes the exact refund (proportional, last return takes the rest).
  const preview = chosen.reduce(
    (acc, { l }) => acc + (BigInt(l.line_total.split(".")[0]) * qtyUnits(toEnDigits(qty[l.id]))) / qtyUnits(l.qty),
    0n,
  );
  const step = (id: string, max: string, d: string) => {
    const cur = valid(toEnDigits(qty[id] ?? "")) ? toEnDigits(qty[id]) : "0";
    let next = d.startsWith("-") ? subQty(cur, d.slice(1)) : addQty(cur, d);
    if (qtyUnits(next) < 0n) next = "0";
    if (qtyUnits(next) > qtyUnits(max)) next = max;
    setQty({ ...qty, [id]: qtyUnits(next) > 0n ? trimQty(next) : "" });
  };
  const create = useMutation({
    mutationFn: async (approvalId: string | null) => {
      if (!register) throw new ApiError(0, "no_register", "این رایانه به صندوقی وصل نیست؛ برگشت را از صفحه صندوق ثبت کنید");
      const body = {
        cash_register_id: register,
        reason: reason.trim(),
        lines: chosen.map(({ l }) => ({ original_line_id: l.id, qty: toEnDigits(qty[l.id]) })),
        // One refund method: the server refunds exactly the computed amount.
        refunds: [{ method, card_reference: method === "card" ? toEnDigits(cardRef) : null }],
        approval_id: approvalId,
      };
      return api.post<Invoice>(`/sales/invoices/${invoice.id}/returns`, body, { idempotencyKey: keyRef.current });
    },
    onSuccess: (r) => {
      toast.success(`برگشت شماره ${toFaDigits(r.number ?? 0)} ثبت شد؛ کالا به موجودی برگشت`);
      qc.invalidateQueries({ queryKey: ["sales"] });
      qc.invalidateQueries({ queryKey: ["inventory"] });
      onClose();
      onDone?.(r);
    },
    onError: (e) => {
      keyRef.current = newIdempotencyKey();
      toast.error(e instanceof ApiError ? e.message : "خطا");
    },
  });
  const submit = () => (canReturn ? create.mutate(null) : setAsking(true));
  const title = `برگشت از فاکتور ${toFaDigits(invoice.number ?? 0)}${invoice.manual_number ? ` (${invoice.manual_number})` : ""}`;
  return (
    <>
      <Dialog open={!asking} onOpenChange={(o) => !o && onClose()}>
        <DialogContent title={title} description="مقدار برگشتی هر قلم را بزنید. کالا با همان بهای فروش به موجودی برمی‌گردد." className="max-w-2xl">
          <div className="flex flex-col gap-3">
            {invoice.customer_name ? <p className="text-sm text-ink-soft">مشتری: {invoice.customer_name}</p> : null}
            {!lines.length ? <p className="text-sm text-ink-soft">همه‌ی اقلام این فاکتور قبلاً برگشت خورده‌اند.</p> : null}
            {lines.map(({ l, max }) => {
              const v = qty[l.id] ?? "";
              const bad = v !== "" && (!valid(toEnDigits(v)) || qtyUnits(toEnDigits(v)) > qtyUnits(max));
              return (
                <div key={l.id} className={cn("surface flex items-center gap-3 rounded-xl px-3 py-2 text-sm", valid(toEnDigits(v)) && !bad && "ring-2 ring-brand-500/40")}>
                  <div className="min-w-0 flex-1">
                    <div className="truncate font-medium">{l.item_name}</div>
                    <div className="text-xs text-ink-faint">
                      خریده: {toFaDigits(trimQty(l.qty))} · قابل برگشت: {toFaDigits(trimQty(max))} {l.unit_name} · {formatMoney(l.line_total, currency)}
                    </div>
                  </div>
                  <div className="flex items-center gap-1">
                    <Button type="button" size="icon" variant="outline" className="size-10" aria-label={`کم کردن ${l.item_name}`} onClick={() => step(l.id, max, "-1")}>
                      <Minus />
                    </Button>
                    <Input
                      className="h-10 w-20 text-center"
                      dir="ltr"
                      inputMode="decimal"
                      placeholder="0"
                      aria-invalid={bad || undefined}
                      aria-label={`مقدار برگشتی ${l.item_name}`}
                      value={v}
                      onChange={(e) => setQty({ ...qty, [l.id]: e.target.value })}
                    />
                    <Button type="button" size="icon" variant="outline" className="size-10" aria-label={`افزودن ${l.item_name}`} onClick={() => step(l.id, max, "1")}>
                      <Plus />
                    </Button>
                    <Button type="button" size="sm" variant="ghost" onClick={() => setQty({ ...qty, [l.id]: trimQty(max) })}>
                      همه
                    </Button>
                  </div>
                </div>
              );
            })}
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
              <Input aria-label="علت برگشت" value={reason} onChange={(e) => setReason(e.target.value)} placeholder="مثلاً خراب، تاریخ گذشته، اشتباه در خرید" />
            </Field>
            <p className="text-sm">
              مبلغ استرداد (تقریبی): <b className="tabular">{formatMoney(String(preview), currency)}</b>
            </p>
            {!canReturn ? <p className="text-xs text-ink-faint">ثبت برگشت با تأیید سرپرست روی همین صندوق انجام می‌شود.</p> : null}
          </div>
          <DialogFooter>
            <Button loading={create.isPending} disabled={preview <= 0n || over || reason.trim().length < 2} onClick={submit}>
              <Undo2 /> ثبت برگشت
            </Button>
            <Button variant="ghost" onClick={onClose}>انصراف</Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
      {asking && register ? (
        <ApprovalDialog
          registerId={register}
          action="return"
          detail={`برگشت ${toFaDigits(chosen.length)} قلم به مبلغ تقریبی ${formatMoney(String(preview), currency)}`}
          onApproved={(id) => {
            setAsking(false);
            create.mutate(id);
          }}
          onClose={() => setAsking(false)}
        />
      ) : null}
    </>
  );
}
