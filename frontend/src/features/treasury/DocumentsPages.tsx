import { keepPreviousData, useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { ArrowDownToLine, ArrowLeftRight, ArrowUpFromLine, CreditCard, FileText, Undo2 } from "lucide-react";
import * as React from "react";
import { Link, useNavigate, useParams } from "react-router";
import { toast } from "sonner";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { Dialog, DialogContent, DialogFooter } from "@/components/ui/dialog";
import { Badge, EmptyState, ErrorBox, Spinner } from "@/components/ui/feedback";
import { Field, Input, Select } from "@/components/ui/form-controls";
import { Pagination, Table, Td, Th, Tr } from "@/components/ui/table";
import { useCurrency } from "@/features/accounting/api";
import { JalaliDateInput, Picker } from "@/features/accounting/inputs";
import { usePartyOptions } from "@/features/parties/api";
import { api, type Page } from "@/lib/api";
import { formatDateTime, formatMoney, toFaDigits } from "@/lib/format";
import { isoToJalaliFa } from "@/lib/jalali";
import { subRials } from "@/lib/money";
import {
  AGAINST_LABEL,
  CHEQUE_STATUS_TONE,
  chequeStatusLabel,
  type DocKind,
  type DocumentSummary,
  KIND_LABEL,
  KIND_TONE,
  METHOD_LABEL,
  onError,
  type TreasuryDocument,
  useBranches,
} from "./api";
import { ChequeDialog } from "./ChequesPage";
import { ReceiptPaymentDialog, SettlementDialog, TransferDialog } from "./DocumentDialogs";

const PAGE_SIZE = 50;

export function StatusBadge({ status }: { status: string }) {
  return status === "reversed" ? <Badge tone="danger">برگشت‌خورده</Badge> : <Badge tone="success">قطعی</Badge>;
}

export function TreasuryDocumentsPage() {
  const currency = useCurrency();
  const nav = useNavigate();
  const parties = usePartyOptions();
  const [page, setPage] = React.useState(1);
  const [kind, setKind] = React.useState<"" | DocKind>("");
  const [status, setStatus] = React.useState("");
  const [party, setParty] = React.useState<string | null>(null);
  const [from, setFrom] = React.useState<string | null>(null);
  const [to, setTo] = React.useState<string | null>(null);
  const [dialog, setDialog] = React.useState<null | "receipt" | "payment" | "transfer" | "settlement">(null);
  const reset = () => setPage(1);

  const params = new URLSearchParams({ page: String(page), page_size: String(PAGE_SIZE) });
  if (kind) params.set("kind", kind);
  if (status) params.set("status", status);
  if (party) params.set("party_id", party);
  if (from) params.set("date_from", from);
  if (to) params.set("date_to", to);
  const list = useQuery({
    queryKey: ["treasury", "documents", params.toString()],
    queryFn: () => api.get<Page<DocumentSummary>>(`/treasury/documents?${params}`),
    placeholderData: keepPreviousData,
  });

  return (
    <Card>
      <div className="flex flex-wrap items-center gap-2 p-4 pb-0">
        <Button onClick={() => setDialog("receipt")}>
          <ArrowDownToLine /> دریافت
        </Button>
        <Button onClick={() => setDialog("payment")}>
          <ArrowUpFromLine /> پرداخت
        </Button>
        <Button variant="secondary" onClick={() => setDialog("transfer")}>
          <ArrowLeftRight /> انتقال وجه
        </Button>
        <Button variant="secondary" onClick={() => setDialog("settlement")}>
          <CreditCard /> تسویه کارت‌خوان
        </Button>
      </div>
      <div className="flex flex-wrap items-end gap-3 p-4">
        <Field label="نوع">
          <Select value={kind} onChange={(e) => { setKind(e.target.value as "" | DocKind); reset(); }}>
            <option value="">همه</option>
            {(Object.keys(KIND_LABEL) as DocKind[]).map((k) => (
              <option key={k} value={k}>{KIND_LABEL[k]}</option>
            ))}
          </Select>
        </Field>
        <Field label="وضعیت">
          <Select value={status} onChange={(e) => { setStatus(e.target.value); reset(); }}>
            <option value="">همه</option>
            <option value="final">قطعی</option>
            <option value="reversed">برگشت‌خورده</option>
          </Select>
        </Field>
        <Field label="طرف‌حساب" className="w-64">
          <Picker ariaLabel="طرف‌حساب" options={parties.data ?? []} value={party} onChange={(v) => { setParty(v); reset(); }} placeholder="همه" />
        </Field>
        <Field label="از تاریخ">
          <JalaliDateInput value={from} onChange={(v) => { setFrom(v); reset(); }} />
        </Field>
        <Field label="تا تاریخ">
          <JalaliDateInput value={to} onChange={(v) => { setTo(v); reset(); }} />
        </Field>
      </div>
      <div className="surface mx-4 mb-4 overflow-hidden rounded-2xl">
        {list.isLoading ? (
          <Spinner />
        ) : list.isError ? (
          <ErrorBox error={list.error} />
        ) : !list.data?.items.length ? (
          <EmptyState icon={FileText} title="سندی یافت نشد" description="دریافت، پرداخت، انتقال وجه یا تسویه کارت‌خوان ثبت کنید." />
        ) : (
          <>
            <Table>
              <thead>
                <tr>
                  <Th className="w-20">شماره</Th>
                  <Th className="w-32">نوع</Th>
                  <Th className="w-28">وضعیت</Th>
                  <Th className="w-28">تاریخ</Th>
                  <Th>طرف‌حساب / حساب</Th>
                  <Th className="w-40">مبلغ</Th>
                  <Th>شرح</Th>
                </tr>
              </thead>
              <tbody>
                {list.data.items.map((d) => (
                  <Tr key={d.id} className="cursor-pointer" onClick={() => nav(`/treasury/documents/${d.id}`)}>
                    <Td className="tabular font-bold">
                      <Link to={`/treasury/documents/${d.id}`} onClick={(e) => e.stopPropagation()} className="hover:underline">
                        {toFaDigits(d.number ?? 0)}
                      </Link>
                    </Td>
                    <Td><Badge tone={KIND_TONE[d.kind]} icon={false}>{KIND_LABEL[d.kind]}</Badge></Td>
                    <Td><StatusBadge status={d.status} /></Td>
                    <Td className="tabular text-ink-soft">{isoToJalaliFa(d.document_date)}</Td>
                    <Td>{d.party_name ?? "—"}</Td>
                    <Td className="tabular font-semibold">{formatMoney(d.amount, currency)}</Td>
                    <Td className="max-w-64 truncate text-ink-soft">{d.description ?? ""}</Td>
                  </Tr>
                ))}
              </tbody>
            </Table>
            <Pagination page={page} pageSize={PAGE_SIZE} total={list.data.total} onPage={setPage} />
          </>
        )}
      </div>
      {dialog === "receipt" || dialog === "payment" ? <ReceiptPaymentDialog kind={dialog} onClose={() => setDialog(null)} /> : null}
      {dialog === "transfer" ? <TransferDialog onClose={() => setDialog(null)} /> : null}
      {dialog === "settlement" ? <SettlementDialog onClose={() => setDialog(null)} /> : null}
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

export function TreasuryDocumentPage() {
  const { id } = useParams();
  const currency = useCurrency();
  const branches = useBranches();
  const [reversing, setReversing] = React.useState(false);
  const [cheque, setCheque] = React.useState<string | null>(null);
  const doc = useQuery({
    queryKey: ["treasury", "document", id],
    queryFn: () => api.get<TreasuryDocument>(`/treasury/documents/${id}`),
  });
  if (doc.isLoading) return <Spinner />;
  if (doc.isError || !doc.data) return <ErrorBox error={doc.error} />;
  const d = doc.data;
  const money = (v: string) => formatMoney(v, currency);
  const branch = branches.data?.find((b) => b.id === d.branch_id)?.name;
  return (
    <Card className="p-4">
      <div className="mb-4 flex flex-wrap items-center gap-3">
        <h2 className="text-lg font-bold text-ink">
          {KIND_LABEL[d.kind]} شماره <span className="tabular">{toFaDigits(d.number ?? 0)}</span>
        </h2>
        <StatusBadge status={d.status} />
        {d.voucher_id ? (
          <Link className="text-sm text-brand-600 hover:underline" to={`/accounting/vouchers/${d.voucher_id}`}>
            سند حسابداری
          </Link>
        ) : null}
        {d.reversal_voucher_id ? (
          <Link className="text-sm text-brand-600 hover:underline" to={`/accounting/vouchers/${d.reversal_voucher_id}`}>
            سند حسابداری برگشت
          </Link>
        ) : null}
        <div className="flex-1" />
        <Button variant="outline" asChild>
          <Link to="/treasury/documents">بازگشت به فهرست</Link>
        </Button>
        {d.status === "final" ? (
          <Button variant="danger" onClick={() => setReversing(true)}>
            <Undo2 /> برگشت سند
          </Button>
        ) : null}
      </div>

      <div className="surface mb-4 grid grid-cols-2 gap-4 rounded-2xl p-4 md:grid-cols-4">
        <KV k="تاریخ سند"><span className="tabular">{isoToJalaliFa(d.document_date)}</span></KV>
        <KV k="شعبه">{branch ?? "—"}</KV>
        {d.party_name ? <KV k="طرف‌حساب">{d.party_name}</KV> : null}
        {d.against ? <KV k="بابت">{AGAINST_LABEL[d.against]}</KV> : null}
        {d.from_account_name ? <KV k="از حساب">{d.from_account_name}</KV> : null}
        {d.to_account_name ? <KV k={d.kind === "settlement" ? "حساب بانکی" : "به حساب"}>{d.to_account_name}</KV> : null}
        <KV k="مبلغ"><b className="tabular">{money(d.amount)}</b></KV>
        {d.kind === "settlement" ? (
          <>
            <KV k="کارمزد بانک"><span className="tabular">{money(d.fee)}</span></KV>
            <KV k="خالص واریزی"><span className="tabular">{money(subRials(d.amount, d.fee))}</span></KV>
          </>
        ) : null}
        {d.reference ? <KV k="شماره پیگیری"><span dir="ltr" className="tabular">{d.reference}</span></KV> : null}
        {d.description ? <KV k="شرح">{d.description}</KV> : null}
        <KV k="زمان ثبت">{formatDateTime(d.created_at)}</KV>
        {d.status === "reversed" ? (
          <>
            <KV k="زمان برگشت">{d.reversed_at ? formatDateTime(d.reversed_at) : "—"}</KV>
            <KV k="علت برگشت">{d.reversal_reason ?? "—"}</KV>
          </>
        ) : null}
      </div>

      {d.lines.length ? (
        <div className="surface overflow-hidden rounded-2xl">
          <Table>
            <thead>
              <tr>
                <Th className="w-12">ردیف</Th>
                <Th className="w-40">روش</Th>
                <Th>صندوق / حساب</Th>
                <Th className="w-40">مبلغ</Th>
                <Th>پیگیری</Th>
                <Th>چک</Th>
              </tr>
            </thead>
            <tbody>
              {d.lines.map((l) => (
                <Tr key={l.line_no}>
                  <Td className="tabular">{toFaDigits(l.line_no)}</Td>
                  <Td>{METHOD_LABEL[l.method]}</Td>
                  <Td>{l.money_account_name ?? "—"}</Td>
                  <Td className="tabular font-semibold">{money(l.amount)}</Td>
                  <Td dir="ltr" className="tabular text-end">{l.reference ?? ""}</Td>
                  <Td>
                    {l.cheque_id ? (
                      <div className="flex flex-wrap items-center gap-2">
                        <button type="button" className="tabular text-brand-600 hover:underline" onClick={() => setCheque(l.cheque_id)}>
                          چک {toFaDigits(l.cheque_number ?? "")}
                        </button>
                        {l.cheque_due_date ? <span className="tabular text-xs text-ink-faint">سررسید {isoToJalaliFa(l.cheque_due_date)}</span> : null}
                        {l.cheque_status ? (
                          <Badge tone={CHEQUE_STATUS_TONE[l.cheque_status] ?? "neutral"}>{chequeStatusLabel(l.cheque_status)}</Badge>
                        ) : null}
                      </div>
                    ) : (
                      "—"
                    )}
                  </Td>
                </Tr>
              ))}
            </tbody>
          </Table>
        </div>
      ) : null}
      {reversing ? <ReverseDialog doc={d} onClose={() => setReversing(false)} /> : null}
      {cheque ? <ChequeDialog id={cheque} onClose={() => setCheque(null)} /> : null}
    </Card>
  );
}

function ReverseDialog({ doc, onClose }: { doc: TreasuryDocument; onClose: () => void }) {
  const qc = useQueryClient();
  const [reason, setReason] = React.useState("");
  const [date, setDate] = React.useState<string | null>(null);
  const reverse = useMutation({
    mutationFn: () =>
      api.post<TreasuryDocument>(
        `/treasury/documents/${doc.id}/reverse`,
        { reason: reason.trim(), document_date: date },
        { version: doc.row_version },
      ),
    onSuccess: () => {
      toast.success("سند برگشت خورد");
      qc.invalidateQueries({ queryKey: ["treasury"] });
      qc.invalidateQueries({ queryKey: ["parties"] });
      onClose();
    },
    onError,
  });
  return (
    <Dialog open onOpenChange={(o) => !o && onClose()}>
      <DialogContent title={`برگشت ${KIND_LABEL[doc.kind]} شماره ${toFaDigits(doc.number ?? 0)}`}>
        <div className="flex flex-col gap-3 text-sm">
          <ul className="list-disc space-y-1 ps-5 text-ink-soft">
            <li>سند حسابداری آن با یک سند معکوس برمی‌گردد؛ سند اصلی حذف یا ویرایش نمی‌شود.</li>
            <li>چک‌های این سند باطل می‌شوند.</li>
            <li>اگر وضعیت یکی از چک‌ها تغییر کرده باشد (واگذاری، وصول، …) یا وجه نقد دریافتی از صندوق خرج شده باشد، برگشت ممکن نیست.</li>
          </ul>
          <Field label="علت برگشت">
            <Input aria-label="علت برگشت" maxLength={500} value={reason} onChange={(e) => setReason(e.target.value)} />
          </Field>
          <Field label="تاریخ برگشت" hint="خالی: همان تاریخ سند اصلی">
            <JalaliDateInput value={date} onChange={setDate} />
          </Field>
        </div>
        <DialogFooter>
          <Button variant="danger" loading={reverse.isPending} disabled={reason.trim().length < 2} onClick={() => reverse.mutate()}>
            <Undo2 /> برگشت سند
          </Button>
          <Button variant="ghost" onClick={onClose}>انصراف</Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
