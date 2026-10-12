import { keepPreviousData, useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  BellRing,
  CheckCircle2,
  Download,
  FileSpreadsheet,
  NotebookPen,
  Pencil,
  Plus,
  RotateCcw,
  ScrollText,
  Upload,
  Users,
} from "lucide-react";
import * as React from "react";
import { Link, NavLink, Outlet, useNavigate, useParams } from "react-router";
import { toast } from "sonner";
import { PageTitle } from "@/components/layout/AppShell";
import { Button } from "@/components/ui/button";
import { Card, CardBody, CardHeader } from "@/components/ui/card";
import { Dialog, DialogContent, DialogFooter } from "@/components/ui/dialog";
import { Badge, EmptyState, ErrorBox, Spinner } from "@/components/ui/feedback";
import { Checkbox, Field, Input, Label, Select } from "@/components/ui/form-controls";
import { Pagination, Table, Td, Th, Tr } from "@/components/ui/table";
import { useCurrency } from "@/features/accounting/api";
import { JalaliDateInput, MoneyInput } from "@/features/accounting/inputs";
import { useCan } from "@/features/auth/auth";
import { ApiError, api, newIdempotencyKey, type Page, upload } from "@/lib/api";
import { type DisplayCurrency, formatDateTime, formatMoney, toFaDigits } from "@/lib/format";
import { isoToJalaliFa, todayIso } from "@/lib/jalali";
import { inputToRials, rialsToInput } from "@/lib/money";
import { cn } from "@/lib/utils";
import { type Note, type Party, type PartySummary, type PartyType, type Statement, usePartyGroups } from "./api";
import { absRials, apiErrorText, BALANCE_LABEL, balanceSide } from "./helpers";

const onError = (e: unknown) => toast.error(apiErrorText(e));
const VIEW = ["parties.view", "parties.manage"];

const TABS = [
  { to: "/parties/list", label: "فهرست طرف‌حساب‌ها", perm: VIEW },
  { to: "/parties/follow-ups", label: "پیگیری‌ها", perm: VIEW },
  { to: "/parties/import", label: "ورود از Excel", perm: ["import.run"] },
];

export function PartiesLayout() {
  const can = useCan();
  return (
    <>
      <PageTitle title="طرف‌حساب‌ها" subtitle="مشتریان و تأمین‌کنندگان، گردش حساب و پیگیری‌ها" />
      <nav className="no-print glass mb-4 flex gap-1 overflow-x-auto rounded-2xl p-1.5" aria-label="بخش‌های طرف‌حساب‌ها">
        {TABS.filter((t) => can(t.perm)).map((t) => (
          <NavLink
            key={t.to}
            to={t.to}
            className={({ isActive }) =>
              cn(
                "rounded-xl px-4 py-2 text-sm font-medium whitespace-nowrap transition",
                isActive ? "bg-white text-brand-600 shadow-sm dark:bg-white/15 dark:text-white" : "text-ink-soft hover:text-ink",
              )
            }
          >
            {t.label}
          </NavLink>
        ))}
      </nav>
      <Outlet />
    </>
  );
}

// --- shared bits ------------------------------------------------------------------

const TYPE_LABEL: Record<PartyType, string> = { person: "حقیقی", company: "حقوقی" };

function RoleBadges({ p }: { p: Pick<PartySummary, "is_customer" | "is_supplier" | "is_active"> }) {
  return (
    <span className="inline-flex flex-wrap gap-1">
      {p.is_customer ? <Badge tone="brand" icon={false}>مشتری</Badge> : null}
      {p.is_supplier ? <Badge tone="info" icon={false}>تأمین‌کننده</Badge> : null}
      {!p.is_active ? <Badge tone="warning">غیرفعال</Badge> : null}
    </span>
  );
}

/** Balance with its side in text (never colour alone). */
function BalanceText({ rials, currency, className }: { rials: string; currency: DisplayCurrency; className?: string }) {
  const side = balanceSide(rials);
  return (
    <span className={cn("tabular inline-flex flex-wrap items-center gap-1.5", className)}>
      {formatMoney(absRials(rials), currency)}
      <span className={cn("text-xs", side === "debtor" ? "text-warning" : side === "creditor" ? "text-info" : "text-ink-faint")}>
        {BALANCE_LABEL[side]}
      </span>
    </span>
  );
}

// --- list -------------------------------------------------------------------------

const PAGE_SIZE = 50;

