import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { CreditCard, Pencil, Plus, TriangleAlert } from "lucide-react";
import * as React from "react";
import { toast } from "sonner";
import { Button } from "@/components/ui/button";
import { Card, CardBody, CardHeader } from "@/components/ui/card";
import { Dialog, DialogContent, DialogFooter } from "@/components/ui/dialog";
import { Badge, EmptyState, ErrorBox, Spinner } from "@/components/ui/feedback";
import { Checkbox, Field, Input, Select } from "@/components/ui/form-controls";
import { Table, Td, Th, Tr } from "@/components/ui/table";
import type { Branch, CashRegister } from "@/features/settings/types";
import { ApiError, api } from "@/lib/api";
import { toEnDigits, toFaDigits } from "@/lib/format";

export type CardProvider = "sep" | "mock";

export type CardTerminal = {
  id: string;
  name: string;
  provider: CardProvider;
  provider_label: string;
  host: string | null;
  port: number | null;
  terminal_no: string | null;
  branch_id: string;
  branch_name: string;
  cash_register_id: string | null;
  register_name: string | null;
  is_active: boolean;
  note: string | null;
  driver_ready: boolean;
  driver_note: string | null;
  row_version: string;
};

const PROVIDERS: { value: CardProvider; label: string }[] = [
  { value: "sep", label: "پرداخت الکترونیک سامان (SEP)، پروتکل SSP1126" },
  { value: "mock", label: "کارت‌خوان آزمایشی (فقط محیط توسعه)" },
];

const onError = (e: unknown) => toast.error(e instanceof ApiError ? e.message : "خطا");

/** Bank card readers (ADR-0023): several per branch, each register has a default. */
export function CardTerminalsCard() {
  const list = useQuery({ queryKey: ["payments", "terminals"], queryFn: () => api.get<CardTerminal[]>("/payments/terminals") });
  const [editing, setEditing] = React.useState<CardTerminal | "new" | null>(null);
  return (
    <Card className="mt-4">
      <CardHeader
        icon={<CreditCard className="size-5" />}
        title="کارت‌خوان‌های بانکی"
        description="هر کارت‌خوان را یک بار تعریف کنید و صندوق پیش‌فرض آن را تعیین کنید؛ صندوق‌دار هنگام پرداخت می‌تواند کارت‌خوان دیگری از همان شعبه را انتخاب کند."
        actions={
          <Button size="sm" onClick={() => setEditing("new")}>
            <Plus /> کارت‌خوان جدید
          </Button>
        }
      />
      <CardBody>
        {list.isLoading ? (
          <Spinner />
        ) : list.isError ? (
          <ErrorBox error={list.error} />
        ) : !list.data?.length ? (
          <EmptyState
            icon={CreditCard}
            title="کارت‌خوانی تعریف نشده"
            description="تا کارت‌خوانی تعریف و متصل نشده، صندوق‌دار مبلغ را روی دستگاه وارد می‌کند و شماره پیگیری را می‌نویسد."
          />
        ) : (
          <div className="surface overflow-hidden rounded-2xl">
            <Table>
              <thead>
                <tr>
                  <Th>نام</Th>
                  <Th>ارائه‌دهنده</Th>
                  <Th>نشانی دستگاه</Th>
                  <Th>شعبه / صندوق پیش‌فرض</Th>
                  <Th>وضعیت اتصال</Th>
                  <Th className="w-12" />
                </tr>
              </thead>
              <tbody>
                {list.data.map((t) => (
                  <Tr key={t.id} className={t.is_active ? "" : "opacity-60"}>
                    <Td className="font-medium">
                      {t.name}
                      {t.terminal_no ? <div className="text-xs text-ink-faint">ترمینال {toFaDigits(t.terminal_no)}</div> : null}
                    </Td>
                    <Td className="text-sm">{t.provider_label}</Td>
                    <Td dir="ltr" className="latin-digits text-sm">{t.host ? `${t.host}${t.port ? `:${t.port}` : ""}` : "—"}</Td>
                    <Td className="text-sm">
                      {t.branch_name}
                      <div className="text-xs text-ink-faint">{t.register_name ?? "بدون صندوق پیش‌فرض"}</div>
                    </Td>
                    <Td className="max-w-80">
                      {!t.is_active ? (
                        <Badge tone="neutral">غیرفعال</Badge>
                      ) : t.driver_ready ? (
                        <Badge tone="success">آماده</Badge>
                      ) : (
                        <div className="flex flex-col gap-1">
                          <Badge tone="warning">ثبت دستی شماره پیگیری</Badge>
                          <span className="flex items-start gap-1 text-xs text-ink-soft">
                            <TriangleAlert className="mt-0.5 size-3 shrink-0 text-warning" />
                            {t.driver_note}
                          </span>
                        </div>
                      )}
                    </Td>
                    <Td>
                      <Button variant="ghost" size="icon" aria-label={`ویرایش ${t.name}`} onClick={() => setEditing(t)}>
                        <Pencil />
                      </Button>
                    </Td>
                  </Tr>
                ))}
              </tbody>
            </Table>
          </div>
        )}
      </CardBody>
      {editing ? <TerminalDialog terminal={editing === "new" ? null : editing} onClose={() => setEditing(null)} /> : null}
    </Card>
  );
}

