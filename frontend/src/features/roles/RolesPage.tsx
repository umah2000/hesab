import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Lock, Pencil, Plus, ShieldCheck } from "lucide-react";
import * as React from "react";
import { toast } from "sonner";
import { PageTitle } from "@/components/layout/AppShell";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { Dialog, DialogContent, DialogFooter } from "@/components/ui/dialog";
import { Badge, ErrorBox, Spinner } from "@/components/ui/feedback";
import { Checkbox, Field, Input } from "@/components/ui/form-controls";
import { ApiError, api, newIdempotencyKey } from "@/lib/api";
import { toFaDigits } from "@/lib/format";

export type Role = {
  id: string;
  code: string;
  name: string;
  description: string | null;
  is_system: boolean;
  is_locked: boolean;
  permissions: string[];
  user_count: number;
  row_version: string;
};
type Permission = { code: string; group: string; label: string };

function RoleDialog({ role, open, onClose }: { role: Role | null; open: boolean; onClose: () => void }) {
  const qc = useQueryClient();
  const perms = useQuery({ queryKey: ["permissions"], queryFn: () => api.get<Permission[]>("/roles/permissions") });
  const [code, setCode] = React.useState("");
  const [name, setName] = React.useState("");
  const [selected, setSelected] = React.useState<Set<string>>(new Set());
  const keyRef = React.useRef(newIdempotencyKey());

  React.useEffect(() => {
    if (!open) return;
    keyRef.current = newIdempotencyKey();
    setCode(role?.code ?? "");
    setName(role?.name ?? "");
    setSelected(new Set(role?.permissions ?? []));
  }, [open, role]);

  const groups = React.useMemo(() => {
    const map = new Map<string, Permission[]>();
    for (const p of perms.data ?? []) map.set(p.group, [...(map.get(p.group) ?? []), p]);
    return [...map.entries()];
  }, [perms.data]);

  const save = useMutation({
    mutationFn: () =>
      role
        ? api.patch<Role>(`/roles/${role.id}`, { name, permissions: role.is_locked ? undefined : [...selected] }, role.row_version)
        : api.post<Role>("/roles", { code, name, permissions: [...selected] }, { idempotencyKey: keyRef.current }),
    onSuccess: () => {
      toast.success("نقش ذخیره شد");
      qc.invalidateQueries({ queryKey: ["roles"] });
      onClose();
    },
    onError: (e) => toast.error(e instanceof ApiError ? e.message : "خطا در ذخیره"),
  });

  const toggle = (c: string, on: boolean) =>
    setSelected((s) => {
      const n = new Set(s);
      if (on) n.add(c);
      else n.delete(c);
      return n;
    });

  return (
    <Dialog open={open} onOpenChange={(o) => !o && onClose()}>
      <DialogContent title={role ? `ویرایش نقش ${role.name}` : "نقش جدید"} className="max-w-2xl">
        <div className="grid gap-4 sm:grid-cols-2">
          <Field label="کد نقش" hint="حروف لاتین بزرگ، مثلاً NIGHT_CASHIER">
            <Input dir="ltr" value={code} disabled={!!role} onChange={(e) => setCode(e.target.value.toUpperCase())} />
          </Field>
          <Field label="نام نقش">
            <Input value={name} onChange={(e) => setName(e.target.value)} />
          </Field>
        </div>
        {role?.is_locked ? (
          <p className="mt-4 flex items-center gap-2 rounded-xl bg-warning/15 p-3 text-sm text-ink">
            <Lock className="size-4" /> مجوزهای نقش مدیر سیستم برای جلوگیری از قفل شدن سامانه قابل تغییر نیست.
          </p>
        ) : null}
        <div className="mt-5 flex flex-col gap-4">
          {perms.isLoading ? <Spinner /> : null}
          {groups.map(([group, items]) => (
            <fieldset key={group} className="surface rounded-2xl p-4" disabled={role?.is_locked}>
              <legend className="px-1 text-sm font-semibold text-ink">{group}</legend>
              <div className="mt-1 grid gap-2 sm:grid-cols-2">
                {items.map((p) => (
                  <label key={p.code} className="flex cursor-pointer items-center gap-2 text-sm text-ink-soft">
                    <Checkbox checked={selected.has(p.code)} disabled={role?.is_locked} onCheckedChange={(c) => toggle(p.code, c === true)} />
                    {p.label}
                  </label>
                ))}
              </div>
            </fieldset>
          ))}
        </div>
        <DialogFooter>
          <Button onClick={() => save.mutate()} loading={save.isPending} disabled={!name || (!role && !code)}>
            ذخیره
          </Button>
          <Button variant="ghost" onClick={onClose}>انصراف</Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}

export function RolesPage() {
  const roles = useQuery({ queryKey: ["roles"], queryFn: () => api.get<Role[]>("/roles") });
  const [editing, setEditing] = React.useState<Role | null>(null);
  const [creating, setCreating] = React.useState(false);

  return (
    <>
      <PageTitle
        title="نقش‌ها و مجوزها"
        subtitle="هر مجوز در سرور بررسی می‌شود؛ نقش‌ها فقط مجوزها را دسته‌بندی می‌کنند"
        actions={
          <Button onClick={() => setCreating(true)}>
            <Plus /> نقش جدید
          </Button>
        }
      />
      {roles.isLoading ? <Spinner /> : roles.isError ? <ErrorBox error={roles.error} /> : null}
      <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-3">
        {roles.data?.map((r) => (
          <Card key={r.id} className="flex flex-col p-5">
            <div className="flex items-start justify-between gap-3">
              <div className="flex items-center gap-3">
                <span className="grid size-11 place-items-center rounded-2xl bg-brand-500/10 text-brand-600 dark:text-brand-300">
                  <ShieldCheck className="size-5" />
                </span>
                <div>
                  <p className="font-bold text-ink">{r.name}</p>
                  <p className="text-xs text-ink-faint" dir="ltr">{r.code}</p>
                </div>
              </div>
              {r.is_locked ? <Badge tone="warning">قفل</Badge> : r.is_system ? <Badge tone="info" icon={false}>پیش‌فرض</Badge> : <Badge tone="brand" icon={false}>سفارشی</Badge>}
            </div>
            <div className="mt-4 flex flex-1 items-end justify-between">
              <p className="text-sm text-ink-faint">
                {toFaDigits(r.permissions.length)} مجوز · {toFaDigits(r.user_count)} کاربر
              </p>
              <Button variant="secondary" size="sm" onClick={() => setEditing(r)}>
                <Pencil /> ویرایش
              </Button>
            </div>
          </Card>
        ))}
      </div>
      <RoleDialog role={editing} open={!!editing} onClose={() => setEditing(null)} />
      <RoleDialog role={null} open={creating} onClose={() => setCreating(false)} />
    </>
  );
}