export function PartiesListPage() {
  const can = useCan();
  const currency = useCurrency();
  const nav = useNavigate();
  const [page, setPage] = React.useState(1);
  const [q, setQ] = React.useState("");
  const [role, setRole] = React.useState("");
  const [balance, setBalance] = React.useState("");
  const [active, setActive] = React.useState("true");
  const [creating, setCreating] = React.useState(false);

  const params = new URLSearchParams({ page: String(page), page_size: String(PAGE_SIZE) });
  if (q.trim()) params.set("q", q.trim());
  if (role) params.set("role", role);
  if (balance) params.set("balance", balance);
  if (active) params.set("active", active);
  const list = useQuery({
    queryKey: ["parties", "list", params.toString()],
    queryFn: () => api.get<Page<PartySummary>>(`/parties?${params}`),
    placeholderData: keepPreviousData,
  });
  const reset = <T,>(set: (v: T) => void) => (v: T) => {
    set(v);
    setPage(1);
  };

  return (
    <Card>
      <div className="flex flex-wrap items-end gap-3 p-4">
        <Field label="جستجو">
          <Input className="w-56" placeholder="نام، کد یا شماره همراه" value={q} onChange={(e) => reset(setQ)(e.target.value)} />
        </Field>
        <Field label="نقش">
          <Select value={role} onChange={(e) => reset(setRole)(e.target.value)}>
            <option value="">همه</option>
            <option value="customer">مشتری</option>
            <option value="supplier">تأمین‌کننده</option>
          </Select>
        </Field>
        <Field label="مانده">
          <Select value={balance} onChange={(e) => reset(setBalance)(e.target.value)}>
            <option value="">همه</option>
            <option value="debtor">بدهکار</option>
            <option value="creditor">بستانکار</option>
          </Select>
        </Field>
        <Field label="وضعیت">
          <Select value={active} onChange={(e) => reset(setActive)(e.target.value)}>
            <option value="true">فعال</option>
            <option value="false">غیرفعال</option>
            <option value="">همه</option>
          </Select>
        </Field>
        <div className="flex-1" />
        {can("parties.manage") ? (
          <Button onClick={() => setCreating(true)}>
            <Plus /> طرف‌حساب جدید
          </Button>
        ) : null}
      </div>
      <div className="surface mx-4 mb-4 overflow-hidden rounded-2xl">
        {list.isLoading ? (
          <Spinner />
        ) : list.isError ? (
          <ErrorBox error={list.error} />
        ) : !list.data?.items.length ? (
          <EmptyState icon={Users} title="طرف‌حسابی یافت نشد" />
        ) : (
          <>
            <Table>
              <thead>
                <tr>
                  <Th className="w-24">کد</Th>
                  <Th>نام</Th>
                  <Th className="w-20">نوع</Th>
                  <Th>نقش</Th>
                  <Th>گروه</Th>
                  <Th className="w-32">همراه</Th>
                  <Th className="w-36">سقف اعتبار</Th>
                  <Th className="w-48">مانده</Th>
                </tr>
              </thead>
              <tbody>
                {list.data.items.map((p) => (
                  <Tr key={p.id} className="cursor-pointer" onClick={() => nav(`/parties/${p.id}`)}>
                    <Td className="tabular text-ink-soft" dir="ltr">{p.code}</Td>
                    <Td className="font-medium">
                      <Link to={`/parties/${p.id}`} className="hover:underline" onClick={(e) => e.stopPropagation()}>
                        {p.name}
                      </Link>
                    </Td>
                    <Td className="text-ink-soft">{TYPE_LABEL[p.party_type]}</Td>
                    <Td><RoleBadges p={p} /></Td>
                    <Td className="text-ink-soft">{p.group_name ?? "—"}</Td>
                    <Td className="tabular" dir="ltr">{p.mobile ? toFaDigits(p.mobile) : "—"}</Td>
                    <Td className="tabular">{p.credit_limit ? formatMoney(p.credit_limit, currency) : "—"}</Td>
                    <Td><BalanceText rials={p.balance} currency={currency} className="font-semibold" /></Td>
                  </Tr>
                ))}
              </tbody>
            </Table>
            <Pagination page={page} pageSize={PAGE_SIZE} total={list.data.total} onPage={setPage} />
          </>
        )}
      </div>
      {creating ? (
        <PartyDialog
          onClose={() => setCreating(false)}
          onSaved={(p) => {
            setCreating(false);
            nav(`/parties/${p.id}`);
          }}
        />
      ) : null}
    </Card>
  );
}

// --- create / edit dialog ---------------------------------------------------------

