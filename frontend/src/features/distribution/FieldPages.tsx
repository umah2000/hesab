import { keepPreviousData, useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Banknote, MapPin, Target as TargetIcon, UserPlus } from "lucide-react";
import * as React from "react";
import { Link, Navigate } from "react-router";
import { toast } from "sonner";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { Dialog, DialogContent, DialogFooter } from "@/components/ui/dialog";
import { Badge, EmptyState, ErrorBox, Spinner } from "@/components/ui/feedback";
import { Field, Input, Select } from "@/components/ui/form-controls";
import { Pagination, Table, Td, Th, Tr } from "@/components/ui/table";
import { MoneyInput } from "@/features/accounting/inputs";
import { useCurrency } from "@/features/accounting/api";
import { useCan } from "@/features/auth/auth";
import type { MoneyAccount } from "@/features/treasury/api";
import { ApiError, api, type Page } from "@/lib/api";
import { formatDate, formatDateTime, formatMoney, toFaDigits } from "@/lib/format";
import { inputToRials, rialsToInput } from "@/lib/money";
import {
  type Collection,
  type CustomerRequest,
  METHOD_LABEL,
  REQUEST_STATUS,
  type RequestStatus,
  type Target,
  WEEKDAYS,
  mapLink,
} from "./api";

/** The section's first page: orders for sales managers, collections for treasury users. */
export function DistributionHome() {
  const can = useCan();
  return <Navigate to={can("distribution.manage") ? "orders" : "collections"} replace />;
}

const onError = (e: unknown) => toast.error(e instanceof ApiError ? e.message : "خطا");

function StatusBadge({ status }: { status: RequestStatus }) {
  const s = REQUEST_STATUS[status];
  return <Badge tone={s.tone}>{s.label}</Badge>;
}

function Place({ lat, lon }: { lat: string | null; lon: string | null }) {
  if (!lat || !lon) return null;
  return (
    <a className="inline-flex items-center gap-1 text-xs text-brand-600 underline" href={mapLink(lat, lon)} target="_blank" rel="noreferrer">
      <MapPin className="size-3.5" /> نقشه
    </a>
  );
}

function StatusFilter({ value, onChange }: { value: string; onChange: (v: string) => void }) {
  return (
    <Field label="وضعیت">
      <Select value={value} onChange={(e) => onChange(e.target.value)}>
        <option value="pending">در انتظار بررسی</option>
        <option value="approved">تأییدشده</option>
        <option value="rejected">ردشده</option>
        <option value="">همه</option>
      </Select>
    </Field>
  );
}

// --- collections ------------------------------------------------------------------------

