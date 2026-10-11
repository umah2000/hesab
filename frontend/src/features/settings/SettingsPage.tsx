import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Building2, Monitor, Plus, Save, Store } from "lucide-react";
import * as React from "react";
import { toast } from "sonner";
import { PageTitle } from "@/components/layout/AppShell";
import { Button } from "@/components/ui/button";
import { Card, CardBody, CardHeader } from "@/components/ui/card";
import { Badge, ErrorBox, Spinner } from "@/components/ui/feedback";
import { Field, Input, Select } from "@/components/ui/form-controls";
import { useCan } from "@/features/auth/auth";
import { ApiError, api, newIdempotencyKey } from "@/lib/api";
import { toFaDigits } from "@/lib/format";
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
        <BranchesCard />
      </div>
    </>
  );
}