type FormState = {
  code: string;
  name: string;
  party_type: PartyType;
  is_customer: boolean;
  is_supplier: boolean;
  is_active: boolean;
  group_id: string;
  national_id: string;
  economic_code: string;
  registration_no: string;
  phone: string;
  mobile: string;
  email: string;
  postal_code: string;
  city: string;
  address: string;
  payment_terms_days: string;
  credit_limit: string;
};

function initialForm(p: Party | undefined, currency: DisplayCurrency): FormState {
  return {
    code: p?.code ?? "",
    name: p?.name ?? "",
    party_type: p?.party_type ?? "person",
    is_customer: p?.is_customer ?? true,
    is_supplier: p?.is_supplier ?? false,
    is_active: p?.is_active ?? true,
    group_id: p?.group_id ?? "",
    national_id: p?.national_id ?? "",
    economic_code: p?.economic_code ?? "",
    registration_no: p?.registration_no ?? "",
    phone: p?.phone ?? "",
    mobile: p?.mobile ?? "",
    email: p?.email ?? "",
    postal_code: p?.postal_code ?? "",
    city: p?.city ?? "",
    address: p?.address ?? "",
    payment_terms_days: p?.payment_terms_days != null ? String(p.payment_terms_days) : "",
    credit_limit: p?.credit_limit ? rialsToInput(p.credit_limit, currency) : "",
  };
}