/** Money visitors took from customers; the treasury approves each one into a receipt (ADR-0026). */
export function CollectionsPage() {
  const currency = useCurrency();
  const can = useCan();
  const [status, setStatus] = React.useState("pending");
  const [page, setPage] = React.useState(1);
  const [open, setOpen] = React.useState<{ c: Collection; kind: "approve" | "reject" } | null>(null);
  const params = new URLSearchParams({ page: String(page), page_size: "50" });
  if (status) params.set("status", status);
  const list = useQuery({
    queryKey: ["distribution", "collections", params.toString()],
    queryFn: () => api.get<Page<Collection>>(`/distribution/collections?${params}`),
    placeholderData: keepPreviousData,
    refetchInterval: 30_000,
  });
  const decide = can("treasury.manage");
  return (
    <Card>
      <div className="flex flex-wrap items-end gap-3 p-4">
        <StatusFilter value={status} onChange={(v) => { setStatus(v); setPage(1); }} />
        <p className="max-w-2xl text-sm text-ink-soft">
          وصولی که ویزیتور ثبت کرده تا تأیید شما در حساب مشتری اثر ندارد. «تأیید» یک سند دریافت عادی خزانه می‌سازد: نقد به صندوق، کارت‌به‌کارت به حساب بانکی، چک به دفتر چک‌های دریافتنی.
        </p>
      </div>
      <div className="surface mx-4 mb-4 overflow-hidden rounded-2xl">
        {list.isLoading ? (
          <Spinner />
        ) : list.isError ? (
          <ErrorBox error={list.error} />
        ) : !list.data?.items.length ? (
          <EmptyState icon={Banknote} title={status === "pending" ? "وصولی منتظر بررسی نیست" : "وصولی یافت نشد"} />
        ) : (
          <>
            <Table>
              <thead>
                <tr>
                  <Th>زمان</Th>
                  <Th>ویزیتور</Th>
                  <Th>مشتری</Th>
                  <Th>روش</Th>
                  <Th className="w-40">مبلغ</Th>
                  <Th>وضعیت</Th>
                  {decide ? <Th className="w-44" /> : null}
                </tr>
              </thead>
              <tbody>
                {list.data.items.map((c) => (
                  <Tr key={c.id}>
                    <Td className="text-ink-soft">
                      {formatDateTime(c.collected_at)}
                      <div><Place lat={c.latitude} lon={c.longitude} /></div>
                    </Td>
                    <Td>{c.visitor_name}</Td>
                    <Td className="font-medium">
                      {c.customer_name}
                      {c.note ? <div className="text-xs font-normal text-ink-faint">{c.note}</div> : null}
                    </Td>
                    <Td>
                      {METHOD_LABEL[c.method]}
                      {c.method === "cheque" ? (
                        <div className="text-xs text-ink-faint">
                          شماره {toFaDigits(c.cheque_number ?? "")} · سررسید {c.cheque_due_date ? formatDate(c.cheque_due_date) : "—"}
                          {c.cheque_bank ? ` · ${c.cheque_bank}` : ""}
                        </div>
                      ) : c.reference ? (
                        <div className="text-xs text-ink-faint" dir="ltr">{c.reference}</div>
                      ) : null}
                    </Td>
                    <Td className="tabular font-semibold">{formatMoney(c.amount, currency)}</Td>
                    <Td>
                      <StatusBadge status={c.status} />
                      {c.treasury_document_id ? (
                        <Link className="ms-2 text-xs text-brand-600 underline" to={`/treasury/documents/${c.treasury_document_id}`}>
                          دریافت {toFaDigits(c.treasury_document_number ?? 0)}
                        </Link>
                      ) : null}
                      {c.decision_note ? <div className="text-xs text-ink-faint">{c.decision_note}</div> : null}
                    </Td>
                    {decide ? (
                      <Td>
                        {c.status === "pending" ? (
                          <div className="flex gap-1.5">
                            <Button size="sm" onClick={() => setOpen({ c, kind: "approve" })}>تأیید</Button>
                            <Button size="sm" variant="outline" onClick={() => setOpen({ c, kind: "reject" })}>رد</Button>
                          </div>
                        ) : null}
                      </Td>
                    ) : null}
                  </Tr>
                ))}
              </tbody>
            </Table>
            <Pagination page={page} pageSize={50} total={list.data.total} onPage={setPage} />
          </>
        )}
      </div>
      {open ? <CollectionDialog c={open.c} kind={open.kind} onClose={() => setOpen(null)} /> : null}
    </Card>
  );
}