function TerminalDialog({ terminal, onClose }: { terminal: CardTerminal | null; onClose: () => void }) {
  const qc = useQueryClient();
  const branches = useQuery({ queryKey: ["branches"], queryFn: () => api.get<Branch[]>("/organization/branches") });
  const [f, setF] = React.useState({
    name: terminal?.name ?? "",
    provider: terminal?.provider ?? ("sep" as CardProvider),
    host: terminal?.host ?? "",
    port: terminal?.port != null ? String(terminal.port) : "",
    terminal_no: terminal?.terminal_no ?? "",
    branch_id: terminal?.branch_id ?? "",
    cash_register_id: terminal?.cash_register_id ?? "",
    is_active: terminal?.is_active ?? true,
    note: terminal?.note ?? "",
  });
  const branchId = f.branch_id || branches.data?.[0]?.id || "";
  const registers = useQuery({
    queryKey: ["registers", branchId],
    queryFn: () => api.get<CashRegister[]>(`/organization/branches/${branchId}/cash-registers`),
    enabled: !!branchId,
  });
  const set = <K extends keyof typeof f>(k: K, v: (typeof f)[K]) => setF((s) => ({ ...s, [k]: v }));
  const save = useMutation({
    mutationFn: () => {
      const body = {
        name: f.name.trim(),
        provider: f.provider,
        host: f.host.trim() || null,
        port: f.port ? Number(f.port) : null,
        terminal_no: f.terminal_no.trim() || null,
        branch_id: branchId,
        cash_register_id: f.cash_register_id || null,
        is_active: f.is_active,
        note: f.note.trim() || null,
      };
      return terminal
        ? api.put<CardTerminal>(`/payments/terminals/${terminal.id}`, body, terminal.row_version)
        : api.post<CardTerminal>("/payments/terminals", body);
    },
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["payments", "terminals"] });
      qc.invalidateQueries({ queryKey: ["sales"] });
      toast.success(terminal ? "کارت‌خوان ویرایش شد" : "کارت‌خوان تعریف شد");
      onClose();
    },
    onError,
  });

  return (
    <Dialog open onOpenChange={(o) => !o && onClose()}>
      <DialogContent title={terminal ? `ویرایش ${terminal.name}` : "کارت‌خوان جدید"} className="max-w-2xl">
        <div className="grid gap-3 sm:grid-cols-2">
          <Field htmlFor="ct-name" label="نام کارت‌خوان" hint="مثلاً «سامان صندوق ۱»">
            <Input id="ct-name" value={f.name} onChange={(e) => set("name", e.target.value)} />
          </Field>
          <Field htmlFor="ct-provider" label="شرکت ارائه‌دهنده (PSP)">
            <Select id="ct-provider" value={f.provider} onChange={(e) => set("provider", e.target.value as CardProvider)}>
              {PROVIDERS.map((p) => (
                <option key={p.value} value={p.value}>{p.label}</option>
              ))}
            </Select>
          </Field>
          <Field htmlFor="ct-host" label="نشانی IP دستگاه" hint="در دستگاه: منو ← پیکربندی ← گزارشات ← تنظیمات ارتباط">
            <Input id="ct-host" dir="ltr" className="latin-digits" placeholder="192.168.1.105" value={f.host} onChange={(e) => set("host", toEnDigits(e.target.value).trim())} />
          </Field>
          <Field htmlFor="ct-port" label="درگاه (port)" hint="اگر مستند PSP آن را مشخص کرده است">
            <Input id="ct-port" dir="ltr" className="latin-digits" inputMode="numeric" value={f.port} onChange={(e) => set("port", toEnDigits(e.target.value).replace(/\D/g, "").slice(0, 5))} />
          </Field>
          <Field htmlFor="ct-branch" label="شعبه">
            <Select id="ct-branch" value={branchId} onChange={(e) => setF((s) => ({ ...s, branch_id: e.target.value, cash_register_id: "" }))}>
              {branches.data?.map((b) => (
                <option key={b.id} value={b.id}>{b.name}</option>
              ))}
            </Select>
          </Field>
          <Field htmlFor="ct-register" label="صندوق پیش‌فرض" hint="در پرداخت این صندوق، همین کارت‌خوان از قبل انتخاب شده است">
            <Select id="ct-register" value={f.cash_register_id} onChange={(e) => set("cash_register_id", e.target.value)}>
              <option value="">بدون صندوق پیش‌فرض</option>
              {registers.data?.map((r) => (
                <option key={r.id} value={r.id}>{r.name}</option>
              ))}
            </Select>
          </Field>
          <Field htmlFor="ct-terminal" label="شماره ترمینال (اختیاری)">
            <Input id="ct-terminal" dir="ltr" className="latin-digits" value={f.terminal_no} onChange={(e) => set("terminal_no", toEnDigits(e.target.value).replace(/[^0-9A-Za-z]/g, "").slice(0, 16))} />
          </Field>
          <Field htmlFor="ct-note" label="توضیح">
            <Input id="ct-note" value={f.note} maxLength={300} onChange={(e) => set("note", e.target.value)} />
          </Field>
          <label className="flex items-center gap-2 text-sm text-ink-soft sm:col-span-2">
            <Checkbox checked={f.is_active} onCheckedChange={(c) => set("is_active", c === true)} /> فعال
          </label>
          {f.provider === "sep" ? (
            <p className="flex items-start gap-1.5 rounded-xl bg-warning/10 p-3 text-xs text-ink sm:col-span-2">
              <TriangleAlert className="mt-0.5 size-4 shrink-0 text-warning" />
              روی دستگاه: «نوع ارتباط: شبکه» و «پروتکل اتصال: SSP1126» (با رمز سوپروایزر از پشتیبان کارت‌خوان). ارسال مستقیم مبلغ پس از
              دریافت مستند فنی پروتکل از پرداخت الکترونیک سامان فعال می‌شود؛ تا آن زمان شماره پیگیری دستی ثبت می‌شود.
            </p>
          ) : null}
        </div>
        <DialogFooter>
          <Button loading={save.isPending} disabled={f.name.trim().length < 2 || !branchId} onClick={() => save.mutate()}>
            {terminal ? "ذخیره" : "تعریف کارت‌خوان"}
          </Button>
          <Button variant="ghost" onClick={onClose}>انصراف</Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