function PartyDialog({ party, onClose, onSaved }: { party?: Party; onClose: () => void; onSaved?: (p: Party) => void }) {
  const qc = useQueryClient();
  const currency = useCurrency();
  const groups = usePartyGroups();
  const editing = !!party;
  const [f, setF] = React.useState<FormState>(() => initialForm(party, currency));
  const keyRef = React.useRef(newIdempotencyKey());
  const set = <K extends keyof FormState>(k: K, v: FormState[K]) => setF((s) => ({ ...s, [k]: v }));
  const txt = (k: keyof FormState) => ({
    value: f[k] as string,
    onChange: (e: React.ChangeEvent<HTMLInputElement | HTMLTextAreaElement>) => set(k, e.target.value as never),
  });

  const save = useMutation({
    mutationFn: () => {
      const opt = (v: string) => (v.trim() === "" ? null : v.trim());
      let credit: string | null = null;
      if (f.is_customer && f.credit_limit.trim() !== "") {
        credit = inputToRials(f.credit_limit, currency);
        if (credit === null) throw new Error("سقف اعتبار نامعتبر است");
      }
      const body: Record<string, unknown> = {
        name: f.name.trim(),
        party_type: f.party_type,
        is_customer: f.is_customer,
        is_supplier: f.is_supplier,
        group_id: f.group_id || null,
        national_id: opt(f.national_id),
        economic_code: opt(f.economic_code),
        registration_no: opt(f.registration_no),
        phone: opt(f.phone),
        mobile: opt(f.mobile),
        email: opt(f.email),
        postal_code: opt(f.postal_code),
        city: opt(f.city),
        address: opt(f.address),
        payment_terms_days: f.is_supplier && f.payment_terms_days.trim() ? Number(f.payment_terms_days) : null,
        credit_limit: credit,
      };
      if (party) return api.put<Party>(`/parties/${party.id}`, { ...body, is_active: f.is_active }, party.row_version);
      return api.post<Party>("/parties", { ...body, code: f.code.trim() }, { idempotencyKey: keyRef.current });
    },
    onSuccess: (p) => {
      qc.invalidateQueries({ queryKey: ["parties"] });
      toast.success(editing ? "طرف‌حساب ویرایش شد" : "طرف‌حساب تعریف شد");
      onSaved?.(p);
      onClose();
    },
    onError: (e) => toast.error(e instanceof ApiError ? apiErrorText(e) : e instanceof Error ? e.message : "خطا"),
  });

  const roleMissing = !f.is_customer && !f.is_supplier;
  const ready = f.name.trim().length >= 2 && (editing || /^[A-Za-z0-9-]+$/.test(f.code.trim())) && !roleMissing;

  return (
    <Dialog open onOpenChange={(o) => !o && onClose()}>
      <DialogContent title={editing ? `ویرایش ${party.name}` : "طرف‌حساب جدید"} className="max-w-2xl">
        <form
          onSubmit={(e) => {
            e.preventDefault();
            if (ready) save.mutate();
          }}
          className="grid gap-3 sm:grid-cols-2"
        >
          {editing ? (
            <Field label="کد">
              <Input dir="ltr" value={f.code} disabled />
            </Field>
          ) : (
            <Field label="کد" hint="حروف لاتین، رقم و خط تیره">
              <Input dir="ltr" maxLength={16} required {...txt("code")} />
            </Field>
          )}
          <Field label="نام">
            <Input maxLength={150} required {...txt("name")} />
          </Field>
          <Field label="نوع شخص">
            <Select value={f.party_type} onChange={(e) => set("party_type", e.target.value as PartyType)}>
              <option value="person">{TYPE_LABEL.person}</option>
              <option value="company">{TYPE_LABEL.company}</option>
            </Select>
          </Field>
          <Field label="گروه">
            <Select value={f.group_id} onChange={(e) => set("group_id", e.target.value)}>
              <option value="">بدون گروه</option>
              {groups.data?.map((g) => (
                <option key={g.id} value={g.id}>{g.name}</option>
              ))}
            </Select>
          </Field>
          <div className="flex flex-wrap items-center gap-5 sm:col-span-2">
            <label className="flex items-center gap-2 text-sm">
              <Checkbox checked={f.is_customer} onCheckedChange={(v) => set("is_customer", v === true)} /> مشتری
            </label>
            <label className="flex items-center gap-2 text-sm">
              <Checkbox checked={f.is_supplier} onCheckedChange={(v) => set("is_supplier", v === true)} /> تأمین‌کننده
            </label>
            {editing ? (
              <label className="flex items-center gap-2 text-sm">
                <Checkbox checked={f.is_active} onCheckedChange={(v) => set("is_active", v === true)} /> فعال
              </label>
            ) : null}
            {roleMissing ? <span className="text-xs text-danger" role="alert">حداقل یکی از مشتری یا تأمین‌کننده را انتخاب کنید</span> : null}
          </div>
          <Field label={f.party_type === "person" ? "کد ملی" : "شناسه ملی"}>
            <Input dir="ltr" inputMode="numeric" maxLength={20} {...txt("national_id")} />
          </Field>
          <Field label="کد اقتصادی">
            <Input dir="ltr" inputMode="numeric" maxLength={20} {...txt("economic_code")} />
          </Field>
          <Field label="شماره ثبت">
            <Input dir="ltr" maxLength={20} {...txt("registration_no")} />
          </Field>
          <Field label="تلفن">
            <Input dir="ltr" inputMode="tel" maxLength={20} {...txt("phone")} />
          </Field>
          <Field label="تلفن همراه">
            <Input dir="ltr" inputMode="tel" maxLength={20} placeholder="09xxxxxxxxx" {...txt("mobile")} />
          </Field>
          <Field label="ایمیل">
            <Input dir="ltr" type="email" maxLength={120} {...txt("email")} />
          </Field>
          <Field label="کد پستی">
            <Input dir="ltr" inputMode="numeric" maxLength={12} {...txt("postal_code")} />
          </Field>
          <Field label="شهر">
            <Input maxLength={60} {...txt("city")} />
          </Field>
          <Field label="نشانی" className="sm:col-span-2">
            <textarea
              className="min-h-16 w-full rounded-xl border border-[var(--line)] bg-[var(--surface)] px-3 py-2 text-sm text-ink outline-none focus:border-brand-400 focus:ring-4 focus:ring-brand-400/15"
              maxLength={500}
              {...txt("address")}
            />
          </Field>
          {f.is_supplier ? (
            <Field label="مهلت پرداخت (روز)" hint="برای تأمین‌کننده">
              <Input
                dir="ltr"
                inputMode="numeric"
                className="tabular"
                value={f.payment_terms_days}
                onChange={(e) => set("payment_terms_days", e.target.value.replace(/[^\d]/g, "").slice(0, 3))}
              />
            </Field>
          ) : null}
          {f.is_customer ? (
            <Field label={`سقف اعتبار (${currency === "IRT" ? "تومان" : "ریال"})`} hint="خالی یعنی فروش اعتباری مجاز نیست">
              <MoneyInput value={f.credit_limit} onChange={(v) => set("credit_limit", v)} />
            </Field>
          ) : null}
          <div className="sm:col-span-2">
            <DialogFooter>
              <Button type="submit" disabled={!ready} loading={save.isPending}>
                {editing ? "ذخیره تغییرات" : "تعریف طرف‌حساب"}
              </Button>
              <Button type="button" variant="ghost" onClick={onClose}>
                انصراف
              </Button>
            </DialogFooter>
          </div>
        </form>
      </DialogContent>
    </Dialog>
  );
}

