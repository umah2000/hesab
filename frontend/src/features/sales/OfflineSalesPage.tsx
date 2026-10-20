import { keepPreviousData, useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { CloudOff } from "lucide-react";
import * as React from "react";
import { Link } from "react-router";
import { toast } from "sonner";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { Dialog, DialogContent, DialogFooter } from "@/components/ui/dialog";
import { Badge, EmptyState, ErrorBox, Spinner, type Tone } from "@/components/ui/feedback";
import { Field, Input, Select } from "@/components/ui/form-controls";
import { Pagination, Table, Td, Th, Tr } from "@/components/ui/table";
import { useCurrency } from "@/features/accounting/api";
import { ApiError, api, type Page } from "@/lib/api";
import { formatDateTime, formatMoney, toFaDigits } from "@/lib/format";

/** Operations pushed by register agents after selling offline (ADR-0017). */
export type SyncOperation = {
  id: string;
  device_id: string;
  device_name: string;
  register_name: string | null;
  op_type: "sale" | "line_removal";
  status: SyncStatus;
  device_number: string | null;
  sold_at: string | null;
  local_time: string;
  received_at: string;
  cashier_name: string | null;
  grand_total: string | null;
  code: string | null;
  message: string | null;
  price_difference: string | null;
  invoice_id: string | null;
  invoice_number: number | null;
  resolved_by_name: string | null;
  resolved_at: string | null;
  resolution_note: string | null;
  row_version: string;
};

type SyncStatus = "applied" | "rejected" | "conflict" | "resolved" | "discarded";

const STATUS: Record<SyncStatus, { label: string; tone: Tone }> = {
  applied: { label: "ثبت شد", tone: "success" },
  resolved: { label: "ثبت با تأیید مدیر", tone: "success" },
  conflict: { label: "تعارض؛ منتظر تصمیم", tone: "warning" },
  rejected: { label: "رد شد", tone: "danger" },
  discarded: { label: "کنار گذاشته شد", tone: "neutral" },
};

const onError = (e: unknown) => toast.error(e instanceof ApiError ? e.message : "خطا");

export function OfflineSalesPage() {
  const currency = useCurrency();
  const [status, setStatus] = React.useState("open");
  const [page, setPage] = React.useState(1);
  const [open, setOpen] = React.useState<SyncOperation | null>(null);
  const params = new URLSearchParams({ page: String(page), page_size: "50" });
  if (status) params.set("status", status);
  const list = useQuery({
    queryKey: ["sync", "operations", params.toString()],
    queryFn: () => api.get<Page<SyncOperation>>(`/sync/operations?${params}`),
    placeholderData: keepPreviousData,
    refetchInterval: 30_000,
  });
  return (
    <Card>
      <div className="flex flex-wrap items-end gap-3 p-4">
        <Field label="وضعیت">
          <Select value={status} onChange={(e) => { setStatus(e.target.value); setPage(1); }}>
            <option value="open">نیازمند رسیدگی (تعارض و ردشده)</option>
            <option value="conflict">تعارض</option>
            <option value="rejected">ردشده</option>
            <option value="applied">ثبت‌شده</option>
            <option value="resolved">ثبت با تأیید مدیر</option>
            <option value="discarded">کنار گذاشته</option>
            <option value="">همه</option>
          </Select>
        </Field>
        <p className="max-w-2xl text-sm text-ink-soft">
          فروش‌هایی که صندوق هنگام قطع ارتباط ثبت کرده است. هر فروش یک بار ثبت می‌شود؛ اگر شیفت یا دوره‌ی مالی‌اش بسته شده باشد یا ساعت صندوق نادرست باشد، تا تصمیم شما در «تعارض» می‌ماند.
        </p>
      </div>
      <div className="surface mx-4 mb-4 overflow-hidden rounded-2xl">
        {list.isLoading ? (
          <Spinner />
        ) : list.isError ? (
          <ErrorBox error={list.error} />
        ) : !list.data?.items.length ? (
          <EmptyState icon={CloudOff} title={status === "open" ? "موردی برای رسیدگی نیست" : "عملیاتی یافت نشد"} />
        ) : (
          <>
            <Table>
              <thead>
                <tr>
                  <Th>شماره صندوق</Th>
                  <Th>زمان فروش</Th>
                  <Th>صندوق / صندوق‌دار</Th>
                  <Th className="w-36">مبلغ</Th>
                  <Th>وضعیت</Th>
                  <Th>شرح</Th>
                  <Th className="w-28" />
                </tr>
              </thead>
              <tbody>
                {list.data.items.map((o) => (
                  <Tr key={o.id}>
                    <Td>{o.op_type === "sale" ? <span className="latin-digits tabular">{o.device_number ?? "—"}</span> : "حذف ردیف (آفلاین)"}</Td>
                    <Td className="text-ink-soft">{formatDateTime(o.sold_at ?? o.local_time)}</Td>
                    <Td className="text-ink-soft">{o.register_name ?? o.device_name}{o.cashier_name ? ` · ${o.cashier_name}` : ""}</Td>
                    <Td className="tabular font-semibold">{o.grand_total ? formatMoney(o.grand_total, currency) : "—"}</Td>
                    <Td><Badge tone={STATUS[o.status].tone}>{STATUS[o.status].label}</Badge></Td>
                    <Td className="text-sm">
                      {o.message ? <div>{o.message}</div> : null}
                      {o.invoice_id ? (
                        <Link className="text-brand-600 underline" to={`/sales/invoices/${o.invoice_id}`}>فاکتور {toFaDigits(o.invoice_number ?? 0)}</Link>
                      ) : null}
                      {o.price_difference && Number(o.price_difference) !== 0 ? (
                        <div className="text-ink-soft">
                          اختلاف با قیمت فعلی سرور: {formatMoney(o.price_difference, currency)}
                        </div>
                      ) : null}
                      {o.resolution_note ? <div className="text-ink-soft">تصمیم {o.resolved_by_name}: {o.resolution_note}</div> : null}
                    </Td>
                    <Td>
                      {o.status === "conflict" || o.status === "rejected" ? (
                        <Button size="sm" onClick={() => setOpen(o)}>رسیدگی</Button>
                      ) : null}
                    </Td>
                  </Tr>
                ))}
              </tbody>
            </Table>
            <Pagination page={page} pageSize={50} total={list.data.total} onPage={setPage} />
          </>
        )}
      </div>
      {open ? <ResolveDialog op={open} onClose={() => setOpen(null)} /> : null}
    </Card>
  );
}

function ResolveDialog({ op, onClose }: { op: SyncOperation; onClose: () => void }) {
  const qc = useQueryClient();
  const currency = useCurrency();
  const canApply = op.status === "conflict";
  const [action, setAction] = React.useState<"apply" | "discard">(canApply ? "apply" : "discard");
  const [note, setNote] = React.useState("");
  const save = useMutation({
    mutationFn: () => api.post<SyncOperation>(`/sync/operations/${op.id}/resolve`, { action, note: note.trim() }, { version: op.row_version }),
    onSuccess: (out) => {
      qc.invalidateQueries({ queryKey: ["sync"] });
      toast.success(out.status === "resolved" ? `ثبت شد: فاکتور ${toFaDigits(out.invoice_number ?? 0)}` : "کنار گذاشته شد");
      onClose();
    },
    onError,
  });
  return (
    <Dialog open onOpenChange={(o) => !o && onClose()}>
      <DialogContent
        title={op.device_number ? <>فروش آفلاین <span className="latin-digits">{op.device_number}</span></> : "عملیات آفلاین"}
        description={op.grand_total ? `${formatMoney(op.grand_total, currency)} · ${formatDateTime(op.sold_at ?? op.local_time)}` : undefined}
      >
        <div className="flex flex-col gap-3">
          <div className="surface rounded-xl p-3 text-sm">
            <Badge tone={STATUS[op.status].tone}>{STATUS[op.status].label}</Badge>
            <p className="mt-2">{op.message}</p>
          </div>
          <Field label="تصمیم">
            <Select value={action} onChange={(e) => setAction(e.target.value as "apply" | "discard")}>
              {canApply ? <option value="apply">ثبت فروش با همین مبالغ</option> : null}
              <option value="discard">کنار گذاشتن (ثبت نمی‌شود)</option>
            </Select>
          </Field>
          {action === "apply" ? (
            <p className="text-sm text-ink-soft">
              فاکتور با تاریخ فروش ثبت می‌شود (اگر دوره بسته باشد، با تاریخ امروز) و کالا امروز از انبار کسر می‌شود. اگر شیفت این فروش بسته شده، مغایرت صندوق آن شیفت را جداگانه اصلاح کنید.
            </p>
          ) : (
            <p className="text-sm text-ink-soft">کنار گذاشتن یعنی این فروش در دفاتر نمی‌آید؛ فقط وقتی که مطمئنید تکراری یا نادرست است.</p>
          )}
          <Field label="توضیح (در ممیزی ثبت می‌شود)">
            <Input aria-label="توضیح تصمیم" value={note} onChange={(e) => setNote(e.target.value)} />
          </Field>
        </div>
        <DialogFooter>
          <Button loading={save.isPending} disabled={note.trim().length < 2} onClick={() => save.mutate()}>ثبت تصمیم</Button>
          <Button variant="ghost" onClick={onClose}>انصراف</Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
