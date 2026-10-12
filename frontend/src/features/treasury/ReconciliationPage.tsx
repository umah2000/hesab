import { keepPreviousData, useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { CheckCircle2, Download, FileSpreadsheet, Link2, Scale, Unlink, Upload, Wand2 } from "lucide-react";
import * as React from "react";
import { Link } from "react-router";
import { toast } from "sonner";
import { Button } from "@/components/ui/button";
import { Card, CardBody, CardHeader } from "@/components/ui/card";
import { Dialog, DialogContent } from "@/components/ui/dialog";
import { Badge, EmptyState, ErrorBox, Spinner } from "@/components/ui/feedback";
import { Field, Select } from "@/components/ui/form-controls";
import { Pagination, Table, Td, Th, Tr } from "@/components/ui/table";
import { useCurrency } from "@/features/accounting/api";
import { JalaliDateInput } from "@/features/accounting/inputs";
import { api, newIdempotencyKey, type Page, upload } from "@/lib/api";
import type { DisplayCurrency } from "@/lib/format";
import { formatMoney, toFaDigits } from "@/lib/format";
import { isoToJalaliFa, todayIso } from "@/lib/jalali";
import {
  accountLabel,
  type AutoMatch,
  type BookLine,
  onError,
  type Reconciliation,
  type StatementImport,
  type StatementLine,
  useMoneyAccounts,
} from "./api";
import { absRials, flowOf, reconVerdict } from "./helpers";

const PAGE_SIZE = 100;

/** Signed amount as text («واریز»/«برداشت») plus the absolute value — never colour alone. */
function Flow({ amount, currency }: { amount: string; currency: DisplayCurrency }) {
  const f = flowOf(amount);
  return (
    <span className="inline-flex items-center gap-2">
      <Badge tone={f.incoming ? "success" : "warning"} icon={false}>{f.label}</Badge>
      <span className="tabular font-semibold">{formatMoney(f.abs, currency)}</span>
    </span>
  );
}

export function ReconciliationPage() {
  const banks = useMoneyAccounts("bank");
  const active = (banks.data ?? []).filter((a) => a.is_active);
  const [account, setAccount] = React.useState("");
  React.useEffect(() => {
    if (!account && active.length) setAccount(active[0].id);
  }, [active, account]);

  return (
    <div className="flex flex-col gap-4">
      <Card className="flex flex-wrap items-end gap-3 p-4">
        <Field label="حساب بانکی" className="min-w-72">
          <Select aria-label="حساب بانکی" value={account} onChange={(e) => setAccount(e.target.value)}>
            {!active.length ? <option value="">حساب بانکی فعالی تعریف نشده است</option> : null}
            {active.map((a) => (
              <option key={a.id} value={a.id}>{accountLabel(a)}</option>
            ))}
          </Select>
        </Field>
        <Button variant="outline" asChild>
          <a href="/api/v1/treasury/statements/template">
            <Download /> دانلود قالب صورتحساب
          </a>
        </Button>
      </Card>
      {banks.isLoading ? <Spinner /> : banks.isError ? <ErrorBox error={banks.error} /> : null}
      {account ? (
        <>
          <div className="grid gap-4 xl:grid-cols-2">
            <StatementImporter key={`imp-${account}`} account={account} />
            <ReconSummary key={`rec-${account}`} account={account} />
          </div>
          <StatementLines key={`lines-${account}`} account={account} />
        </>
      ) : null}
    </div>
  );
}

function StatementImporter({ account }: { account: string }) {
  const qc = useQueryClient();
  const [file, setFile] = React.useState<File | null>(null);
  const [preview, setPreview] = React.useState<StatementImport | null>(null);
  const keyRef = React.useRef(newIdempotencyKey());
  const inputRef = React.useRef<HTMLInputElement>(null);
  const check = useMutation({
    mutationFn: (f: File) => upload<StatementImport>(`/treasury/accounts/${account}/statement/preview`, f),
    onSuccess: setPreview,
    onError,
  });
  const commit = useMutation({
    mutationFn: () => upload<StatementImport>(`/treasury/accounts/${account}/statement/commit`, file as File, {}, keyRef.current),
    onSuccess: (r) => {
      toast.success(`${toFaDigits(r.new_rows)} ردیف ثبت شد؛ ${toFaDigits(r.duplicate_rows)} ردیف تکراری نادیده گرفته شد`);
      keyRef.current = newIdempotencyKey();
      setPreview(null);
      setFile(null);
      qc.invalidateQueries({ queryKey: ["treasury"] });
    },
    onError: (e) => {
      keyRef.current = newIdempotencyKey();
      onError(e);
    },
  });
  return (
    <Card>
      <CardHeader icon={<FileSpreadsheet className="size-5" />} title="ورود صورتحساب بانک" description="فایل Excel طبق قالب؛ ردیف‌های قبلاً واردشده تکراری حساب و نادیده گرفته می‌شوند." />
      <CardBody className="flex flex-col gap-3">
        <div className="flex flex-wrap items-center gap-3">
          <input
            ref={inputRef}
            type="file"
            accept=".xlsx,application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
            className="hidden"
            onChange={(e) => {
              const f = e.target.files?.[0] ?? null;
              setFile(f);
              setPreview(null);
              keyRef.current = newIdempotencyKey();
              if (f) check.mutate(f);
              e.target.value = "";
            }}
          />
          <Button variant="secondary" onClick={() => inputRef.current?.click()} loading={check.isPending}>
            <Upload /> انتخاب فایل Excel
          </Button>
          {file ? <span className="text-sm text-ink-soft">{file.name}</span> : null}
        </div>
        {preview ? (
          <div className="flex flex-col gap-3">
            <div className="flex flex-wrap gap-2">
              <Badge tone="info" icon={false}>{toFaDigits(preview.total_rows)} ردیف</Badge>
              <Badge tone="success">{toFaDigits(preview.new_rows)} ردیف جدید</Badge>
              <Badge tone="neutral" icon={false}>{toFaDigits(preview.duplicate_rows)} تکراری</Badge>
              {preview.errors.length ? <Badge tone="danger">{toFaDigits(preview.errors.length)} خطا</Badge> : null}
            </div>
            {preview.errors.length ? (
              <div className="surface max-h-60 overflow-y-auto rounded-2xl">
                <table className="w-full text-sm">
                  <thead>
                    <tr className="text-xs text-ink-faint">
                      <th className="w-16 px-3 py-2 text-start">ردیف</th>
                      <th className="w-36 px-3 py-2 text-start">ستون</th>
                      <th className="px-3 py-2 text-start">خطا</th>
                    </tr>
                  </thead>
                  <tbody>
                    {preview.errors.map((e, i) => (
                      <tr key={i} className="border-t border-[var(--line)]">
                        <td className="tabular px-3 py-1.5">{toFaDigits(e.row)}</td>
                        <td className="px-3 py-1.5">{e.column}</td>
                        <td className="px-3 py-1.5 text-danger">{e.message}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            ) : null}
            <p className="text-sm text-ink-soft">
              {preview.errors.length
                ? "ثبت فقط وقتی ممکن است که هیچ ردیفی خطا نداشته باشد. فایل را اصلاح و دوباره انتخاب کنید."
                : preview.new_rows
                  ? "با تأیید، ردیف‌های جدید یکجا ثبت می‌شوند."
                  : "ردیف جدیدی برای ثبت وجود ندارد."}
            </p>
            <Button className="self-start" disabled={!!preview.errors.length || !preview.new_rows || !file} loading={commit.isPending} onClick={() => commit.mutate()}>
              <CheckCircle2 /> تأیید و ثبت
            </Button>
          </div>
        ) : null}
      </CardBody>
    </Card>
  );
}

function ReconSummary({ account }: { account: string }) {
  const qc = useQueryClient();
  const currency = useCurrency();
  const [asOf, setAsOf] = React.useState<string | null>(todayIso());
  const recon = useQuery({
    queryKey: ["treasury", "reconciliation", account, asOf],
    queryFn: () => api.get<Reconciliation>(`/treasury/accounts/${account}/reconciliation?as_of=${asOf}`),
    enabled: !!asOf,
    placeholderData: keepPreviousData,
  });
  const auto = useMutation({
    mutationFn: () => api.post<AutoMatch>(`/treasury/accounts/${account}/statement/auto-match`),
    onSuccess: (r) => {
      toast.success(
        `${toFaDigits(r.matched)} ردیف تطبیق شد · ${toFaDigits(r.ambiguous)} ردیف چند گزینه دارد · ${toFaDigits(r.unmatched)} ردیف بدون گزینه`,
      );
      qc.invalidateQueries({ queryKey: ["treasury"] });
    },
    onError,
  });
  const money = (v: string) => formatMoney(v, currency);
  const r = recon.data;
  const verdict = r ? reconVerdict(r.adjusted_book_balance, r.statement_balance) : null;
  return (
    <Card>
      <CardHeader
        icon={<Scale className="size-5" />}
        title="مغایرت‌گیری"
        description="مانده دفاتر، اصلاح‌شده با اقلام تطبیق‌نشده، با مانده صورتحساب بانک مقایسه می‌شود."
        actions={
          <Button variant="secondary" size="sm" loading={auto.isPending} onClick={() => auto.mutate()}>
            <Wand2 /> تطبیق خودکار
          </Button>
        }
      />
      <CardBody className="flex flex-col gap-3">
        <Field label="تا تاریخ" className="w-40">
          <JalaliDateInput value={asOf} onChange={setAsOf} />
        </Field>
        {recon.isLoading ? (
          <Spinner />
        ) : recon.isError ? (
          <ErrorBox error={recon.error} />
        ) : r && verdict ? (
          <>
            <div className="surface grid grid-cols-1 gap-2 rounded-2xl p-4 text-sm sm:grid-cols-3">
              <div>
                <div className="text-xs text-ink-faint">مانده دفاتر</div>
                <b className="tabular">{money(r.book_balance)}</b>
              </div>
              <div>
                <div className="text-xs text-ink-faint">مانده اصلاح‌شده دفاتر</div>
                <b className="tabular">{money(r.adjusted_book_balance)}</b>
              </div>
              <div>
                <div className="text-xs text-ink-faint">مانده صورتحساب بانک</div>
                <b className="tabular">{r.statement_balance === null ? "—" : money(r.statement_balance)}</b>
              </div>
            </div>
            <div>
              {verdict.state === "agree" ? (
                <Badge tone="success">مغایرت ندارد</Badge>
              ) : verdict.state === "differ" && verdict.diff ? (
                <Badge tone="warning">مغایرت: {money(absRials(verdict.diff))}</Badge>
              ) : (
                <Badge tone="info">صورتحساب تا این تاریخ ستون «مانده» ندارد؛ مقایسه ممکن نیست</Badge>
              )}
            </div>
            <UnmatchedLists recon={r} currency={currency} />
          </>
        ) : null}
      </CardBody>
    </Card>
  );
}

function UnmatchedLists({ recon, currency }: { recon: Reconciliation; currency: DisplayCurrency }) {
  return (
    <div className="flex flex-col gap-3">
      <div>
        <h3 className="mb-1 text-sm font-bold text-ink">
          ردیف‌های صورتحساب بدون سند ({toFaDigits(recon.statement_unmatched.length)})
        </h3>
        {recon.statement_unmatched.length ? (
          <div className="surface max-h-60 overflow-y-auto rounded-2xl">
            <Table className="min-w-[28rem]">
              <tbody>
                {recon.statement_unmatched.map((l) => (
                  <Tr key={l.id}>
                    <Td className="tabular w-24">{isoToJalaliFa(l.line_date)}</Td>
                    <Td className="text-ink-soft">{l.description ?? l.reference ?? "—"}</Td>
                    <Td><Flow amount={l.amount} currency={currency} /></Td>
                  </Tr>
                ))}
              </tbody>
            </Table>
          </div>
        ) : (
          <p className="text-sm text-ink-faint">موردی نیست.</p>
        )}
      </div>
      <div>
        <h3 className="mb-1 text-sm font-bold text-ink">
          ردیف‌های دفاتر بدون صورتحساب ({toFaDigits(recon.book_unmatched.length)})
        </h3>
        {recon.book_unmatched.length ? (
          <div className="surface max-h-60 overflow-y-auto rounded-2xl">
            <Table className="min-w-[28rem]">
              <tbody>
                {recon.book_unmatched.map((b) => (
                  <BookRow key={b.voucher_line_id} b={b} currency={currency} />
                ))}
              </tbody>
            </Table>
          </div>
        ) : (
          <p className="text-sm text-ink-faint">موردی نیست.</p>
        )}
      </div>
    </div>
  );
}

function BookRow({ b, currency, action }: { b: BookLine; currency: DisplayCurrency; action?: React.ReactNode }) {
  return (
    <Tr>
      <Td className="tabular w-24">{isoToJalaliFa(b.document_date)}</Td>
      <Td>
        <Link className="tabular text-brand-600 hover:underline" to={`/accounting/vouchers/${b.voucher_id}`}>
          سند {toFaDigits(b.voucher_number ?? 0)}
        </Link>
        {b.description ? <div className="text-xs text-ink-faint">{b.description}</div> : null}
      </Td>
      <Td><Flow amount={b.amount} currency={currency} /></Td>
      {action ? <Td className="w-28">{action}</Td> : null}
    </Tr>
  );
}

function StatementLines({ account }: { account: string }) {
  const qc = useQueryClient();
  const currency = useCurrency();
  const [matched, setMatched] = React.useState("");
  const [page, setPage] = React.useState(1);
  const [matching, setMatching] = React.useState<StatementLine | null>(null);
  const params = new URLSearchParams({ page: String(page), page_size: String(PAGE_SIZE) });
  if (matched) params.set("matched", matched);
  const list = useQuery({
    queryKey: ["treasury", "statement", account, params.toString()],
    queryFn: () => api.get<Page<StatementLine>>(`/treasury/accounts/${account}/statement?${params}`),
    placeholderData: keepPreviousData,
  });
  const unmatch = useMutation({
    mutationFn: (id: string) => api.post<StatementLine>(`/treasury/statement-lines/${id}/unmatch`),
    onSuccess: () => {
      toast.success("تطبیق لغو شد");
      qc.invalidateQueries({ queryKey: ["treasury"] });
    },
    onError,
  });
  return (
    <Card>
      <CardHeader
        title="ردیف‌های صورتحساب"
        actions={
          <Select aria-label="فیلتر تطبیق" value={matched} onChange={(e) => { setMatched(e.target.value); setPage(1); }}>
            <option value="">همه</option>
            <option value="false">تطبیق‌نشده</option>
            <option value="true">تطبیق‌شده</option>
          </Select>
        }
      />
      <div className="surface mx-4 mb-4 overflow-hidden rounded-2xl">
        {list.isLoading ? (
          <Spinner />
        ) : list.isError ? (
          <ErrorBox error={list.error} />
        ) : !list.data?.items.length ? (
          <EmptyState icon={FileSpreadsheet} title="ردیفی نیست" description="صورتحساب بانک را از قالب Excel وارد کنید." />
        ) : (
          <>
            <Table>
              <thead>
                <tr>
                  <Th className="w-24">تاریخ</Th>
                  <Th>شرح</Th>
                  <Th className="w-32">پیگیری</Th>
                  <Th className="w-56">مبلغ</Th>
                  <Th className="w-40">مانده بانک</Th>
                  <Th className="w-36">تطبیق</Th>
                  <Th className="w-32" />
                </tr>
              </thead>
              <tbody>
                {list.data.items.map((l) => (
                  <Tr key={l.id}>
                    <Td className="tabular">{isoToJalaliFa(l.line_date)}</Td>
                    <Td className="text-ink-soft">{l.description ?? "—"}</Td>
                    <Td dir="ltr" className="tabular text-end">{l.reference ?? ""}</Td>
                    <Td><Flow amount={l.amount} currency={currency} /></Td>
                    <Td className="tabular">{l.balance === null ? "—" : formatMoney(l.balance, currency)}</Td>
                    <Td>
                      {l.voucher_id ? (
                        <Link to={`/accounting/vouchers/${l.voucher_id}`} className="hover:underline">
                          <Badge tone="success">سند {toFaDigits(l.voucher_number ?? 0)}</Badge>
                        </Link>
                      ) : (
                        <Badge tone="warning">تطبیق‌نشده</Badge>
                      )}
                    </Td>
                    <Td>
                      {l.voucher_line_id ? (
                        <Button variant="ghost" size="sm" loading={unmatch.isPending && unmatch.variables === l.id} onClick={() => unmatch.mutate(l.id)}>
                          <Unlink /> لغو تطبیق
                        </Button>
                      ) : (
                        <Button variant="outline" size="sm" onClick={() => setMatching(l)}>
                          <Link2 /> تطبیق دستی
                        </Button>
                      )}
                    </Td>
                  </Tr>
                ))}
              </tbody>
            </Table>
            <Pagination page={page} pageSize={PAGE_SIZE} total={list.data.total} onPage={setPage} />
          </>
        )}
      </div>
      {matching ? <MatchDialog line={matching} onClose={() => setMatching(null)} /> : null}
    </Card>
  );
}

function MatchDialog({ line, onClose }: { line: StatementLine; onClose: () => void }) {
  const qc = useQueryClient();
  const currency = useCurrency();
  const candidates = useQuery({
    queryKey: ["treasury", "candidates", line.id],
    queryFn: () => api.get<BookLine[]>(`/treasury/statement-lines/${line.id}/candidates`),
  });
  const match = useMutation({
    mutationFn: (voucherLineId: string) =>
      api.post<StatementLine>(`/treasury/statement-lines/${line.id}/match`, { voucher_line_id: voucherLineId }),
    onSuccess: () => {
      toast.success("ردیف تطبیق داده شد");
      qc.invalidateQueries({ queryKey: ["treasury"] });
      onClose();
    },
    onError,
  });
  return (
    <Dialog open onOpenChange={(o) => !o && onClose()}>
      <DialogContent
        title="تطبیق دستی"
        description="ردیف‌های سند هم‌مبلغ این حساب در بازه ۳۰ روز که هنوز تطبیق نشده‌اند. تطبیق، سند حسابداری را تغییر نمی‌دهد."
        className="max-w-2xl"
      >
        <div className="surface mb-3 flex flex-wrap items-center gap-3 rounded-xl p-3 text-sm">
          <span className="tabular">{isoToJalaliFa(line.line_date)}</span>
          <span className="text-ink-soft">{line.description ?? line.reference ?? ""}</span>
          <Flow amount={line.amount} currency={currency} />
        </div>
        {candidates.isLoading ? (
          <Spinner />
        ) : candidates.isError ? (
          <ErrorBox error={candidates.error} />
        ) : !candidates.data?.length ? (
          <EmptyState icon={Link2} title="ردیف سند هم‌مبلغی یافت نشد" />
        ) : (
          <div className="surface overflow-hidden rounded-2xl">
            <Table className="min-w-[32rem]">
              <tbody>
                {candidates.data.map((b) => (
                  <BookRow
                    key={b.voucher_line_id}
                    b={b}
                    currency={currency}
                    action={
                      <Button size="sm" loading={match.isPending && match.variables === b.voucher_line_id} disabled={match.isPending} onClick={() => match.mutate(b.voucher_line_id)}>
                        انتخاب
                      </Button>
                    }
                  />
                ))}
              </tbody>
            </Table>
          </div>
        )}
      </DialogContent>
    </Dialog>
  );
}
