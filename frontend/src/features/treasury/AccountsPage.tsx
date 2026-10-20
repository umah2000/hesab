import { useMutation, useQueryClient } from "@tanstack/react-query";
import { Landmark, Pencil, Plus, Save } from "lucide-react";
import * as React from "react";
import { toast } from "sonner";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { Dialog, DialogContent, DialogFooter } from "@/components/ui/dialog";
import { Badge, EmptyState, ErrorBox, Spinner } from "@/components/ui/feedback";
import { Checkbox, Field, Input, Label, Select } from "@/components/ui/form-controls";
import { Table, Td, Th, Tr } from "@/components/ui/table";
import { useCurrency } from "@/features/accounting/api";
import { api, newIdempotencyKey } from "@/lib/api";
import { formatMoney } from "@/lib/format";
import { cleanDigits } from "./helpers";
import { ACCOUNT_KIND_LABEL, type AccountKind, type MoneyAccount, onError, useBranches, useMoneyAccounts } from "./api";

export function MoneyAccountsPage() {
  const currency = useCurrency();
  const [kind, setKind] = React.useState<"" | AccountKind>("");
  const [editing, setEditing] = React.useState<MoneyAccount | "new" | null>(null);
  const list = useMoneyAccounts(kind || undefined);
  return (
    <Card>
      <div className="flex flex-wrap items-end gap-3 p-4">
        <Field label="نوع">
          <Select value={kind} onChange={(e) => setKind(e.target.value as "" | AccountKind)}>
            <option value="">صندوق و بانک</option>
            <option value="cash">صندوق</option>
            <option value="bank">حساب بانکی</option>
          </Select>
        </Field>
        <div className="flex-1" />
        <Button onClick={() => setEditing("new")}>
          <Plus /> صندوق یا حساب جدید
        </Button>
      </div>
      <div className="surface mx-4 mb-4 overflow-hidden rounded-2xl">
        {list.isLoading ? (
          <Spinner />
        ) : list.isError ? (
          <ErrorBox error={list.error} />
        ) : !list.data?.length ? (
          <EmptyState icon={Landmark} title="صندوق یا حساب بانکی تعریف نشده است" />
        ) : (
          <Table>
            <thead>
              <tr>
                <Th className="w-28">کد</Th>
                <Th>نام</Th>
                <Th className="w-28">نوع</Th>
                <Th>شعبه</Th>
                <Th>مشخصات بانک</Th>
                <Th className="w-44">مانده</Th>
                <Th className="w-24">وضعیت</Th>
                <Th className="w-12" />
              </tr>
            </thead>
            <tbody>
              {list.data.map((a) => (
                <Tr key={a.id}>
                  <Td dir="ltr" className="tabular text-end">{a.code}</Td>
                  <Td className="font-medium">{a.name}</Td>
                  <Td>{ACCOUNT_KIND_LABEL[a.kind]}</Td>
                  <Td className="text-ink-soft">{a.branch_name ?? "—"}</Td>
                  <Td className="text-xs text-ink-soft">
                    {a.kind === "bank" ? (
                      <>
                        {[a.bank_name, a.bank_branch].filter(Boolean).join(" — ") || "—"}
                        {a.account_no ? <div className="tabular" dir="ltr">{a.account_no}</div> : null}
                        {a.iban ? <div className="tabular" dir="ltr">{a.iban}</div> : null}
                      </>
                    ) : (
                      "—"
                    )}
                  </Td>
                  <Td className="tabular font-semibold">{formatMoney(a.balance, currency)}</Td>
                  <Td>{a.is_active ? <Badge tone="success">فعال</Badge> : <Badge tone="neutral">غیرفعال</Badge>}</Td>
                  <Td>
                    <Button variant="ghost" size="icon" aria-label={`ویرایش ${a.name}`} onClick={() => setEditing(a)}>
                      <Pencil />
                    </Button>
                  </Td>
                </Tr>
              ))}
            </tbody>
          </Table>
        )}
      </div>
      {editing ? <AccountDialog account={editing === "new" ? null : editing} onClose={() => setEditing(null)} /> : null}
    </Card>
  );
}

