import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { ArrowRight, CheckCheck, Lock, Plus, Printer, Save, Trash2, Undo2 } from "lucide-react";
import * as React from "react";
import { Link, useNavigate, useParams } from "react-router";
import { toast } from "sonner";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { Dialog, DialogContent, DialogFooter } from "@/components/ui/dialog";
import { Badge, ErrorBox, Spinner } from "@/components/ui/feedback";
import { Field, Input, Select } from "@/components/ui/form-controls";
import { useCan } from "@/features/auth/auth";
import type { Branch } from "@/features/settings/types";
import { ApiError, api, newIdempotencyKey } from "@/lib/api";
import { formatDateTime, formatMoney, toFaDigits } from "@/lib/format";
import { isoToJalaliFa, todayIso } from "@/lib/jalali";
import { compareRials, inputToRials, rialsToInput, subRials, sumRials } from "@/lib/money";
import { cn } from "@/lib/utils";
import { SOURCE_LABEL, type Voucher, useAccounts, useCurrency, useDetailAccounts } from "./api";
import { JalaliDateInput, MoneyInput, Picker, accountOptions, detailOptions } from "./inputs";

type Row = {
  key: string;
  account_id: string | null;
  detail_account_id: string | null;
  description: string;
  debit: string; // display currency text
  credit: string;
};

const emptyRow = (): Row => ({
  key: crypto.randomUUID(),
  account_id: null,
  detail_account_id: null,
  description: "",
  debit: "",
  credit: "",
});

function onError(e: unknown) {
  toast.error(e instanceof ApiError ? e.message : "خطا");
}

export function VoucherEditorPage() {
  const { id } = useParams();
  const isNew = !id || id === "new";
  const voucher = useQuery({
    queryKey: ["accounting", "voucher", id],
    queryFn: () => api.get<Voucher>(`/accounting/vouchers/${id}`),
    enabled: !isNew,
  });
  if (!isNew && voucher.isLoading) return <Spinner />;
  if (!isNew && voucher.isError) return <ErrorBox error={voucher.error} />;
  const v = voucher.data;
  if (v && v.status === "final") return <VoucherView voucher={v} />;
  return <VoucherForm key={v?.row_version ?? "new"} voucher={v} />;
}

