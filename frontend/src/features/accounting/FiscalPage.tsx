import { useMutation, useQueryClient } from "@tanstack/react-query";
import { CalendarPlus, Lock, LockOpen, ShieldAlert } from "lucide-react";
import * as React from "react";
import { toast } from "sonner";
import { Button } from "@/components/ui/button";
import { Card, CardBody, CardHeader } from "@/components/ui/card";
import { Dialog, DialogContent, DialogFooter } from "@/components/ui/dialog";
import { Badge, ErrorBox, Spinner } from "@/components/ui/feedback";
import { Field, Input } from "@/components/ui/form-controls";
import { useCan } from "@/features/auth/auth";
import { ApiError, api, newIdempotencyKey } from "@/lib/api";
import { formatMoney, toEnDigits, toFaDigits } from "@/lib/format";
import { isoToJalaliFa } from "@/lib/jalali";
import { cn } from "@/lib/utils";
import { type FiscalYear, useCurrency, useFiscalYears } from "./api";

const onError = (e: unknown) => toast.error(e instanceof ApiError ? e.message : "خطا");

function CloseYearDialog({ year, onClose }: { year: FiscalYear | null; onClose: () => void }) {
  const qc = useQueryClient();
  const currency = useCurrency();
  const [confirm, setConfirm] = React.useState("");
  React.useEffect(() => setConfirm(""), [year]);
  const close = useMutation({
    mutationFn: () => api.post<{ profit: string; opening_number?: number }>(`/accounting/fiscal-years/${year?.id}/close`),
    onSuccess: (r) => {
      qc.invalidateQueries({ queryKey: ["accounting"] });
      toast.success(`سال مالی بسته شد. سود (زیان) سال: ${formatMoney(r.profit, currency)}`);
      onClose();
    },
    onError,
  });
  return (
    <Dialog open={!!year} onOpenChange={(o) => !o && onClose()}>
      {year ? (
        <DialogContent title={`بستن ${year.title}`}>
          <div className="flex flex-col gap-3 text-sm text-ink-soft">
            <p className="flex items-start gap-2 rounded-xl bg-danger/10 p-3 text-danger">
              <ShieldAlert className="mt-0.5 size-5 shrink-0" />
              این عملیات برگشت‌پذیر نیست. پس از بستن، هیچ سندی در این سال ثبت نمی‌شود.
            </p>
            <ol className="list-decimal space-y-1 ps-5">
              <li>حساب‌های درآمد و هزینه به «سود (زیان) انباشته» بسته می‌شوند.</li>
              <li>سند اختتامیه همه مانده‌ها را صفر می‌کند.</li>
              <li>سند افتتاحیه در روز اول سال {toFaDigits(year.jalali_year + 1)} صادر می‌شود.</li>
            </ol>
            <p>پیش از بستن: هیچ سند پیش‌نویسی نباید در این سال باقی مانده باشد. پشتیبان‌گیری توصیه می‌شود.</p>
            <Field label={`برای تأیید، سال ${toFaDigits(year.jalali_year)} را بنویسید`}>
              <Input dir="ltr" value={confirm} onChange={(e) => setConfirm(e.target.value)} />
            </Field>
          </div>
          <DialogFooter>
            <Button
              variant="danger"
              disabled={toEnDigits(confirm) !== String(year.jalali_year)}
              loading={close.isPending}
              onClick={() => close.mutate()}
            >
              بستن سال مالی
            </Button>
            <Button variant="ghost" onClick={onClose}>انصراف</Button>
          </DialogFooter>
        </DialogContent>
      ) : null}
    </Dialog>
  );
}

export function FiscalPage() {
  const qc = useQueryClient();
  const can = useCan();
  const years = useFiscalYears();
  const [closing, setClosing] = React.useState<FiscalYear | null>(null);
  const manage = can("accounting.fiscal.close");
  const keyRef = React.useRef(newIdempotencyKey());

  const nextYear = (years.data?.[0]?.jalali_year ?? 1404) + 1;
  const create = useMutation({
    mutationFn: () => api.post<FiscalYear>("/accounting/fiscal-years", { jalali_year: nextYear }, { idempotencyKey: keyRef.current }),
    onSuccess: () => {
      keyRef.current = newIdempotencyKey();
      qc.invalidateQueries({ queryKey: ["accounting", "fiscal-years"] });
      toast.success(`سال مالی ${toFaDigits(nextYear)} تعریف شد`);
    },
    onError,
  });
  const lock = useMutation({
    mutationFn: (p: { id: string; locked: boolean; version: string }) =>
      api.put<FiscalYear>(`/accounting/fiscal-periods/${p.id}/lock`, { is_locked: p.locked }, p.version),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["accounting", "fiscal-years"] }),
    onError,
  });

  if (years.isLoading) return <Spinner />;
  if (years.isError) return <ErrorBox error={years.error} />;

  return (
    <div className="flex flex-col gap-4">
      {manage ? (
        <div className="flex justify-end">
          <Button variant="secondary" onClick={() => create.mutate()} loading={create.isPending}>
            <CalendarPlus /> تعریف سال مالی {toFaDigits(nextYear)}
          </Button>
        </div>
      ) : null}
      {years.data?.map((y) => (
        <Card key={y.id}>
          <CardHeader
            title={y.title}
            description={`${isoToJalaliFa(y.start_date)} تا ${isoToJalaliFa(y.end_date)}`}
            actions={
              <>
                {y.status === "open" ? <Badge tone="success">باز</Badge> : <Badge tone="neutral">بسته</Badge>}
                {manage && y.status === "open" ? (
                  <Button variant="outline" size="sm" onClick={() => setClosing(y)}>
                    بستن سال
                  </Button>
                ) : null}
              </>
            }
          />
          <CardBody className="grid grid-cols-2 gap-2 sm:grid-cols-4 lg:grid-cols-6">
            {y.periods.map((p) => (
              <button
                key={p.id}
                type="button"
                disabled={!manage || y.status === "closed" || lock.isPending}
                onClick={() => lock.mutate({ id: p.id, locked: !p.is_locked, version: p.row_version })}
                title={manage ? (p.is_locked ? "باز کردن دوره" : "قفل کردن دوره") : undefined}
                className={cn(
                  "flex items-center justify-between gap-2 rounded-xl px-3 py-2.5 text-sm transition",
                  p.is_locked ? "bg-black/5 text-ink-faint dark:bg-white/5" : "bg-brand-500/8 text-ink hover:bg-brand-500/15",
                  "disabled:cursor-default",
                )}
              >
                <span>{p.title.split(" ")[0]}</span>
                {p.is_locked ? <Lock className="size-4" aria-label="قفل" /> : <LockOpen className="size-4 text-success" aria-label="باز" />}
              </button>
            ))}
          </CardBody>
        </Card>
      ))}
      <CloseYearDialog year={closing} onClose={() => setClosing(null)} />
    </div>
  );
}