// --- detail -----------------------------------------------------------------------

export function PartyDetailPage() {
  const { id } = useParams();
  const can = useCan();
  const currency = useCurrency();
  const [editing, setEditing] = React.useState(false);
  const party = useQuery({ queryKey: ["parties", "party", id], queryFn: () => api.get<Party>(`/parties/${id}`) });
  if (party.isLoading) return <Spinner />;
  if (party.isError || !party.data) return <ErrorBox error={party.error} />;
  const p = party.data;
  const info: [string, string | null, boolean?][] = [
    [p.party_type === "person" ? "کد ملی" : "شناسه ملی", p.national_id, true],
    ["کد اقتصادی", p.economic_code, true],
    ["شماره ثبت", p.registration_no, true],
    ["تلفن", p.phone, true],
    ["تلفن همراه", p.mobile, true],
    ["ایمیل", p.email, true],
    ["کد پستی", p.postal_code, true],
    ["شهر", p.city],
    ["نشانی", p.address],
    ["گروه", p.group_name],
    ["مهلت پرداخت", p.payment_terms_days != null ? `${toFaDigits(p.payment_terms_days)} روز` : null],
    ["سقف اعتبار", p.is_customer ? (p.credit_limit ? formatMoney(p.credit_limit, currency) : "فروش اعتباری ندارد") : null],
  ];

  return (
    <div className="flex flex-col gap-4">
      <Card className="p-4">
        <div className="flex flex-wrap items-center gap-3">
          <h2 className="text-lg font-bold text-ink">{p.name}</h2>
          <span className="tabular text-sm text-ink-faint" dir="ltr">{p.code}</span>
          <Badge tone="neutral" icon={false}>{TYPE_LABEL[p.party_type]}</Badge>
          <RoleBadges p={p} />
          <div className="flex-1" />
          <div className="surface rounded-xl px-3 py-1.5 text-sm">
            مانده: <BalanceText rials={p.balance} currency={currency} className="font-bold" />
          </div>
          {can("parties.manage") ? (
            <Button variant="outline" onClick={() => setEditing(true)}>
              <Pencil /> ویرایش
            </Button>
          ) : null}
        </div>
      </Card>
      <div className="grid gap-4 xl:grid-cols-[22rem_1fr]">
        <div className="flex flex-col gap-4">
          <Card>
            <CardHeader
              title="هویت و تماس"
              description={p.masked ? "اطلاعات حساس برای شما پوشیده نمایش داده می‌شود" : undefined}
            />
            <CardBody>
              <dl className="surface grid grid-cols-[auto_1fr] gap-x-4 gap-y-2 rounded-2xl p-4 text-sm">
                {info.map(([label, value, ltr]) => (
                  <React.Fragment key={label}>
                    <dt className="text-ink-faint">{label}</dt>
                    <dd className={cn("text-ink", ltr && "tabular")} dir={ltr && value ? "ltr" : undefined}>
                      {value ? (ltr ? toFaDigits(value) : value) : "—"}
                    </dd>
                  </React.Fragment>
                ))}
              </dl>
            </CardBody>
          </Card>
          <NotesCard partyId={p.id} />
        </div>
        <StatementCard partyId={p.id} />
      </div>
      {editing ? <PartyDialog party={p} onClose={() => setEditing(false)} /> : null}
    </div>
  );
}