function VoucherForm({ voucher }: { voucher?: Voucher }) {
  const qc = useQueryClient();
  const navigate = useNavigate();
  const can = useCan();
  const currency = useCurrency();
  const accounts = useAccounts();
  const details = useDetailAccounts();
  const branches = useQuery({ queryKey: ["branches"], queryFn: () => api.get<Branch[]>("/organization/branches") });
  const accById = React.useMemo(() => new Map((accounts.data ?? []).map((a) => [a.id, a])), [accounts.data]);
  const accOpts = React.useMemo(() => accountOptions(accounts.data, { postableOnly: true }), [accounts.data]);
  const detOpts = React.useMemo(() => detailOptions(details.data), [details.data]);

  const [date, setDate] = React.useState<string | null>(voucher?.document_date ?? todayIso());
  const [branchId, setBranchId] = React.useState<string>(voucher?.branch_id ?? "");
  const [description, setDescription] = React.useState(voucher?.description ?? "");
  const [rows, setRows] = React.useState<Row[]>(() =>
    voucher
      ? voucher.lines.map((l) => ({
          key: l.id,
          account_id: l.account_id,
          detail_account_id: l.detail_account_id,
          description: l.description ?? "",
          debit: Number(l.debit) ? rialsToInput(l.debit, currency) : "",
          credit: Number(l.credit) ? rialsToInput(l.credit, currency) : "",
        }))
      : [emptyRow(), emptyRow()],
  );
  const keyRef = React.useRef(newIdempotencyKey());
  const pickerRefs = React.useRef(new Map<string, HTMLInputElement | null>());

  React.useEffect(() => {
    if (!branchId && branches.data?.length) setBranchId(branches.data[0].id);
  }, [branches.data, branchId]);

  const rials = rows.map((r) => ({ d: inputToRials(r.debit, currency), c: inputToRials(r.credit, currency) }));
  const totalDebit = sumRials(rials.map((x) => x.d ?? "0"));
  const totalCredit = sumRials(rials.map((x) => x.c ?? "0"));
  const diff = subRials(totalDebit, totalCredit);
  const balanced = compareRials(diff, "0") === 0 && compareRials(totalDebit, "0") > 0;

  const update = (key: string, patch: Partial<Row>) =>
    setRows((rs) => rs.map((r) => (r.key === key ? { ...r, ...patch } : r)));
  const addRow = (focus = true) => {
    const row = emptyRow();
    // Pre-fill the balancing amount on the opposite side, like most accounting software.
    if (compareRials(diff, "0") > 0) row.credit = rialsToInput(diff, currency);
    else if (compareRials(diff, "0") < 0) row.debit = rialsToInput(diff.slice(1), currency);
    row.description = rows.at(-1)?.description ?? "";
    setRows((rs) => [...rs, row]);
    if (focus) setTimeout(() => pickerRefs.current.get(row.key)?.focus(), 30);
  };

  const payload = () => {
    if (!date) throw new ApiError(0, "invalid_date", "تاریخ سند نامعتبر است");
    const lines = rows
      .filter((r) => r.account_id || r.debit || r.credit)
      .map((r, i) => {
        const d = inputToRials(r.debit, currency);
        const c = inputToRials(r.credit, currency);
        if (!r.account_id) throw new ApiError(0, "account_required", `ردیف ${toFaDigits(i + 1)}: حساب را انتخاب کنید`);
        if (d === null || c === null) throw new ApiError(0, "invalid_amount", `ردیف ${toFaDigits(i + 1)}: مبلغ نامعتبر است`);
        return {
          account_id: r.account_id,
          detail_account_id: r.detail_account_id,
          description: r.description || null,
          debit: d,
          credit: c,
        };
      });
    return { branch_id: branchId, document_date: date, description: description || null, lines };
  };

  const save = useMutation({
    mutationFn: async () => {
      const body = payload();
      return voucher
        ? api.put<Voucher>(`/accounting/vouchers/${voucher.id}`, body, voucher.row_version)
        : api.post<Voucher>("/accounting/vouchers", body, { idempotencyKey: keyRef.current });
    },
    onSuccess: (v) => {
      qc.invalidateQueries({ queryKey: ["accounting", "vouchers"] });
      qc.setQueryData(["accounting", "voucher", v.id], v);
      toast.success("سند پیش‌نویس ذخیره شد");
      if (!voucher) navigate(`/accounting/vouchers/${v.id}`, { replace: true });
    },
    onError,
  });

  const saveAndFinalize = useMutation({
    mutationFn: async () => {
      const body = payload();
      const saved = voucher
        ? await api.put<Voucher>(`/accounting/vouchers/${voucher.id}`, body, voucher.row_version)
        : await api.post<Voucher>("/accounting/vouchers", body, { idempotencyKey: keyRef.current });
      try {
        return await api.post<Voucher>(`/accounting/vouchers/${saved.id}/finalize`, undefined, { version: saved.row_version });
      } catch (e) {
        // The draft is safe; open it so the user can fix and retry.
        qc.setQueryData(["accounting", "voucher", saved.id], saved);
        if (!voucher) navigate(`/accounting/vouchers/${saved.id}`, { replace: true });
        throw e;
      }
    },
    onSuccess: (v) => {
      qc.invalidateQueries({ queryKey: ["accounting"] });
      qc.setQueryData(["accounting", "voucher", v.id], v);
      toast.success(`سند شماره ${toFaDigits(v.number ?? 0)} قطعی شد`);
      navigate(`/accounting/vouchers/${v.id}`, { replace: true });
    },
    onError,
  });

  const remove = useMutation({
    mutationFn: () => api.del(`/accounting/vouchers/${voucher?.id}`, voucher?.row_version ?? ""),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["accounting", "vouchers"] });
      toast.success("پیش‌نویس حذف شد");
      navigate("/accounting/vouchers");
    },
    onError,
  });

  React.useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if ((e.ctrlKey || e.metaKey) && e.key === "s") {
        e.preventDefault();
        save.mutate();
      } else if ((e.ctrlKey || e.metaKey) && e.key === "Enter") {
        e.preventDefault();
        if (can("accounting.voucher.finalize")) saveAndFinalize.mutate();
      } else if (e.altKey && (e.key === "n" || e.key === "ی")) {
        e.preventDefault();
        addRow();
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  });

  const busy = save.isPending || saveAndFinalize.isPending;

  return (
    <div className="flex flex-col gap-4">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div className="flex items-center gap-3">
          <Button variant="ghost" size="icon" asChild aria-label="بازگشت">
            <Link to="/accounting/vouchers">
              <ArrowRight />
            </Link>
          </Button>
          <div>
            <h1 className="text-xl font-extrabold text-ink">{voucher ? "ویرایش سند پیش‌نویس" : "سند حسابداری جدید"}</h1>
            <p className="text-sm text-ink-faint">
              مبالغ به {currency === "IRT" ? "تومان" : "ریال"} · <kbd className="text-xs">Ctrl+S</kbd> ذخیره ·{" "}
              <kbd className="text-xs">Ctrl+Enter</kbd> قطعی · <kbd className="text-xs">Alt+N</kbd> ردیف جدید
            </p>
          </div>
        </div>
        <Badge tone="warning">پیش‌نویس</Badge>
      </div>

      <Card className="grid gap-4 p-5 md:grid-cols-[10rem_14rem_1fr]">
        <Field label="تاریخ سند" htmlFor="v-date">
          <JalaliDateInput id="v-date" value={date} onChange={setDate} invalid={!date} />
        </Field>
        <Field label="شعبه" htmlFor="v-branch">
          <Select id="v-branch" value={branchId} onChange={(e) => setBranchId(e.target.value)}>
            {branches.data?.map((b) => (
              <option key={b.id} value={b.id}>
                {b.name}
              </option>
            ))}
          </Select>
        </Field>
        <Field label="شرح سند" htmlFor="v-desc">
          <Input id="v-desc" value={description} maxLength={500} onChange={(e) => setDescription(e.target.value)} />
        </Field>
      </Card>

      <Card className="overflow-visible p-2">
        <div className="surface overflow-x-auto rounded-2xl">
          <table className="w-full min-w-[60rem] text-sm">
            <thead>
              <tr className="text-xs text-ink-faint">
                <th className="w-10 px-2 py-3">#</th>
                <th className="px-2 py-3 text-start">حساب معین</th>
                <th className="w-56 px-2 py-3 text-start">تفصیلی</th>
                <th className="px-2 py-3 text-start">شرح ردیف</th>
                <th className="w-40 px-2 py-3 text-start">بدهکار</th>
                <th className="w-40 px-2 py-3 text-start">بستانکار</th>
                <th className="w-10" />
              </tr>
            </thead>
            <tbody>
              {rows.map((r, i) => {
                const acc = r.account_id ? accById.get(r.account_id) : undefined;
                const needsDetail = !!acc?.requires_detail && !r.detail_account_id;
                const badD = inputToRials(r.debit, currency) === null;
                const badC = inputToRials(r.credit, currency) === null;
                return (
                  <tr key={r.key} className="border-t border-[var(--line)] align-top">
                    <td className="tabular px-2 py-2 pt-4 text-center text-ink-faint">{toFaDigits(i + 1)}</td>
                    <td className="px-2 py-2">
                      <Picker
                        ref={(el) => {
                          pickerRefs.current.set(r.key, el);
                        }}
                        ariaLabel={`حساب ردیف ${i + 1}`}
                        options={accOpts}
                        value={r.account_id}
                        onChange={(v) => update(r.key, { account_id: v, detail_account_id: null })}
                        placeholder="کد یا نام حساب"
                      />
                    </td>
                    <td className="px-2 py-2">
                      <Picker
                        ariaLabel={`تفصیلی ردیف ${i + 1}`}
                        options={detOpts}
                        value={r.detail_account_id}
                        onChange={(v) => update(r.key, { detail_account_id: v })}
                        placeholder={acc?.requires_detail ? "الزامی" : "اختیاری"}
                        invalid={needsDetail}
                      />
                    </td>
                    <td className="px-2 py-2">
                      <Input value={r.description} maxLength={300} onChange={(e) => update(r.key, { description: e.target.value })} />
                    </td>
                    <td className="px-2 py-2">
                      <MoneyInput compact
                        aria-label={`بدهکار ردیف ${i + 1}`}
                        value={r.debit}
                        aria-invalid={badD || undefined}
                        onChange={(v) => update(r.key, { debit: v, credit: v ? "" : r.credit })}
                      />
                    </td>
                    <td className="px-2 py-2">
                      <MoneyInput compact
                        aria-label={`بستانکار ردیف ${i + 1}`}
                        value={r.credit}
                        aria-invalid={badC || undefined}
                        onChange={(v) => update(r.key, { credit: v, debit: v ? "" : r.debit })}
                        onKeyDown={(e) => {
                          if (e.key === "Enter" && i === rows.length - 1) {
                            e.preventDefault();
                            addRow();
                          }
                        }}
                      />
                    </td>
                    <td className="px-1 py-2">
                      <Button
                        variant="ghost"
                        size="icon"
                        aria-label={`حذف ردیف ${i + 1}`}
                        disabled={rows.length <= 1}
                        onClick={() => setRows((rs) => rs.filter((x) => x.key !== r.key))}
                      >
                        <Trash2 />
                      </Button>
                    </td>
                  </tr>
                );
              })}
            </tbody>
            <tfoot>
              <tr className="border-t-2 border-[var(--line)] bg-[var(--surface-muted)] font-bold">
                <td colSpan={2} className="px-2 py-3">
                  <Button variant="secondary" size="sm" onClick={() => addRow()}>
                    <Plus /> ردیف جدید
                  </Button>
                </td>
                <td colSpan={2} className="px-2 py-3 text-end text-ink-soft">
                  جمع
                </td>
                <td className="tabular px-3 py-3 text-ink">{formatMoney(totalDebit, currency)}</td>
                <td className="tabular px-3 py-3 text-ink">{formatMoney(totalCredit, currency)}</td>
                <td />
              </tr>
            </tfoot>
          </table>
        </div>
        <div
          role="status"
          className={cn(
            "m-2 flex items-center justify-between rounded-xl px-4 py-3 text-sm font-semibold",
            balanced ? "bg-success/10 text-success" : "bg-warning/15 text-[oklch(0.5_0.13_70)] dark:text-warning",
          )}
        >
          <span>{balanced ? "✓ سند تراز است" : "⚠ سند تراز نیست"}</span>
          {!balanced ? <span className="tabular">اختلاف: {formatMoney(diff.replace("-", ""), currency)}</span> : null}
        </div>
      </Card>

      <div className="flex flex-wrap items-center gap-2">
        {can("accounting.voucher.finalize") ? (
          <Button onClick={() => saveAndFinalize.mutate()} loading={saveAndFinalize.isPending} disabled={busy || !balanced}>
            <CheckCheck /> ذخیره و قطعی کردن
          </Button>
        ) : null}
        <Button variant="outline" onClick={() => save.mutate()} loading={save.isPending} disabled={busy}>
          <Save /> ذخیره پیش‌نویس
        </Button>
        <div className="flex-1" />
        {voucher ? (
          <Button variant="ghost" className="text-danger" onClick={() => remove.mutate()} loading={remove.isPending}>
            <Trash2 /> حذف پیش‌نویس
          </Button>
        ) : null}
      </div>
    </div>
  );
}