function CollectionDialog({ c, kind, onClose }: { c: Collection; kind: "approve" | "reject"; onClose: () => void }) {
  const qc = useQueryClient();
  const currency = useCurrency();
  const [account, setAccount] = React.useState("");
  const [note, setNote] = React.useState("");
  const needAccount = kind === "approve" && c.method !== "cheque";
  const want = c.method === "cash" ? "cash" : "bank";
  const accounts = useQuery({
    queryKey: ["treasury", "accounts", want],
    enabled: needAccount,
    queryFn: () => api.get<MoneyAccount[]>(`/treasury/accounts?kind=${want}`),
  });
  const save = useMutation({
    mutationFn: () =>
      api.post<Collection>(
        `/distribution/collections/${c.id}/${kind}`,
        kind === "approve" ? { money_account_id: needAccount ? account : null } : { note: note.trim() },
        { version: c.row_version },
      ),
    onSuccess: (r) => {
      qc.invalidateQueries({ queryKey: ["distribution", "collections"] });
      toast.success(kind === "approve" ? `سند دریافت ${toFaDigits(r.treasury_document_number ?? 0)} ثبت شد` : "رد شد");
      onClose();
    },
    onError,
  });
  const valid = kind === "reject" ? note.trim().length >= 2 : !needAccount || !!account;
  return (
    <Dialog open onOpenChange={(o) => !o && onClose()}>
      <DialogContent
        title={kind === "approve" ? "تأیید وصول و ثبت دریافت" : "رد وصول"}
        description={`${c.customer_name} — ${METHOD_LABEL[c.method]} ${formatMoney(c.amount, currency)} · ویزیتور ${c.visitor_name}`}
      >
        <div className="flex flex-col gap-3 text-sm">
          {kind === "approve" ? (
            needAccount ? (
              <Field label={c.method === "cash" ? "صندوق مقصد" : "حساب بانکی مقصد"}>
                <Select value={account} onChange={(e) => setAccount(e.target.value)}>
                  <option value="">انتخاب کنید</option>
                  {accounts.data?.filter((a) => a.is_active).map((a) => (
                    <option key={a.id} value={a.id}>{a.code} — {a.name}</option>
                  ))}
                </Select>
              </Field>
            ) : (
              <p className="text-ink-soft">چک در دفتر چک‌های دریافتنی با وضعیت «نزد صندوق» ثبت می‌شود.</p>
            )
          ) : (
            <Field label="علت (به ویزیتور نمایش داده می‌شود)">
              <Input value={note} onChange={(e) => setNote(e.target.value)} />
            </Field>
          )}
        </div>
        <DialogFooter>
          <Button loading={save.isPending} disabled={!valid} onClick={() => save.mutate()}>
            {kind === "approve" ? "تأیید و ثبت سند" : "رد وصول"}
          </Button>
          <Button variant="ghost" onClick={onClose}>انصراف</Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}

// --- new customers ----------------------------------------------------------------------

export function CustomerRequestsPage() {
  const [status, setStatus] = React.useState("pending");
  const [page, setPage] = React.useState(1);
  const [open, setOpen] = React.useState<{ r: CustomerRequest; kind: "approve" | "reject" } | null>(null);
  const params = new URLSearchParams({ page: String(page), page_size: "50" });
  if (status) params.set("status", status);
  const list = useQuery({
    queryKey: ["distribution", "customer-requests", params.toString()],
    queryFn: () => api.get<Page<CustomerRequest>>(`/distribution/customer-requests?${params}`),
    placeholderData: keepPreviousData,
  });
  return (
    <Card>
      <div className="flex flex-wrap items-end gap-3 p-4">
        <StatusFilter value={status} onChange={(v) => { setStatus(v); setPage(1); }} />
        <p className="max-w-2xl text-sm text-ink-soft">
          فروشگاه‌هایی که ویزیتورها پیدا کرده‌اند. «تأیید» با کد تفصیلی طرف‌حساب را می‌سازد و به همان ویزیتور، با روز بازدید پیشنهادی، تخصیص می‌دهد.
        </p>
      </div>
      <div className="surface mx-4 mb-4 overflow-hidden rounded-2xl">
        {list.isLoading ? (
          <Spinner />
        ) : list.isError ? (
          <ErrorBox error={list.error} />
        ) : !list.data?.items.length ? (
          <EmptyState icon={UserPlus} title={status === "pending" ? "درخواستی منتظر بررسی نیست" : "درخواستی یافت نشد"} />
        ) : (
          <>
            <Table>
              <thead>
                <tr>
                  <Th>زمان</Th>
                  <Th>ویزیتور</Th>
                  <Th>فروشگاه</Th>
                  <Th>تماس و نشانی</Th>
                  <Th>روز بازدید</Th>
                  <Th>وضعیت</Th>
                  <Th className="w-44" />
                </tr>
              </thead>
              <tbody>
                {list.data.items.map((r) => (
                  <Tr key={r.id}>
                    <Td className="text-ink-soft">{formatDateTime(r.created_at)}</Td>
                    <Td>{r.visitor_name}</Td>
                    <Td className="font-medium">
                      {r.name}
                      {r.owner_name ? <div className="text-xs font-normal text-ink-faint">{r.owner_name}</div> : null}
                    </Td>
                    <Td className="text-sm">
                      {r.mobile || r.phone ? <div dir="ltr" className="text-end tabular">{toFaDigits(r.mobile ?? r.phone ?? "")}</div> : null}
                      <div className="text-ink-soft">{[r.city, r.address].filter(Boolean).join("، ") || "—"}</div>
                      <Place lat={r.latitude} lon={r.longitude} />
                    </Td>
                    <Td>{r.visit_weekday != null ? WEEKDAYS[r.visit_weekday] : "—"}</Td>
                    <Td>
                      <StatusBadge status={r.status} />
                      {r.party_code ? <span className="ms-2 text-xs text-ink-faint" dir="ltr">{r.party_code}</span> : null}
                      {r.decision_note ? <div className="text-xs text-ink-faint">{r.decision_note}</div> : null}
                    </Td>
                    <Td>
                      {r.status === "pending" ? (
                        <div className="flex gap-1.5">
                          <Button size="sm" onClick={() => setOpen({ r, kind: "approve" })}>تأیید</Button>
                          <Button size="sm" variant="outline" onClick={() => setOpen({ r, kind: "reject" })}>رد</Button>
                        </div>
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
      {open ? <RequestDialog r={open.r} kind={open.kind} onClose={() => setOpen(null)} /> : null}
    </Card>
  );
}

function RequestDialog({ r, kind, onClose }: { r: CustomerRequest; kind: "approve" | "reject"; onClose: () => void }) {
  const qc = useQueryClient();
  const currency = useCurrency();
  const [code, setCode] = React.useState("");
  const [credit, setCredit] = React.useState("");
  const [note, setNote] = React.useState("");
  const save = useMutation({
    mutationFn: () =>
      api.post<CustomerRequest>(
        `/distribution/customer-requests/${r.id}/${kind}`,
        kind === "approve"
          ? { code: code.trim(), credit_limit: credit ? inputToRials(credit, currency) : null, note: note.trim() || null }
          : { note: note.trim() },
        { version: r.row_version },
      ),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["distribution"] });
      toast.success(kind === "approve" ? "طرف‌حساب ساخته و تخصیص داده شد" : "رد شد");
      onClose();
    },
    onError,
  });
  const valid = kind === "reject" ? note.trim().length >= 2 : /^[A-Za-z0-9-]{1,16}$/.test(code.trim());
  return (
    <Dialog open onOpenChange={(o) => !o && onClose()}>
      <DialogContent title={kind === "approve" ? "تأیید مشتری جدید" : "رد درخواست"} description={`${r.name} · ویزیتور ${r.visitor_name}`}>
        <div className="flex flex-col gap-3 text-sm">
          {kind === "approve" ? (
            <>
              <Field label="کد تفصیلی طرف‌حساب">
                <Input dir="ltr" value={code} onChange={(e) => setCode(e.target.value)} placeholder="C-120" />
              </Field>
              <Field label={`سقف اعتبار (${currency === "IRT" ? "تومان" : "ریال"}؛ خالی = بدون فروش نسیه)`}>
                <MoneyInput value={credit} onChange={setCredit} />
              </Field>
              <Field label="توضیح (اختیاری)">
                <Input value={note} onChange={(e) => setNote(e.target.value)} />
              </Field>
            </>
          ) : (
            <Field label="علت (به ویزیتور نمایش داده می‌شود)">
              <Input value={note} onChange={(e) => setNote(e.target.value)} />
            </Field>
          )}
        </div>
        <DialogFooter>
          <Button loading={save.isPending} disabled={!valid} onClick={() => save.mutate()}>
            {kind === "approve" ? "ساخت طرف‌حساب" : "رد درخواست"}
          </Button>
          <Button variant="ghost" onClick={onClose}>انصراف</Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}

// --- targets ----------------------------------------------------------------------------

const MONTHS = ["فروردین", "اردیبهشت", "خرداد", "تیر", "مرداد", "شهریور", "مهر", "آبان", "آذر", "دی", "بهمن", "اسفند"];

function thisJalaliMonth(): { year: number; month: number } {
  const parts = new Intl.DateTimeFormat("en-u-ca-persian-nu-latn", { year: "numeric", month: "numeric", timeZone: "Asia/Tehran" }).formatToParts(new Date());
  const n = (t: string) => Number(parts.find((p) => p.type === t)?.value.replace(/\D/g, "") ?? 0);
  return { year: n("year"), month: n("month") };
}

export function TargetsPage() {
  const currency = useCurrency();
  const now = React.useMemo(thisJalaliMonth, []);
  const [year, setYear] = React.useState(now.year);
  const [month, setMonth] = React.useState(now.month);
  const list = useQuery({
    queryKey: ["distribution", "targets", year, month],
    queryFn: () => api.get<Target[]>(`/distribution/targets?year=${year}&month=${month}`),
  });
  return (
    <Card>
      <div className="flex flex-wrap items-end gap-3 p-4">
        <Field label="ماه">
          <Select value={month} onChange={(e) => setMonth(Number(e.target.value))}>
            {MONTHS.map((m, i) => (
              <option key={m} value={i + 1}>{m}</option>
            ))}
          </Select>
        </Field>
        <Field label="سال">
          <Select value={year} onChange={(e) => setYear(Number(e.target.value))}>
            {[now.year - 1, now.year, now.year + 1].map((y) => (
              <option key={y} value={y}>{toFaDigits(y)}</option>
            ))}
          </Select>
        </Field>
        <p className="max-w-2xl text-sm text-ink-soft">
          پیشرفت هر ویزیتور «مبلغ فاکتورشده» از سفارش‌های خود اوست؛ فروش حضوری و سفارش ویزیتور دیگر در آن حساب نمی‌شود. ویزیتور هدف و پیشرفتش را در اپ می‌بیند.
        </p>
      </div>
      <div className="surface mx-4 mb-4 overflow-hidden rounded-2xl">
        {list.isLoading ? (
          <Spinner />
        ) : list.isError ? (
          <ErrorBox error={list.error} />
        ) : !list.data?.length ? (
          <EmptyState icon={TargetIcon} title="ویزیتوری تعریف نشده" />
        ) : (
          <Table>
            <thead>
              <tr>
                <Th>ویزیتور</Th>
                <Th className="w-56">هدف ({currency === "IRT" ? "تومان" : "ریال"})</Th>
                <Th className="w-40">فاکتورشده</Th>
                <Th>پیشرفت</Th>
              </tr>
            </thead>
            <tbody>
              {list.data.map((t) => (
                <TargetRow key={`${t.visitor_id}-${year}-${month}`} t={t} year={year} month={month} />
              ))}
            </tbody>
          </Table>
        )}
      </div>
    </Card>
  );
}

function TargetRow({ t, year, month }: { t: Target; year: number; month: number }) {
  const qc = useQueryClient();
  const currency = useCurrency();
  const [value, setValue] = React.useState(t.amount ? rialsToInput(t.amount, currency) : "");
  const save = useMutation({
    mutationFn: () =>
      api.put<Target>(
        `/distribution/visitors/${t.visitor_id}/targets/${year}/${month}`,
        { amount: inputToRials(value || "0", currency) },
        t.row_version ?? "",
      ),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["distribution", "targets"] });
      toast.success(`هدف ${t.visitor_name} ثبت شد`);
    },
    onError,
  });
  const pct = t.amount && Number(t.amount) > 0 ? Math.min(100, Math.round((Number(t.invoiced) / Number(t.amount)) * 100)) : null;
  const changed = value !== (t.amount ? rialsToInput(t.amount, currency) : "");
  return (
    <Tr>
      <Td className="font-medium">{t.visitor_name}</Td>
      <Td>
        <div className="flex items-center gap-1.5">
          <MoneyInput compact value={value} onChange={setValue} aria-label={`هدف ${t.visitor_name}`} />
          <Button size="sm" variant={changed ? "primary" : "ghost"} disabled={!changed || !value} loading={save.isPending} onClick={() => save.mutate()}>
            ذخیره
          </Button>
        </div>
      </Td>
      <Td className="tabular">{formatMoney(t.invoiced, currency)}</Td>
      <Td>
        {pct == null ? (
          <span className="text-ink-faint">هدف تعیین نشده</span>
        ) : (
          <div className="flex items-center gap-2">
            <div className="h-2.5 w-40 overflow-hidden rounded-full bg-brand-100 dark:bg-white/10" role="progressbar" aria-valuenow={pct} aria-valuemin={0} aria-valuemax={100}>
              <div className="h-full rounded-full bg-brand-600" style={{ width: `${pct}%` }} />
            </div>
            <span className="tabular text-sm font-semibold">{toFaDigits(pct)}٪</span>
          </div>
        )}
      </Td>
    </Tr>
  );
}