function StatementCard({ partyId }: { partyId: string }) {
  const currency = useCurrency();
  const [from, setFrom] = React.useState<string | null>(null);
  const [to, setTo] = React.useState<string | null>(null);
  const params = new URLSearchParams();
  if (from) params.set("date_from", from);
  if (to) params.set("date_to", to);
  const st = useQuery({
    queryKey: ["parties", "statement", partyId, params.toString()],
    queryFn: () => api.get<Statement>(`/parties/${partyId}/statement?${params}`),
    placeholderData: keepPreviousData,
  });
  const money = (v: string) => formatMoney(v, currency);
  return (
    <Card>
      <CardHeader icon={<ScrollText className="size-5" />} title="گردش حساب" description="فقط اسناد قطعی" />
      <CardBody className="flex flex-col gap-3">
        <div className="flex flex-wrap items-end gap-3">
          <Field label="از تاریخ">
            <JalaliDateInput value={from} onChange={setFrom} />
          </Field>
          <Field label="تا تاریخ">
            <JalaliDateInput value={to} onChange={setTo} />
          </Field>
          {from || to ? (
            <Button variant="ghost" onClick={() => { setFrom(null); setTo(null); }}>
              <RotateCcw /> همه دوره‌ها
            </Button>
          ) : null}
        </div>
        <div className="surface overflow-hidden rounded-2xl">
          {st.isLoading ? (
            <Spinner />
          ) : st.isError || !st.data ? (
            <ErrorBox error={st.error} />
          ) : (
            <Table>
              <thead>
                <tr>
                  <Th className="w-28">تاریخ</Th>
                  <Th className="w-20">سند</Th>
                  <Th>شرح</Th>
                  <Th>حساب</Th>
                  <Th className="w-32">بدهکار</Th>
                  <Th className="w-32">بستانکار</Th>
                  <Th className="w-44">مانده</Th>
                </tr>
              </thead>
              <tbody>
                <Tr>
                  <Td colSpan={6} className="font-medium text-ink-soft">مانده ابتدای دوره</Td>
                  <Td><BalanceText rials={st.data.opening_balance} currency={currency} /></Td>
                </Tr>
                {st.data.lines.length === 0 ? (
                  <Tr>
                    <Td colSpan={7} className="py-6 text-center text-ink-faint">در این بازه گردشی ثبت نشده است</Td>
                  </Tr>
                ) : (
                  st.data.lines.map((l, i) => (
                    <Tr key={`${l.voucher_id}-${i}`}>
                      <Td className="tabular">{isoToJalaliFa(l.document_date)}</Td>
                      <Td className="tabular">
                        <Link className="text-brand-600 hover:underline" to={`/accounting/vouchers/${l.voucher_id}`}>
                          {l.voucher_number != null ? toFaDigits(l.voucher_number) : "سند"}
                        </Link>
                      </Td>
                      <Td>{l.description ?? "—"}</Td>
                      <Td className="text-ink-soft">
                        <span className="tabular" dir="ltr">{toFaDigits(l.account_code)}</span> {l.account_name}
                      </Td>
                      <Td className="tabular">{Number(l.debit) ? money(l.debit) : "—"}</Td>
                      <Td className="tabular">{Number(l.credit) ? money(l.credit) : "—"}</Td>
                      <Td><BalanceText rials={l.balance} currency={currency} /></Td>
                    </Tr>
                  ))
                )}
                <Tr className="font-semibold">
                  <Td colSpan={4}>جمع گردش</Td>
                  <Td className="tabular">{money(st.data.total_debit)}</Td>
                  <Td className="tabular">{money(st.data.total_credit)}</Td>
                  <Td />
                </Tr>
                <Tr className="font-bold">
                  <Td colSpan={6}>مانده پایان دوره</Td>
                  <Td><BalanceText rials={st.data.closing_balance} currency={currency} /></Td>
                </Tr>
              </tbody>
            </Table>
          )}
        </div>
      </CardBody>
    </Card>
  );
}

function useNoteDone() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({ id, done }: { id: string; done: boolean }) => api.post<Note>(`/parties/notes/${id}/done`, { done }),
    onSuccess: (n) => {
      qc.invalidateQueries({ queryKey: ["parties"] });
      toast.success(n.done ? "پیگیری انجام‌شده ثبت شد" : "پیگیری دوباره باز شد");
    },
    onError,
  });
}

