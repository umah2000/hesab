import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Building2, DatabaseBackup, HardDriveUpload, Monitor, Plus, Save, ShieldCheck, Store } from "lucide-react";
import * as React from "react";
import { toast } from "sonner";
import { PageTitle } from "@/components/layout/AppShell";
import { Button } from "@/components/ui/button";
import { Card, CardBody, CardHeader } from "@/components/ui/card";
import { Badge, ErrorBox, Spinner } from "@/components/ui/feedback";
import { Field, Input, Select } from "@/components/ui/form-controls";
import { useCan } from "@/features/auth/auth";
import { ApiError, api, newIdempotencyKey } from "@/lib/api";
import { formatDateTime, toEnDigits, toFaDigits } from "@/lib/format";
import { BrandingCard } from "./BrandingCard";
import { LicenseCard } from "./LicenseCard";
import type { Branch, CashRegister, Organization } from "./types";

const onError = (e: unknown) => toast.error(e instanceof ApiError ? e.message : "خطا");

function OrganizationCard() {
  const qc = useQueryClient();
  const can = useCan();
  const org = useQuery({ queryKey: ["organization"], queryFn: () => api.get<Organization>("/organization/settings") });
  const [draft, setDraft] = React.useState<Partial<Organization>>({});
  React.useEffect(() => setDraft({}), [org.data?.row_version]);
  const editable = can("settings.manage");

  const save = useMutation({
    mutationFn: () => api.put<Organization>("/organization/settings", draft, org.data?.row_version ?? ""),
    onSuccess: (o) => {
      qc.setQueryData(["organization"], o);
      toast.success("تنظیمات ذخیره شد");
    },
    onError,
  });

  if (org.isLoading) return <Card><Spinner /></Card>;
  if (org.isError || !org.data) return <Card><ErrorBox error={org.error} /></Card>;
  const v = { ...org.data, ...draft };

  return (
    <Card>
      <CardHeader icon={<Store className="size-5" />} title="اطلاعات سازمان" description="این تنظیمات برای همه شعب اعمال می‌شود" />
      <CardBody className="grid gap-4 md:grid-cols-3">
        <Field label="نام فروشگاه / سازمان">
          <Input value={v.name} disabled={!editable} onChange={(e) => setDraft({ ...draft, name: e.target.value })} />
        </Field>
        <Field label="واحد نمایش مبالغ" hint="مبالغ همیشه به ریال ذخیره می‌شوند">
          <Select value={v.display_currency} disabled={!editable} onChange={(e) => setDraft({ ...draft, display_currency: e.target.value as "IRR" | "IRT" })}>
            <option value="IRT">تومان</option>
            <option value="IRR">ریال</option>
          </Select>
        </Field>
        <Field label="فروش بیش از موجودی">
          <Select
            value={v.negative_stock_policy}
            disabled={!editable}
            onChange={(e) => setDraft({ ...draft, negative_stock_policy: e.target.value as Organization["negative_stock_policy"] })}
          >
            <option value="warn">مجاز، با هشدار</option>
            <option value="deny">غیرمجاز</option>
            <option value="allow">آزاد</option>
          </Select>
        </Field>
        <Field label="نرخ پیش‌فرض مالیات بر ارزش افزوده (٪)" hint="برای کالاهای مشمول بدون نرخ اختصاصی">
          <Input dir="ltr" value={v.default_vat_rate} disabled={!editable} onChange={(e) => setDraft({ ...draft, default_vat_rate: toEnDigits(e.target.value) })} />
        </Field>
        <Field label="قیمت‌های فروش" hint="قیمت مصرف‌کننده معمولاً شامل مالیات است">
          <Select
            value={v.prices_include_vat ? "1" : "0"}
            disabled={!editable}
            onChange={(e) => setDraft({ ...draft, prices_include_vat: e.target.value === "1" })}
          >
            <option value="1">شامل مالیات (مالیات از قیمت جدا می‌شود)</option>
            <option value="0">بدون مالیات (مالیات به قیمت اضافه می‌شود)</option>
          </Select>
        </Field>
        <Field label="سقف تخفیف صندوق‌دار (٪ فاکتور)" hint="بیشتر از این، تأیید سرپرست لازم است">
          <Input dir="ltr" value={v.cashier_discount_limit} disabled={!editable} onChange={(e) => setDraft({ ...draft, cashier_discount_limit: toEnDigits(e.target.value) })} />
        </Field>
        <Field label="متن بالای فیش" className="md:col-span-1">
          <Textarea value={v.receipt_header ?? ""} disabled={!editable} onChange={(e) => setDraft({ ...draft, receipt_header: e.target.value })} />
        </Field>
        <Field label="متن پایین فیش" className="md:col-span-1">
          <Textarea value={v.receipt_footer ?? ""} disabled={!editable} onChange={(e) => setDraft({ ...draft, receipt_footer: e.target.value })} />
        </Field>
        <Field label="هشدار کپی پشتیبان پس از (روز)">
          <Input dir="ltr" value={String(v.backup_warning_days)} disabled={!editable} onChange={(e) => setDraft({ ...draft, backup_warning_days: Number(toEnDigits(e.target.value)) || 1 })} />
        </Field>
        {editable ? (
          <div className="md:col-span-3">
            <Button onClick={() => save.mutate()} loading={save.isPending} disabled={Object.keys(draft).length === 0}>
              <Save /> ذخیره تنظیمات
            </Button>
          </div>
        ) : null}
      </CardBody>
    </Card>
  );
}

