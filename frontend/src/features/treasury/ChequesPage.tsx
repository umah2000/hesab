import { keepPreviousData, useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Check, FileStack } from "lucide-react";
import * as React from "react";
import { Link } from "react-router";
import { toast } from "sonner";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { Dialog, DialogContent } from "@/components/ui/dialog";
import { Badge, EmptyState, ErrorBox, Spinner } from "@/components/ui/feedback";
import { Field, Input, Select } from "@/components/ui/form-controls";
import { Pagination, Table, Td, Th, Tr } from "@/components/ui/table";
import { useCurrency } from "@/features/accounting/api";
import { JalaliDateInput, Picker } from "@/features/accounting/inputs";
import { usePartyOptions } from "@/features/parties/api";
import { api, type Page } from "@/lib/api";
import { formatDateTime, formatMoney, toFaDigits } from "@/lib/format";
import { isoToJalaliFa, todayIso } from "@/lib/jalali";
import {
  ACTION_LABEL,
  accountLabel,
  type Cheque,
  type ChequeAction,
  CHEQUE_STATUS_LABEL,
  CHEQUE_STATUS_TONE,
  type ChequeSummary,
  chequeStatusLabel,
  DIRECTION_LABEL,
  ISSUED_STATUSES,
  onError,
  RECEIVED_STATUSES,
  useMoneyAccounts,
} from "./api";
import { actionAccount } from "./helpers";

const PAGE_SIZE = 50;

function ChequeStatus({ status }: { status: string }) {
  return <Badge tone={CHEQUE_STATUS_TONE[status] ?? "neutral"}>{chequeStatusLabel(status)}</Badge>;
}

export function ChequesPage() {
  const currency = useCurrency();
  const parties = usePartyOptions();
  const [page, setPage] = React.useState(1);
  const [direction, setDirection] = React.useState("");
  const [status, setStatus] = React.useState("");
  const [dueUntil, setDueUntil] = React.useState<string | null>(null);
  const [party, setParty] = React.useState<string | null>(null);
  const [open, setOpen] = React.useState<string | null>(null);
  const reset = () => setPage(1);
  const statuses =
    direction === "received" ? RECEIVED_STATUSES : direction === "issued" ? ISSUED_STATUSES : Object.keys(CHEQUE_STATUS_LABEL);

  const params = new URLSearchParams({ page: String(page), page_size: String(PAGE_SIZE) });
  if (direction) params.set("direction", direction);
  if (status) params.set("status", status);
  if (dueUntil) params.set("due_until", dueUntil);
  if (party) params.set("party_id", party);
  const list = useQuery({
    queryKey: ["treasury", "cheques", params.toString()],
    queryFn: () => api.get<Page<ChequeSummary>>(`/treasury/cheques?${params}`),
    placeholderData: keepPreviousData,
  });

  return (
    <Card>
      <div className="flex flex-wrap items-end gap-3 p-4">
        <Field label="نوع چک">
          <Select
            value={direction}
            onChange={(e) => {
              setDirection(e.target.value);
              setStatus("");
              reset();
            }}
          >
            <option value="">دریافتی و پرداختی</option>
            <option value="received">دریافتی</option>
            <option value="issued">پرداختی</option>
          </Select>
        </Field>
        <Field label="وضعیت">
          <Select value={status} onChange={(e) => { setStatus(e.target.value); reset(); }}>
            <option value="">همه</option>
            {statuses.map((s) => (
              <option key={s} value={s}>{CHEQUE_STATUS_LABEL[s]}</option>
            ))}
          </Select>
        </Field>
        <Field label="سررسید تا" hint="چک‌های باز با سررسید تا این تاریخ">
          <JalaliDateInput value={dueUntil} onChange={(v) => { setDueUntil(v); reset(); }} />
        </Field>
        <Field label="طرف‌حساب" className="w-64">
          <Picker ariaLabel="طرف‌حساب" options={parties.data ?? []} value={party} onChange={(v) => { setParty(v); reset(); }} placeholder="همه" />
        </Field>
      </div>
      <div className="surface mx-4 mb-4 overflow-hidden rounded-2xl">
        {list.isLoading ? (
          <Spinner />
        ) : list.isError ? (
          <ErrorBox error={list.error} />
        ) : !list.data?.items.length ? (
          <EmptyState icon={FileStack} title="چکی یافت نشد" description="چک‌ها از روی اسناد دریافت و پرداخت ثبت می‌شوند." />
        ) : (
          <>
            <Table>
              <thead>
                <tr>
                  <Th className="w-28">شماره</Th>
                  <Th className="w-24">نوع</Th>
                  <Th>طرف‌حساب</Th>
                  <Th>بانک</Th>
                  <Th className="w-48">سررسید</Th>
                  <Th className="w-40">مبلغ</Th>
                  <Th className="w-40">وضعیت</Th>
                </tr>
              </thead>
              <tbody>
                {list.data.items.map((c) => (
                  <Tr key={c.id} className="cursor-pointer" onClick={() => setOpen(c.id)}>
                    <Td className="tabular font-bold">{toFaDigits(c.number)}</Td>
                    <Td>{DIRECTION_LABEL[c.direction]}</Td>
                    <Td>{c.party_name}</Td>
                    <Td className="text-ink-soft">{c.bank_name ?? "—"}</Td>
                    <Td>
                      <span className="tabular">{isoToJalaliFa(c.due_date)}</span>
                      {c.overdue ? <Badge tone="warning" className="ms-2">سررسید گذشته</Badge> : null}
                    </Td>
                    <Td className="tabular font-semibold">{formatMoney(c.amount, currency)}</Td>
                    <Td><ChequeStatus status={c.status} /></Td>
                  </Tr>
                ))}
              </tbody>
            </Table>
            <Pagination page={page} pageSize={PAGE_SIZE} total={list.data.total} onPage={setPage} />
          </>
        )}
      </div>
      {open ? <ChequeDialog id={open} onClose={() => setOpen(null)} /> : null}
    </Card>
  );
}