function NotesCard({ partyId }: { partyId: string }) {
  const qc = useQueryClient();
  const notes = useQuery({ queryKey: ["parties", "notes", partyId], queryFn: () => api.get<Note[]>(`/parties/${partyId}/notes`) });
  const [body, setBody] = React.useState("");
  const [follow, setFollow] = React.useState<string | null>(null);
  const add = useMutation({
    mutationFn: () => api.post<Note>(`/parties/${partyId}/notes`, { body: body.trim(), follow_up_on: follow }),
    onSuccess: () => {
      setBody("");
      setFollow(null);
      qc.invalidateQueries({ queryKey: ["parties"] });
      toast.success("یادداشت ثبت شد");
    },
    onError,
  });
  const done = useNoteDone();
  return (
    <Card>
      <CardHeader icon={<NotebookPen className="size-5" />} title="یادداشت‌ها و پیگیری‌ها" />
      <CardBody className="flex flex-col gap-3">
        <form
          className="flex flex-col gap-2"
          onSubmit={(e) => {
            e.preventDefault();
            if (body.trim().length >= 2) add.mutate();
          }}
        >
          <Label htmlFor="party-note">یادداشت</Label>
          <textarea
            id="party-note"
            className="min-h-16 w-full rounded-xl border border-[var(--line)] bg-[var(--surface)] px-3 py-2 text-sm text-ink outline-none focus:border-brand-400 focus:ring-4 focus:ring-brand-400/15"
            maxLength={1000}
            value={body}
            onChange={(e) => setBody(e.target.value)}
          />
          <div className="flex flex-wrap items-end gap-2">
            <Field label="تاریخ پیگیری (اختیاری)">
              <JalaliDateInput value={follow} onChange={setFollow} className="w-36" />
            </Field>
            <Button type="submit" disabled={body.trim().length < 2} loading={add.isPending}>
              <Plus /> افزودن
            </Button>
          </div>
        </form>
        {notes.isLoading ? (
          <Spinner />
        ) : notes.isError ? (
          <ErrorBox error={notes.error} />
        ) : !notes.data?.length ? (
          <p className="py-4 text-center text-sm text-ink-faint">یادداشتی ثبت نشده است</p>
        ) : (
          <ul className="flex flex-col gap-2">
            {notes.data.map((n) => (
              <li key={n.id} className="surface rounded-xl p-3 text-sm">
                <p className="whitespace-pre-wrap text-ink">{n.body}</p>
                <div className="mt-2 flex flex-wrap items-center gap-2 text-xs text-ink-faint">
                  <span>{n.author} · {formatDateTime(n.created_at)}</span>
                  {n.follow_up_on ? (
                    <>
                      <Badge tone={n.done ? "success" : n.follow_up_on <= todayIso() ? "warning" : "info"}>
                        {n.done ? "انجام شد" : "پیگیری"} {isoToJalaliFa(n.follow_up_on)}
                      </Badge>
                      <Button
                        size="sm"
                        variant="ghost"
                        loading={done.isPending && done.variables?.id === n.id}
                        onClick={() => done.mutate({ id: n.id, done: !n.done })}
                      >
                        {n.done ? <RotateCcw /> : <CheckCircle2 />} {n.done ? "بازگشایی" : "انجام شد"}
                      </Button>
                    </>
                  ) : null}
                </div>
              </li>
            ))}
          </ul>
        )}
      </CardBody>
    </Card>
  );
}

// --- follow-ups -------------------------------------------------------------------

export function FollowUpsPage() {
  const list = useQuery({ queryKey: ["parties", "follow-ups"], queryFn: () => api.get<Note[]>("/parties/follow-ups") });
  const done = useNoteDone();
  return (
    <Card>
      <CardHeader icon={<BellRing className="size-5" />} title="پیگیری‌های سررسیده" description="پیگیری‌های انجام‌نشده تا امروز" />
      <div className="surface mx-4 mb-4 overflow-hidden rounded-2xl">
        {list.isLoading ? (
          <Spinner />
        ) : list.isError ? (
          <ErrorBox error={list.error} />
        ) : !list.data?.length ? (
          <EmptyState icon={CheckCircle2} title="پیگیری سررسیده‌ای نیست" />
        ) : (
          <Table>
            <thead>
              <tr>
                <Th className="w-28">سررسید</Th>
                <Th>طرف‌حساب</Th>
                <Th>یادداشت</Th>
                <Th className="w-40">ثبت‌کننده</Th>
                <Th className="w-32" />
              </tr>
            </thead>
            <tbody>
              {list.data.map((n) => (
                <Tr key={n.id}>
                  <Td className="tabular">
                    {n.follow_up_on ? (
                      <Badge tone={n.follow_up_on < todayIso() ? "warning" : "info"}>{isoToJalaliFa(n.follow_up_on)}</Badge>
                    ) : "—"}
                  </Td>
                  <Td>
                    <Link className="font-medium text-brand-600 hover:underline" to={`/parties/${n.party_id}`}>{n.party_name}</Link>
                  </Td>
                  <Td className="whitespace-pre-wrap">{n.body}</Td>
                  <Td className="text-ink-soft">{n.author}</Td>
                  <Td>
                    <Button
                      size="sm"
                      variant="outline"
                      loading={done.isPending && done.variables?.id === n.id}
                      onClick={() => done.mutate({ id: n.id, done: true })}
                    >
                      <CheckCircle2 /> انجام شد
                    </Button>
                  </Td>
                </Tr>
              ))}
            </tbody>
          </Table>
        )}
      </div>
    </Card>
  );
}

// --- Excel import -----------------------------------------------------------------

type Preview = {
  total_rows: number;
  valid_rows: number;
  to_create: number;
  to_update: number;
  errors: { row: number; column: string; message: string }[];
};
type ImportResult = { created: number; updated: number; document_id: string | null };