function Registers({ branch }: { branch: Branch }) {
  const qc = useQueryClient();
  const can = useCan();
  const regs = useQuery({
    queryKey: ["registers", branch.id],
    queryFn: () => api.get<CashRegister[]>(`/organization/branches/${branch.id}/cash-registers`),
  });
  const [code, setCode] = React.useState("");
  const [name, setName] = React.useState("");
  const keyRef = React.useRef(newIdempotencyKey());
  const add = useMutation({
    mutationFn: () => api.post<CashRegister>("/organization/cash-registers", { branch_id: branch.id, code, name }, { idempotencyKey: keyRef.current }),
    onSuccess: () => {
      keyRef.current = newIdempotencyKey();
      setCode("");
      setName("");
      qc.invalidateQueries({ queryKey: ["registers", branch.id] });
      toast.success("صندوق اضافه شد");
    },
    onError,
  });
  const toggle = useMutation({
    mutationFn: (r: CashRegister) => api.patch(`/organization/cash-registers/${r.id}`, { is_active: !r.is_active }, r.row_version),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["registers", branch.id] }),
    onError,
  });

  return (
    <div className="flex flex-col gap-2">
      {regs.data?.map((r) => (
        <div key={r.id} className="flex items-center gap-3 rounded-xl bg-black/[0.03] px-3 py-2 dark:bg-white/5">
          <Monitor className="size-4 text-ink-faint" />
          <span className="flex-1 text-sm text-ink">{r.name}</span>
          <span className="text-xs text-ink-faint" dir="ltr">{r.code}</span>
          {r.is_active ? <Badge tone="success">فعال</Badge> : <Badge tone="neutral">غیرفعال</Badge>}
          {can("branches.manage") ? (
            <Button size="sm" variant="ghost" onClick={() => toggle.mutate(r)}>
              {r.is_active ? "غیرفعال کن" : "فعال کن"}
            </Button>
          ) : null}
        </div>
      ))}
      {regs.data?.length === 0 ? <p className="text-sm text-ink-faint">هنوز صندوقی تعریف نشده است.</p> : null}
      {can("branches.manage") ? (
        <div className="mt-1 flex gap-2">
          <Input className="w-24" dir="ltr" placeholder="کد" value={code} onChange={(e) => setCode(e.target.value)} />
          <Input placeholder="نام صندوق، مثلاً صندوق ۱" value={name} onChange={(e) => setName(e.target.value)} />
          <Button variant="outline" disabled={!code || name.length < 2} loading={add.isPending} onClick={() => add.mutate()}>
            <Plus /> افزودن
          </Button>
        </div>
      ) : null}
    </div>
  );
}

