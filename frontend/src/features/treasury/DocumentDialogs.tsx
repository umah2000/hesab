import { useMutation, useQueryClient } from "@tanstack/react-query";
import { Plus, Save, Trash2 } from "lucide-react";
import * as React from "react";
import { useNavigate } from "react-router";
import { toast } from "sonner";
import { Button } from "@/components/ui/button";
import { Dialog, DialogContent, DialogFooter } from "@/components/ui/dialog";
import { Field, Input, Select } from "@/components/ui/form-controls";
import { useCurrency } from "@/features/accounting/api";
import { JalaliDateInput, MoneyInput, Picker } from "@/features/accounting/inputs";
import { usePartyOptions } from "@/features/parties/api";
import { api, newIdempotencyKey } from "@/lib/api";
import { formatMoney, toFaDigits } from "@/lib/format";
import { todayIso } from "@/lib/jalali";
import { compareRials, inputToRials, sumRials } from "@/lib/money";
import {
  type Against,
  AGAINST_LABEL,
  accountLabel,
  type Method,
  METHOD_LABEL,
  type MoneyAccount,
  onError,
  type TreasuryDocument,
  useBranches,
  useMoneyAccounts,
} from "./api";
import { cleanDigits, sayadOk, settlementNet } from "./helpers";

/** A positive amount typed in display currency → rials, or null. */
function positive(v: string, currency: "IRR" | "IRT"): string | null {
  const r = inputToRials(v, currency);
  return r !== null && compareRials(r, "0") > 0 ? r : null;
}

/** Active branches in scope; the first is the default. */
function useBranchChoice() {
  const branches = useBranches();
  const active = React.useMemo(() => (branches.data ?? []).filter((b) => b.is_active), [branches.data]);
  const [branch, setBranch] = React.useState("");
  React.useEffect(() => {
    if (!branch && active.length) setBranch(active[0].id);
  }, [active, branch]);
  return { active, branch, setBranch };
}

function BranchDate({
  branches,
  branch,
  setBranch,
  date,
  setDate,
}: {
  branches: { id: string; name: string }[];
  branch: string;
  setBranch: (v: string) => void;
  date: string | null;
  setDate: (v: string | null) => void;
}) {
  return (
    <div className="grid grid-cols-2 gap-3">
      <Field label="شعبه">
        <Select aria-label="شعبه" value={branch} onChange={(e) => setBranch(e.target.value)}>
          {branches.map((b) => (
            <option key={b.id} value={b.id}>{b.name}</option>
          ))}
        </Select>
      </Field>
      <Field label="تاریخ سند">
        <JalaliDateInput value={date} onChange={setDate} />
      </Field>
    </div>
  );
}

/** Accounts usable in a branch: every active bank, and active cash boxes of that branch only. */
function usable(accounts: MoneyAccount[] | undefined, branch: string, kind?: "cash" | "bank") {
  return (accounts ?? []).filter(
    (a) => a.is_active && (!kind || a.kind === kind) && (a.kind === "bank" || a.branch_id === branch),
  );
}

function useDone(onClose: () => void, invalidateParties: boolean) {
  const qc = useQueryClient();
  const nav = useNavigate();
  return (d: TreasuryDocument, label: string) => {
    toast.success(`${label} شماره ${toFaDigits(d.number ?? 0)} ثبت شد`);
    qc.invalidateQueries({ queryKey: ["treasury"] });
    if (invalidateParties) qc.invalidateQueries({ queryKey: ["parties"] });
    onClose();
    nav(`/treasury/documents/${d.id}`);
  };
}

// --- receipt / payment ------------------------------------------------------------

type LineDraft = {
  key: number;
  method: Method;
  account: string;
  amount: string;
  reference: string;
  number: string;
  sayad: string;
  bankName: string;
  drawer: string;
  due: string | null;
};

const emptyLine = (key: number): LineDraft => ({
  key,
  method: "cash",
  account: "",
  amount: "",
  reference: "",
  number: "",
  sayad: "",
  bankName: "",
  drawer: "",
  due: null,
});