function AccountDialog({ account, onClose }: { account: MoneyAccount | null; onClose: () => void }) {
  const qc = useQueryClient();
  const branches = useBranches();
  const [code, setCode] = React.useState(account?.code ?? "");
  const [name, setName] = React.useState(account?.name ?? "");
  const [kind, setKind] = React.useState<AccountKind>(account?.kind ?? "cash");
  const [branch, setBranch] = React.useState(account?.branch_id ?? "");
  const [bankName, setBankName] = React.useState(account?.bank_name ?? "");
  const [bankBranch, setBankBranch] = React.useState(account?.bank_branch ?? "");
  const [accountNo, setAccountNo] = React.useState(account?.account_no ?? "");
  const [iban, setIban] = React.useState(account?.iban ?? "");
  const [active, setActive] = React.useState(account?.is_active ?? true);
  const keyRef = React.useRef(newIdempotencyKey());
  const activeBranches = (branches.data ?? []).filter((b) => b.is_active || b.id === branch);

  const problem =
    !account && !/^[A-Za-z0-9-]{1,16}$/.test(code.trim())
      ? "کد فقط حروف و رقم لاتین و خط تیره (حداکثر ۱۶)"
      : name.trim().length < 2
        ? "نام را وارد کنید"
        : kind === "cash" && !branch
          ? "صندوق باید به یک شعبه تعلق داشته باشد"
          : null;

  const save = useMutation({
    mutationFn: () => {
      const bank = kind === "bank";
      const fields = {
        name: name.trim(),
        branch_id: branch || null,
        bank_name: bank ? bankName.trim() || null : null,
        bank_branch: bank ? bankBranch.trim() || null : null,
        account_no: bank ? cleanDigits(accountNo) || null : null,
        iban: bank ? cleanDigits(iban).toUpperCase() || null : null,
      };
      return account
        ? api.put<MoneyAccount>(`/treasury/accounts/${account.id}`, { ...fields, is_active: active }, account.row_version)
        : api.post<MoneyAccount>("/treasury/accounts", { ...fields, code: code.trim(), kind }, { idempotencyKey: keyRef.current });
    },
    onSuccess: (a) => {
      toast.success(account ? "تغییرات ذخیره شد" : `«${a.name}» تعریف شد`);
      qc.invalidateQueries({ queryKey: ["treasury"] });
      onClose();
    },
    onError: (e) => {
      keyRef.current = newIdempotencyKey();
      onError(e);
    },
  });

  return (
    <Dialog open onOpenChange={(o) => !o && onClose()}>
      <DialogContent
        title={account ? `ویرایش ${account.name}` : "صندوق یا حساب بانکی جدید"}
        description="هر صندوق یا حساب بانکی یک حساب تفصیلی است و مانده‌اش از اسناد قطعی حساب می‌شود."
      >
        <div className="flex flex-col gap-3">
          <div className="grid grid-cols-2 gap-3">
            <Field label="کد" hint={account ? "کد پس از ثبت تغییر نمی‌کند" : "لاتین، مثل CASH-01"}>
              <Input dir="ltr" maxLength={16} disabled={!!account} value={code} onChange={(e) => setCode(e.target.value)} />
            </Field>
            <Field label="نوع">
              <Select aria-label="نوع" disabled={!!account} value={kind} onChange={(e) => setKind(e.target.value as AccountKind)}>
                <option value="cash">صندوق</option>
                <option value="bank">حساب بانکی</option>
              </Select>
            </Field>
          </div>
          <Field label="نام">
            <Input maxLength={150} value={name} onChange={(e) => setName(e.target.value)} />
          </Field>
          <Field label="شعبه" hint={kind === "cash" ? "الزامی برای صندوق" : "اختیاری"}>
            <Select aria-label="شعبه" value={branch} onChange={(e) => setBranch(e.target.value)}>
              <option value="">{kind === "cash" ? "انتخاب کنید" : "بدون شعبه"}</option>
              {activeBranches.map((b) => (
                <option key={b.id} value={b.id}>{b.name}</option>
              ))}
            </Select>
          </Field>
          {kind === "bank" ? (
            <>
              <div className="grid grid-cols-2 gap-3">
                <Field label="نام بانک">
                  <Input maxLength={100} value={bankName} onChange={(e) => setBankName(e.target.value)} />
                </Field>
                <Field label="شعبه بانک">
                  <Input maxLength={100} value={bankBranch} onChange={(e) => setBankBranch(e.target.value)} />
                </Field>
              </div>
              <Field label="شماره حساب">
                <Input dir="ltr" maxLength={30} value={accountNo} onChange={(e) => setAccountNo(e.target.value)} />
              </Field>
              <Field label="شبا" hint="IR و ۲۴ رقم؛ درستی آن در سرور بررسی می‌شود">
                <Input dir="ltr" maxLength={34} placeholder="IR000000000000000000000000" value={iban} onChange={(e) => setIban(e.target.value)} />
              </Field>
            </>
          ) : null}
          {account ? (
            <div className="flex items-center gap-2">
              <Checkbox id="acc-active" checked={active} onCheckedChange={(v) => setActive(v === true)} />
              <Label htmlFor="acc-active">فعال</Label>
              <span className="text-xs text-ink-faint">
                (غیرفعال‌کردن فقط با مانده صفر ممکن است)
              </span>
            </div>
          ) : null}
          {problem ? <p className="text-xs text-ink-faint">{problem}</p> : null}
        </div>
        <DialogFooter>
          <Button loading={save.isPending} disabled={!!problem} onClick={() => save.mutate()}>
            <Save /> ذخیره
          </Button>
          <Button variant="ghost" onClick={onClose}>انصراف</Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