function KV({ k, children }: { k: string; children: React.ReactNode }) {
  return (
    <div className="flex flex-col gap-0.5">
      <span className="text-xs text-ink-faint">{k}</span>
      <span className="text-sm text-ink">{children}</span>
    </div>
  );
}

/** Cheque details, the actions the server allows now, and its append-only history. */
export function ChequeDialog({ id, onClose }: { id: string; onClose: () => void }) {
  const currency = useCurrency();
  const [action, setAction] = React.useState<ChequeAction | null>(null);
  const cheque = useQuery({
    queryKey: ["treasury", "cheque", id],
    queryFn: () => api.get<Cheque>(`/treasury/cheques/${id}`),
  });
  const c = cheque.data;
  return (
    <Dialog open onOpenChange={(o) => !o && onClose()}>
      <DialogContent title={c ? `چک ${DIRECTION_LABEL[c.direction]} شماره ${toFaDigits(c.number)}` : "چک"} className="max-w-3xl">
        {cheque.isLoading ? (
          <Spinner />
        ) : cheque.isError || !c ? (
          <ErrorBox error={cheque.error} />
        ) : (
          <div className="flex flex-col gap-4">
            <div className="surface grid grid-cols-2 gap-4 rounded-2xl p-4 md:grid-cols-3">
              <KV k="وضعیت"><ChequeStatus status={c.status} /></KV>
              <KV k="طرف‌حساب">{c.party_name}</KV>
              <KV k="مبلغ"><b className="tabular">{formatMoney(c.amount, currency)}</b></KV>
              <KV k="سررسید"><span className="tabular">{isoToJalaliFa(c.due_date)}</span></KV>
              <KV k="بانک">{c.bank_name ?? "—"}</KV>
              <KV k="صادرکننده">{c.drawer ?? "—"}</KV>
              <KV k="شناسه صیادی"><span className="tabular" dir="ltr">{c.sayad_id ?? "—"}</span></KV>
              <KV k={c.direction === "issued" ? "حساب بانکی چک" : "صندوق / حساب فعلی"}>{c.money_account_name ?? "—"}</KV>
              <KV k="سند مبدأ">
                <Link className="text-brand-600 hover:underline" to={`/treasury/documents/${c.document_id}`} onClick={onClose}>
                  {c.direction === "received" ? "دریافت" : "پرداخت"} شماره {toFaDigits(c.document_number ?? 0)}
                </Link>
              </KV>
            </div>

            {c.actions.length ? (
              <div className="flex flex-col gap-3">
                <div className="flex flex-wrap gap-2">
                  {c.actions.map((a) => (
                    <Button key={a} variant={action === a ? "primary" : "outline"} size="sm" onClick={() => setAction(a)}>
                      {ACTION_LABEL[a]}
                    </Button>
                  ))}
                </div>
                {action && c.actions.includes(action) ? (
                  <ActionForm key={action} cheque={c} action={action} onDone={() => setAction(null)} />
                ) : null}
              </div>
            ) : (
              <p className="text-sm text-ink-faint">برای این چک در وضعیت فعلی اقدامی ممکن نیست.</p>
            )}

            <div>
              <h3 className="mb-2 text-sm font-bold text-ink">سابقه چک</h3>
              <div className="surface overflow-hidden rounded-2xl">
                <Table className="min-w-[36rem]">
                  <thead>
                    <tr>
                      <Th className="w-10">#</Th>
                      <Th className="w-24">تاریخ</Th>
                      <Th>تغییر وضعیت</Th>
                      <Th>حساب</Th>
                      <Th>کاربر</Th>
                      <Th>سند</Th>
                    </tr>
                  </thead>
                  <tbody>
                    {c.events.map((e) => (
                      <Tr key={e.seq}>
                        <Td className="tabular">{toFaDigits(e.seq)}</Td>
                        <Td className="tabular">{isoToJalaliFa(e.event_date)}</Td>
                        <Td>
                          {e.from_status ? `${chequeStatusLabel(e.from_status)} ← ` : "ثبت: "}
                          {chequeStatusLabel(e.to_status)}
                          {e.note ? <div className="text-xs text-ink-faint">{e.note}</div> : null}
                        </Td>
                        <Td className="text-ink-soft">{e.money_account_name ?? "—"}</Td>
                        <Td className="text-ink-soft">
                          {e.user ?? "—"}
                          <div className="text-xs text-ink-faint">{formatDateTime(e.created_at)}</div>
                        </Td>
                        <Td>
                          {e.voucher_id ? (
                            <Link className="text-brand-600 hover:underline" to={`/accounting/vouchers/${e.voucher_id}`} onClick={onClose}>
                              سند حسابداری
                            </Link>
                          ) : (
                            "—"
                          )}
                        </Td>
                      </Tr>
                    ))}
                  </tbody>
                </Table>
              </div>
            </div>
          </div>
        )}
      </DialogContent>
    </Dialog>
  );
}