function BranchesCard() {
  const qc = useQueryClient();
  const can = useCan();
  const branches = useQuery({ queryKey: ["branches"], queryFn: () => api.get<Branch[]>("/organization/branches") });
  const [code, setCode] = React.useState("");
  const [name, setName] = React.useState("");
  const keyRef = React.useRef(newIdempotencyKey());
  const add = useMutation({
    mutationFn: () => api.post<Branch>("/organization/branches", { code, name }, { idempotencyKey: keyRef.current }),
    onSuccess: () => {
      keyRef.current = newIdempotencyKey();
      setCode("");
      setName("");
      qc.invalidateQueries({ queryKey: ["branches"] });
      toast.success("شعبه اضافه شد");
    },
    onError,
  });

  return (
    <Card>
      <CardHeader
        icon={<Building2 className="size-5" />}
        title="شعب و صندوق‌ها"
        description={branches.data ? `${toFaDigits(branches.data.length)} شعبه در محدوده دسترسی شما` : undefined}
      />
      <CardBody className="flex flex-col gap-4">
        {branches.isLoading ? <Spinner /> : null}
        {branches.data?.map((b) => (
          <div key={b.id} className="surface rounded-2xl p-4">
            <div className="mb-3 flex items-center gap-2">
              <p className="font-bold text-ink">{b.name}</p>
              <span className="text-xs text-ink-faint" dir="ltr">#{b.code}</span>
              {!b.is_active ? <Badge tone="neutral">غیرفعال</Badge> : null}
            </div>
            <Registers branch={b} />
          </div>
        ))}
        {can("branches.manage") ? (
          <div className="flex flex-wrap gap-2 border-t border-[var(--line)] pt-4">
            <Input className="w-24" dir="ltr" placeholder="کد" value={code} onChange={(e) => setCode(e.target.value)} />
            <Input className="flex-1" placeholder="نام شعبه جدید" value={name} onChange={(e) => setName(e.target.value)} />
            <Button disabled={!code || name.length < 2} loading={add.isPending} onClick={() => add.mutate()}>
              <Plus /> شعبه جدید
            </Button>
          </div>
        ) : null}
      </CardBody>
    </Card>
  );
}

export function SettingsPage() {
  return (
    <>
      <PageTitle title="تنظیمات" subtitle="سازمان، شعب و صندوق‌های فروش" />
      <div className="flex flex-col gap-4">
        <OrganizationCard />
        <BrandingCard />
        <BackupCard />
        <LicenseCard />
        <BranchesCard />
      </div>
    </>
  );
}

function Textarea(props: React.TextareaHTMLAttributes<HTMLTextAreaElement>) {
  return (
    <textarea
      rows={2}
      maxLength={500}
      className="rounded-xl border border-[var(--line)] bg-[var(--surface)] px-3 py-2 text-sm text-ink outline-none focus:ring-2 focus:ring-brand-400 disabled:opacity-60"
      {...props}
    />
  );
}

type BackupRow = { at: string; status: "ok" | "failed"; file_path: string | null; size_bytes: number | null; message: string | null };
type BackupStatus = {
  last_backup: BackupRow | null;
  last_restore_test: BackupRow | null;
  last_copy: BackupRow | null;
  encrypted_copies: boolean;
  last_offsite_copy_at: string | null;
  warning_days: number;
  warnings: string[];
  history: (BackupRow & { kind: "backup" | "restore_test" | "copy"; seconds: number | null })[];
};