function VoucherView({ voucher: v }: { voucher: Voucher }) {
  const can = useCan();
  const currency = useCurrency();
  const qc = useQueryClient();
  const navigate = useNavigate();
  const [reversing, setReversing] = React.useState(false);
  const [revDate, setRevDate] = React.useState<string | null>(todayIso());

  const reverse = useMutation({
    mutationFn: () =>
      api.post<Voucher>(`/accounting/vouchers/${v.id}/reverse`, { document_date: revDate }, { version: v.row_version }),
    onSuccess: (r) => {
      qc.invalidateQueries({ queryKey: ["accounting"] });
      toast.success(`سند برگشت شماره ${toFaDigits(r.number ?? 0)} صادر شد`);
      setReversing(false);
      navigate(`/accounting/vouchers/${r.id}`);
    },
    onError,
  });

  const reversible = v.source_type !== "opening" && v.source_type !== "closing" && !v.reversal_of_id && !v.reversed_by_id;

  return (
    <div className="flex flex-col gap-4 print:gap-2">
      <div className="flex flex-wrap items-center justify-between gap-3 print:hidden">
        <div className="flex items-center gap-3">
          <Button variant="ghost" size="icon" asChild aria-label="بازگشت">
            <Link to="/accounting/vouchers">
              <ArrowRight />
            </Link>
          </Button>
          <h1 className="text-xl font-extrabold text-ink">سند شماره {toFaDigits(v.number ?? 0)}</h1>
          <Badge tone="success">قطعی</Badge>
          {v.reversed_by_id ? <Badge tone="danger">برگشت‌خورده</Badge> : null}
          {v.source_type !== "manual" ? <Badge tone="info" icon={false}>{SOURCE_LABEL[v.source_type]}</Badge> : null}
        </div>
        <div className="flex gap-2">
          <Button variant="outline" onClick={() => window.print()}>
            <Printer /> چاپ
          </Button>
          {can("accounting.voucher.reverse") && reversible ? (
            <Button variant="danger" onClick={() => setReversing(true)}>
              <Undo2 /> صدور سند برگشت
            </Button>
          ) : null}
        </div>
      </div>

      <Card className="grid gap-4 p-5 text-sm sm:grid-cols-4">
        <Info label="تاریخ سند" value={isoToJalaliFa(v.document_date)} />
        <Info label="شماره" value={toFaDigits(v.number ?? 0)} />
        <Info label="قطعی شده در" value={v.finalized_at ? formatDateTime(v.finalized_at) : "—"} />
        <Info label="شرح" value={v.description ?? "—"} />
        {v.reversal_of_id ? (
          <p className="sm:col-span-4">
            این سند، برگشت{" "}
            <Link className="text-brand-600 underline dark:text-brand-300" to={`/accounting/vouchers/${v.reversal_of_id}`}>
              سند اصلی
            </Link>{" "}
            است.
          </p>
        ) : null}
        {v.reversed_by_id ? (
          <p className="text-danger sm:col-span-4">
            این سند با{" "}
            <Link className="underline" to={`/accounting/vouchers/${v.reversed_by_id}`}>
              سند برگشت
            </Link>{" "}
            خنثی شده است.
          </p>
        ) : null}
      </Card>

      <Card className="p-2">
        <div className="surface overflow-x-auto rounded-2xl">
          <table className="w-full min-w-[48rem] text-sm">
            <thead>
              <tr className="text-xs text-ink-faint">
                <th className="w-10 px-3 py-3">#</th>
                <th className="px-3 py-3 text-start">حساب</th>
                <th className="px-3 py-3 text-start">تفصیلی</th>
                <th className="px-3 py-3 text-start">شرح</th>
                <th className="px-3 py-3 text-start">بدهکار</th>
                <th className="px-3 py-3 text-start">بستانکار</th>
              </tr>
            </thead>
            <tbody>
              {v.lines.map((l) => (
                <tr key={l.id} className="border-t border-[var(--line)]">
                  <td className="tabular px-3 py-2.5 text-center text-ink-faint">{toFaDigits(l.line_no)}</td>
                  <td className="px-3 py-2.5">
                    <span className="tabular text-ink-faint">{toFaDigits(l.account_code)}</span> {l.account_name}
                  </td>
                  <td className="px-3 py-2.5 text-ink-soft">{l.detail_account_name ?? "—"}</td>
                  <td className="px-3 py-2.5 text-ink-soft">{l.description ?? ""}</td>
                  <td className="tabular px-3 py-2.5">{Number(l.debit) ? formatMoney(l.debit, currency) : ""}</td>
                  <td className="tabular px-3 py-2.5">{Number(l.credit) ? formatMoney(l.credit, currency) : ""}</td>
                </tr>
              ))}
            </tbody>
            <tfoot>
              <tr className="border-t-2 border-[var(--line)] bg-[var(--surface-muted)] font-bold">
                <td colSpan={4} className="px-3 py-3 text-end">
                  جمع
                </td>
                <td className="tabular px-3 py-3">{formatMoney(v.total_debit, currency)}</td>
                <td className="tabular px-3 py-3">{formatMoney(v.total_credit, currency)}</td>
              </tr>
            </tfoot>
          </table>
        </div>
        <p className="flex items-center gap-2 px-3 py-3 text-xs text-ink-faint print:hidden">
          <Lock className="size-3.5" /> سند قطعی قابل ویرایش یا حذف نیست؛ اصلاح فقط با صدور سند برگشت انجام می‌شود.
        </p>
      </Card>

      <Dialog open={reversing} onOpenChange={setReversing}>
        <DialogContent title={`برگشت سند شماره ${toFaDigits(v.number ?? 0)}`} description="سند جدیدی با ردیف‌های معکوس صادر و قطعی می‌شود. این عمل قابل بازگشت نیست.">
          <Field label="تاریخ سند برگشت" htmlFor="rev-date">
            <JalaliDateInput id="rev-date" value={revDate} onChange={setRevDate} />
          </Field>
          <DialogFooter>
            <Button variant="danger" onClick={() => reverse.mutate()} loading={reverse.isPending} disabled={!revDate}>
              تأیید و صدور برگشت
            </Button>
            <Button variant="ghost" onClick={() => setReversing(false)}>
              انصراف
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  );
}

function Info({ label, value }: { label: string; value: React.ReactNode }) {
  return (
    <div>
      <p className="text-xs text-ink-faint">{label}</p>
      <p className="mt-1 font-medium text-ink">{value}</p>
    </div>
  );
}