function ActionForm({ cheque, action, onDone }: { cheque: Cheque; action: ChequeAction; onDone: () => void }) {
  const qc = useQueryClient();
  const accounts = useMoneyAccounts();
  const needs = actionAccount(cheque.direction, cheque.status, action);
  const [date, setDate] = React.useState<string | null>(todayIso());
  const [note, setNote] = React.useState("");
  const [account, setAccount] = React.useState("");
  const options = (accounts.data ?? []).filter((a) => a.is_active && (needs === "any" || a.kind === "bank"));
  const run = useMutation({
    mutationFn: () =>
      api.post<Cheque>(
        `/treasury/cheques/${cheque.id}/actions`,
        { action, event_date: date, money_account_id: needs ? account : null, note: note.trim() || null },
        { version: cheque.row_version },
      ),
    onSuccess: (c) => {
      toast.success(`«${ACTION_LABEL[action]}» ثبت شد؛ وضعیت: ${chequeStatusLabel(c.status)}`);
      qc.setQueryData(["treasury", "cheque", c.id], c);
      qc.invalidateQueries({ queryKey: ["treasury"] });
      onDone();
    },
    onError,
  });
  return (
    <div className="surface flex flex-wrap items-end gap-3 rounded-2xl p-3">
      <Field label="تاریخ رویداد">
        <JalaliDateInput value={date} onChange={setDate} />
      </Field>
      {needs ? (
        <Field label={needs === "bank" ? "حساب بانکی" : "صندوق یا حساب بانکی"} className="min-w-56 flex-1">
          <Select aria-label="حساب" value={account} onChange={(e) => setAccount(e.target.value)}>
            <option value="">انتخاب کنید</option>
            {options.map((a) => (
              <option key={a.id} value={a.id}>
                {a.kind === "cash" ? "صندوق" : "بانک"}: {accountLabel(a)}
              </option>
            ))}
          </Select>
        </Field>
      ) : null}
      <Field label="یادداشت" className="min-w-48 flex-1">
        <Input maxLength={300} value={note} onChange={(e) => setNote(e.target.value)} />
      </Field>
      <Button loading={run.isPending} disabled={!date || (!!needs && !account)} onClick={() => run.mutate()}>
        <Check /> ثبت {ACTION_LABEL[action]}
      </Button>
    </div>
  );
}