export function ReceiptPaymentDialog({ kind, onClose }: { kind: "receipt" | "payment"; onClose: () => void }) {
  const incoming = kind === "receipt";
  const label = incoming ? "دریافت" : "پرداخت";
  const currency = useCurrency();
  const { active, branch, setBranch } = useBranchChoice();
  const accounts = useMoneyAccounts();
  const parties = usePartyOptions();
  const [date, setDate] = React.useState<string | null>(todayIso());
  const [party, setParty] = React.useState<string | null>(null);
  const [against, setAgainst] = React.useState<"" | Against>("");
  const [description, setDescription] = React.useState("");
  const [lines, setLines] = React.useState<LineDraft[]>([emptyLine(1)]);
  const nextKey = React.useRef(2);
  const keyRef = React.useRef(newIdempotencyKey());
  const done = useDone(onClose, true);

  const update = (key: number, patch: Partial<LineDraft>) =>
    setLines((ls) => ls.map((l) => (l.key === key ? { ...l, ...patch } : l)));

  const rials = lines.map((l) => positive(l.amount, currency));
  const total = sumRials(rials.map((r) => r ?? "0"));

  const problem = (() => {
    if (!branch) return "شعبه را انتخاب کنید";
    if (!date) return "تاریخ معتبر وارد کنید";
    if (!party) return "طرف‌حساب را انتخاب کنید";
    for (const [i, l] of lines.entries()) {
      const n = `ردیف ${toFaDigits(i + 1)}`;
      if (!rials[i]) return `${n}: مبلغ را وارد کنید`;
      if (l.method !== "cheque" && !l.account) return `${n}: ${l.method === "cash" ? "صندوق" : "حساب بانکی"} را انتخاب کنید`;
      if (l.method === "cheque") {
        if (!cleanDigits(l.number)) return `${n}: شماره چک را وارد کنید`;
        if (!l.due) return `${n}: تاریخ سررسید معتبر وارد کنید`;
        if (!sayadOk(l.sayad)) return `${n}: شناسه صیادی ۱۶ رقم است`;
        if (!incoming && !l.account) return `${n}: حساب بانکی چک را انتخاب کنید`;
      }
    }
    return null;
  })();

  const create = useMutation({
    mutationFn: () => {
      const body = {
        branch_id: branch,
        document_date: date,
        party_id: party,
        against: against || null,
        description: description.trim() || null,
        lines: lines.map((l, i) => ({
          method: l.method,
          money_account_id: l.method === "cheque" && incoming ? null : l.account || null,
          amount: rials[i],
          reference: l.method === "bank" ? l.reference.trim() || null : null,
          cheque:
            l.method === "cheque"
              ? {
                  number: cleanDigits(l.number),
                  sayad_id: cleanDigits(l.sayad) || null,
                  bank_name: l.bankName.trim() || null,
                  drawer: l.drawer.trim() || null,
                  due_date: l.due,
                }
              : null,
        })),
      };
      return api.post<TreasuryDocument>(incoming ? "/treasury/receipts" : "/treasury/payments", body, {
        idempotencyKey: keyRef.current,
      });
    },
    onSuccess: (d) => done(d, label),
    onError: (e) => {
      keyRef.current = newIdempotencyKey();
      onError(e);
    },
  });

  return (
    <Dialog open onOpenChange={(o) => !o && onClose()}>
      <DialogContent
        title={incoming ? "دریافت از طرف‌حساب" : "پرداخت به طرف‌حساب"}
        description={
          incoming
            ? "دریافت نقد، واریز بانکی یا چک. چک دریافتی با وضعیت «نزد صندوق» ثبت می‌شود."
            : "پرداخت نقد، حواله بانکی یا چک. برداشت نقد بیش از موجودی صندوق پذیرفته نمی‌شود."
        }
        className="max-w-3xl"
      >
        <div className="flex flex-col gap-3">
          <BranchDate branches={active} branch={branch} setBranch={setBranch} date={date} setDate={setDate} />
          <div className="grid grid-cols-2 gap-3">
            <Field label="طرف‌حساب">
              <Picker ariaLabel="طرف‌حساب" options={parties.data ?? []} value={party} onChange={setParty} placeholder="کد یا نام" />
            </Field>
            <Field label="بابت" hint="خالی: دریافتنی برای مشتری، پرداختنی برای تأمین‌کننده">
              <Select aria-label="بابت" value={against} onChange={(e) => setAgainst(e.target.value as "" | Against)}>
                <option value="">پیش‌فرض (بر اساس نوع طرف‌حساب)</option>
                <option value="receivable">{AGAINST_LABEL.receivable}</option>
                <option value="payable">{AGAINST_LABEL.payable}</option>
              </Select>
            </Field>
          </div>
          <Field label="شرح">
            <Input value={description} maxLength={500} onChange={(e) => setDescription(e.target.value)} />
          </Field>

          <div className="flex flex-col gap-2">
            {lines.map((l, i) => {
              const options = l.method === "cash" ? usable(accounts.data, branch, "cash") : usable(accounts.data, branch, "bank");
              const needsAccount = l.method !== "cheque" || !incoming;
              return (
                <div key={l.key} className="surface flex flex-col gap-2 rounded-xl p-3">
                  <div className="flex flex-wrap items-end gap-2">
                    <span className="tabular pb-2 text-sm text-ink-faint">{toFaDigits(i + 1)}</span>
                    <Field label="روش" className="w-44">
                      <Select
                        aria-label={`روش ردیف ${i + 1}`}
                        value={l.method}
                        onChange={(e) => update(l.key, { method: e.target.value as Method, account: "" })}
                      >
                        {(Object.keys(METHOD_LABEL) as Method[]).map((m) => (
                          <option key={m} value={m}>{METHOD_LABEL[m]}</option>
                        ))}
                      </Select>
                    </Field>
                    {needsAccount ? (
                      <Field label={l.method === "cash" ? "صندوق" : l.method === "cheque" ? "حساب بانکی چک" : "حساب بانکی"} className="min-w-48 flex-1">
                        <Select aria-label={`حساب ردیف ${i + 1}`} value={l.account} onChange={(e) => update(l.key, { account: e.target.value })}>
                          <option value="">انتخاب کنید</option>
                          {options.map((a) => (
                            <option key={a.id} value={a.id}>{accountLabel(a)}</option>
                          ))}
                        </Select>
                      </Field>
                    ) : null}
                    <Field label={`مبلغ (${currency === "IRT" ? "تومان" : "ریال"})`} className="w-44">
                      <MoneyInput aria-label={`مبلغ ردیف ${i + 1}`} value={l.amount} onChange={(v) => update(l.key, { amount: v })} />
                    </Field>
                    {l.method === "bank" ? (
                      <Field label="شماره پیگیری" className="w-36">
                        <Input dir="ltr" maxLength={60} value={l.reference} onChange={(e) => update(l.key, { reference: e.target.value })} />
                      </Field>
                    ) : null}
                    {lines.length > 1 ? (
                      <Button
                        variant="ghost"
                        size="icon"
                        aria-label={`حذف ردیف ${i + 1}`}
                        onClick={() => setLines((ls) => ls.filter((x) => x.key !== l.key))}
                      >
                        <Trash2 />
                      </Button>
                    ) : null}
                  </div>
                  {l.method === "cheque" ? (
                    <div className="grid grid-cols-2 gap-2 sm:grid-cols-5">
                      <Field label="شماره چک">
                        <Input dir="ltr" maxLength={30} value={l.number} onChange={(e) => update(l.key, { number: e.target.value })} />
                      </Field>
                      <Field label="شناسه صیادی" error={sayadOk(l.sayad) ? undefined : "۱۶ رقم"}>
                        <Input dir="ltr" maxLength={20} inputMode="numeric" value={l.sayad} onChange={(e) => update(l.key, { sayad: e.target.value })} />
                      </Field>
                      <Field label="بانک">
                        <Input maxLength={100} value={l.bankName} onChange={(e) => update(l.key, { bankName: e.target.value })} />
                      </Field>
                      <Field label="صادرکننده">
                        <Input maxLength={150} value={l.drawer} onChange={(e) => update(l.key, { drawer: e.target.value })} />
                      </Field>
                      <Field label="سررسید">
                        <JalaliDateInput value={l.due} onChange={(v) => update(l.key, { due: v })} />
                      </Field>
                    </div>
                  ) : null}
                </div>
              );
            })}
            <Button
              variant="outline"
              size="sm"
              className="self-start"
              disabled={lines.length >= 50}
              onClick={() => {
                setLines((ls) => [...ls, emptyLine(nextKey.current)]);
                nextKey.current += 1;
              }}
            >
              <Plus /> ردیف جدید
            </Button>
          </div>
          <p className="text-sm">
            جمع {label}: <b className="tabular">{formatMoney(total, currency)}</b>
          </p>
          {problem ? <p className="text-xs text-ink-faint">{problem}</p> : null}
        </div>
        <DialogFooter>
          <Button loading={create.isPending} disabled={!!problem} onClick={() => create.mutate()}>
            <Save /> ثبت {label}
          </Button>
          <Button variant="ghost" onClick={onClose}>انصراف</Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}

// --- transfer -----------------------------------------------------------------------

export function TransferDialog({ onClose }: { onClose: () => void }) {
  const currency = useCurrency();
  const { active, branch, setBranch } = useBranchChoice();
  const accounts = useMoneyAccounts();
  const [date, setDate] = React.useState<string | null>(todayIso());
  const [from, setFrom] = React.useState("");
  const [to, setTo] = React.useState("");
  const [amount, setAmount] = React.useState("");
  const [reference, setReference] = React.useState("");
  const [description, setDescription] = React.useState("");
  const keyRef = React.useRef(newIdempotencyKey());
  const done = useDone(onClose, false);
  const options = usable(accounts.data, branch);
  const rials = positive(amount, currency);
  const problem = !branch
    ? "شعبه را انتخاب کنید"
    : !date
      ? "تاریخ معتبر وارد کنید"
      : !from || !to
        ? "مبدأ و مقصد را انتخاب کنید"
        : from === to
          ? "مبدأ و مقصد انتقال یکی است"
          : !rials
            ? "مبلغ را وارد کنید"
            : null;

  const create = useMutation({
    mutationFn: () =>
      api.post<TreasuryDocument>(
        "/treasury/transfers",
        {
          branch_id: branch,
          document_date: date,
          from_account_id: from,
          to_account_id: to,
          amount: rials,
          reference: reference.trim() || null,
          description: description.trim() || null,
        },
        { idempotencyKey: keyRef.current },
      ),
    onSuccess: (d) => done(d, "انتقال وجه"),
    onError: (e) => {
      keyRef.current = newIdempotencyKey();
      onError(e);
    },
  });

  const accountSelect = (label: string, value: string, set: (v: string) => void) => (
    <Field label={label}>
      <Select aria-label={label} value={value} onChange={(e) => set(e.target.value)}>
        <option value="">انتخاب کنید</option>
        {options.map((a) => (
          <option key={a.id} value={a.id}>
            {a.kind === "cash" ? "صندوق" : "بانک"}: {accountLabel(a)}
          </option>
        ))}
      </Select>
    </Field>
  );

  return (
    <Dialog open onOpenChange={(o) => !o && onClose()}>
      <DialogContent title="انتقال وجه" description="جابه‌جایی وجه بین صندوق و حساب بانکی. صندوق‌ها فقط از شعبه انتخابی نمایش داده می‌شوند.">
        <div className="flex flex-col gap-3">
          <BranchDate branches={active} branch={branch} setBranch={setBranch} date={date} setDate={setDate} />
          <div className="grid grid-cols-2 gap-3">
            {accountSelect("از", from, setFrom)}
            {accountSelect("به", to, setTo)}
          </div>
          <div className="grid grid-cols-2 gap-3">
            <Field label={`مبلغ (${currency === "IRT" ? "تومان" : "ریال"})`}>
              <MoneyInput aria-label="مبلغ" value={amount} onChange={setAmount} />
            </Field>
            <Field label="شماره پیگیری">
              <Input dir="ltr" maxLength={60} value={reference} onChange={(e) => setReference(e.target.value)} />
            </Field>
          </div>
          <Field label="شرح">
            <Input maxLength={500} value={description} onChange={(e) => setDescription(e.target.value)} />
          </Field>
          {problem ? <p className="text-xs text-ink-faint">{problem}</p> : null}
        </div>
        <DialogFooter>
          <Button loading={create.isPending} disabled={!!problem} onClick={() => create.mutate()}>
            <Save /> ثبت انتقال
          </Button>
          <Button variant="ghost" onClick={onClose}>انصراف</Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}

// --- card-reader settlement ---------------------------------------------------------

export function SettlementDialog({ onClose }: { onClose: () => void }) {
  const currency = useCurrency();
  const { active, branch, setBranch } = useBranchChoice();
  const banks = useMoneyAccounts("bank");
  const [date, setDate] = React.useState<string | null>(todayIso());
  const [bank, setBank] = React.useState("");
  const [amount, setAmount] = React.useState("");
  const [fee, setFee] = React.useState("");
  const [reference, setReference] = React.useState("");
  const [description, setDescription] = React.useState("");
  const keyRef = React.useRef(newIdempotencyKey());
  const done = useDone(onClose, false);
  const gross = positive(amount, currency);
  const feeRials = inputToRials(fee, currency);
  const net = settlementNet(gross, feeRials);
  const problem = !branch
    ? "شعبه را انتخاب کنید"
    : !date
      ? "تاریخ معتبر وارد کنید"
      : !bank
        ? "حساب بانکی را انتخاب کنید"
        : !gross
          ? "مبلغ تسویه را وارد کنید"
          : feeRials === null || !net
            ? "کارمزد باید کمتر از مبلغ تسویه باشد"
            : null;

  const create = useMutation({
    mutationFn: () =>
      api.post<TreasuryDocument>(
        "/treasury/settlements",
        {
          branch_id: branch,
          document_date: date,
          bank_account_id: bank,
          amount: gross,
          fee: feeRials ?? "0",
          reference: reference.trim() || null,
          description: description.trim() || null,
        },
        { idempotencyKey: keyRef.current },
      ),
    onSuccess: (d) => done(d, "تسویه کارت‌خوان"),
    onError: (e) => {
      keyRef.current = newIdempotencyKey();
      onError(e);
    },
  });
  const unit = currency === "IRT" ? "تومان" : "ریال";

  return (
    <Dialog open onOpenChange={(o) => !o && onClose()}>
      <DialogContent title="تسویه کارت‌خوان" description="بانک مبلغ فروش کارتی را پس از کسر کارمزد به حساب واریز می‌کند.">
        <div className="flex flex-col gap-3">
          <BranchDate branches={active} branch={branch} setBranch={setBranch} date={date} setDate={setDate} />
          <Field label="حساب بانکی">
            <Select aria-label="حساب بانکی" value={bank} onChange={(e) => setBank(e.target.value)}>
              <option value="">انتخاب کنید</option>
              {(banks.data ?? []).filter((a) => a.is_active).map((a) => (
                <option key={a.id} value={a.id}>{accountLabel(a)}</option>
              ))}
            </Select>
          </Field>
          <div className="grid grid-cols-2 gap-3">
            <Field label={`مبلغ ناخالص فروش کارتی (${unit})`}>
              <MoneyInput aria-label="مبلغ ناخالص" value={amount} onChange={setAmount} />
            </Field>
            <Field label={`کارمزد بانک (${unit})`}>
              <MoneyInput aria-label="کارمزد" value={fee} onChange={setFee} />
            </Field>
          </div>
          <Field label="شماره پیگیری">
            <Input dir="ltr" maxLength={60} value={reference} onChange={(e) => setReference(e.target.value)} />
          </Field>
          <Field label="شرح">
            <Input maxLength={500} value={description} onChange={(e) => setDescription(e.target.value)} />
          </Field>
          <p className="text-sm">
            خالص واریزی به بانک: <b className="tabular">{net ? formatMoney(net, currency) : "—"}</b>
          </p>
          {problem ? <p className="text-xs text-ink-faint">{problem}</p> : null}
        </div>
        <DialogFooter>
          <Button loading={create.isPending} disabled={!!problem} onClick={() => create.mutate()}>
            <Save /> ثبت تسویه
          </Button>
          <Button variant="ghost" onClick={onClose}>انصراف</Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}