export function PartiesImportPage() {
  const qc = useQueryClient();
  const can = useCan();
  const [file, setFile] = React.useState<File | null>(null);
  const [preview, setPreview] = React.useState<Preview | null>(null);
  const [result, setResult] = React.useState<ImportResult | null>(null);
  const [openingDate, setOpeningDate] = React.useState<string | null>(todayIso());
  const keyRef = React.useRef(newIdempotencyKey());
  const inputRef = React.useRef<HTMLInputElement>(null);

  const check = useMutation({
    mutationFn: (f: File) => upload<Preview>("/parties/import/preview", f),
    onSuccess: setPreview,
    onError,
  });
  const commit = useMutation({
    mutationFn: () => upload<ImportResult>("/parties/import/commit", file as File, { opening_date: openingDate ?? "" }, keyRef.current),
    onSuccess: (r) => {
      setResult(r);
      keyRef.current = newIdempotencyKey();
      qc.invalidateQueries({ queryKey: ["parties"] });
      toast.success("ورود طرف‌حساب‌ها انجام شد");
    },
    onError,
  });

  return (
    <Card>
      <CardHeader
        icon={<FileSpreadsheet className="size-5" />}
        title="ورود طرف‌حساب‌ها از Excel"
        description="کد، نام، نوع، نقش، گروه، اطلاعات هویتی و تماس، سقف اعتبار و مانده اول دوره"
        actions={
          <Button variant="outline" size="sm" asChild>
            <a href="/api/v1/parties/import/template">
              <Download /> دانلود قالب
            </a>
          </Button>
        }
      />
      <CardBody className="flex flex-col gap-4">
        <Field label="تاریخ سند افتتاحیه (مانده‌های اول دوره)" className="max-w-xs">
          <JalaliDateInput value={openingDate} onChange={setOpeningDate} />
        </Field>
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
              setResult(null);
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
              <Badge tone="success">{toFaDigits(preview.valid_rows)} ردیف معتبر</Badge>
              <Badge tone="brand" icon={false}>{toFaDigits(preview.to_create)} طرف‌حساب جدید</Badge>
              <Badge tone="brand" icon={false}>{toFaDigits(preview.to_update)} به‌روزرسانی</Badge>
              {preview.errors.length ? <Badge tone="danger">{toFaDigits(preview.errors.length)} خطا</Badge> : null}
            </div>
            {preview.errors.length ? (
              <div className="surface max-h-72 overflow-y-auto rounded-2xl">
                <table className="w-full text-sm">
                  <thead>
                    <tr className="text-xs text-ink-faint">
                      <th className="w-20 px-3 py-2 text-start">ردیف</th>
                      <th className="w-40 px-3 py-2 text-start">ستون</th>
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
                ? "ورود فقط وقتی انجام می‌شود که هیچ ردیفی خطا نداشته باشد. فایل را اصلاح و دوباره انتخاب کنید."
                : "همه ردیف‌ها معتبرند. با تأیید، همه با هم ثبت می‌شوند (همه یا هیچ)."}
            </p>
            {!can("parties.manage") ? (
              <p className="text-sm text-warning">ثبت نهایی نیازمند مجوز «مدیریت طرف‌حساب‌ها» است.</p>
            ) : null}
            <Button
              className="self-start"
              disabled={!!preview.errors.length || !preview.valid_rows || !openingDate || !can("parties.manage")}
              loading={commit.isPending}
              onClick={() => commit.mutate()}
            >
              <CheckCircle2 /> تأیید و ثبت
            </Button>
          </div>
        ) : null}
        {result ? (
          <div className="flex flex-col gap-1 rounded-xl bg-success/10 p-3 text-sm text-success" role="status">
            <span>
              {toFaDigits(result.created)} طرف‌حساب جدید ثبت و {toFaDigits(result.updated)} طرف‌حساب به‌روز شد.
            </span>
            {result.document_id ? (
              <span>
                مانده‌های اول دوره در یک سند حسابداری <b>پیش‌نویس</b> ذخیره شد و هنوز در مانده‌ها اثر ندارد؛ حسابدار باید آن را بررسی و قطعی کند.{" "}
                <Link className="underline" to={`/accounting/vouchers/${result.document_id}`}>
                  بررسی سند افتتاحیه
                </Link>
              </span>
            ) : null}
          </div>
        ) : null}
      </CardBody>
    </Card>
  );
}