function BackupCard() {
  const qc = useQueryClient();
  const can = useCan();
  const status = useQuery({ queryKey: ["system", "backups"], queryFn: () => api.get<BackupStatus>("/system/backups") });
  const run = useMutation({
    mutationFn: () => api.post("/system/backups/run"),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["system", "backups"] });
      toast.success("نسخه پشتیبان گرفته و بررسی شد");
    },
    onError,
  });
  const copied = useMutation({
    mutationFn: () => api.post("/system/backups/offsite-copied"),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["system", "backups"] });
      toast.success("کپی به بیرون ثبت شد");
    },
    onError,
  });
  if (!can(["settings.manage", "audit.view"])) return null;
  const d = status.data;
  const size = (b: number | null) => (b ? `${toFaDigits((b / 1024 / 1024).toFixed(1))} مگابایت` : "");
  return (
    <Card>
      <CardHeader
        icon={<DatabaseBackup className="size-5" />}
        title="پشتیبان‌گیری"
        description={
          d?.encrypted_copies
            ? "نسخه پشتیبان روزانه گرفته، رمزنگاری و به مقصد دوم کپی می‌شود؛ آزمون بازیابی روی همان کپی انجام می‌شود."
            : "نسخه پشتیبان روزانه روی همین سیستم گرفته می‌شود؛ کپی آن به دیسک بیرونی با اپراتور است."
        }
        actions={
          <div className="flex gap-2">
            {can("settings.manage") ? (
              <Button size="sm" variant="outline" loading={run.isPending} onClick={() => run.mutate()}>
                پشتیبان‌گیری الان
              </Button>
            ) : null}
            {d?.encrypted_copies ? null : (
              <Button size="sm" loading={copied.isPending} onClick={() => copied.mutate()}>
                <HardDriveUpload /> کپی به بیرون را انجام دادم
              </Button>
            )}
          </div>
        }
      />
      <CardBody className="flex flex-col gap-3 text-sm">
        {status.isLoading || !d ? (
          <Spinner />
        ) : (
          <>
            {d.warnings.length ? (
              <ul className="list-inside list-disc rounded-xl bg-warning/10 p-3 text-ink">
                {d.warnings.map((w) => (
                  <li key={w}>{w}</li>
                ))}
              </ul>
            ) : (
              <Badge tone="success">وضعیت پشتیبان‌گیری مناسب است</Badge>
            )}
            <div className="grid gap-2 md:grid-cols-3">
              <div>آخرین پشتیبان موفق: <b>{d.last_backup ? formatDateTime(d.last_backup.at) : "ندارد"}</b> {d.last_backup ? size(d.last_backup.size_bytes) : ""}</div>
              <div>آخرین آزمون بازیابی: <b>{d.last_restore_test ? formatDateTime(d.last_restore_test.at) : "ندارد"}</b></div>
              <div>
                {d.encrypted_copies ? "آخرین کپی رمزنگاری‌شده" : "آخرین کپی به بیرون"}:{" "}
                <b>{d.last_offsite_copy_at ? formatDateTime(d.last_offsite_copy_at) : "ثبت نشده"}</b>
              </div>
            </div>
            {d.last_copy?.file_path ? (
              <div className="flex items-center gap-2 text-xs text-ink-faint">
                <ShieldCheck className="size-4 text-success" aria-hidden />
                <span>مقصد دوم (رمزنگاری‌شده، بررسی‌شده):</span>
                <span dir="ltr" className="font-mono">{d.last_copy.file_path}</span>
              </div>
            ) : null}
            {d.last_backup?.file_path ? <div className="font-mono text-xs text-ink-faint" dir="ltr">{d.last_backup.file_path}</div> : null}
            {d.history.length ? (
              <details>
                <summary className="cursor-pointer text-ink-soft">تاریخچه</summary>
                <ul className="mt-2 flex flex-col gap-1">
                  {d.history.map((h, i) => (
                    <li key={i} className="flex gap-3 text-xs">
                      <span className="w-36">{formatDateTime(h.at)}</span>
                      <span className="w-28">{h.kind === "backup" ? "پشتیبان" : h.kind === "copy" ? "کپی رمزنگاری‌شده" : "آزمون بازیابی"}</span>
                      {h.status === "ok" ? <Badge tone="success">موفق</Badge> : <Badge tone="danger">ناموفق</Badge>}
                      {h.kind === "copy" && h.message?.startsWith("sha256=") ? (
                        <span className="truncate font-mono text-ink-faint" dir="ltr" title={h.message}>
                          {h.message.slice(0, 23)}…
                        </span>
                      ) : (
                        <span className="truncate text-ink-faint">{h.message ?? size(h.size_bytes)}</span>
                      )}
                    </li>
                  ))}
                </ul>
              </details>
            ) : null}
          </>
        )}
      </CardBody>
    </Card>
  );
}
