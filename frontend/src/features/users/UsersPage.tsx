import { zodResolver } from "@hookform/resolvers/zod";
import { keepPreviousData, useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { KeyRound, LockOpen, Pencil, Search, UserPlus, Users } from "lucide-react";
import * as React from "react";
import { type Control, Controller, type FieldValues, useForm, useWatch } from "react-hook-form";
import { toast } from "sonner";
import { z } from "zod";
import { PageTitle } from "@/components/layout/AppShell";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { Dialog, DialogContent, DialogFooter } from "@/components/ui/dialog";
import { Badge, EmptyState, ErrorBox, Spinner } from "@/components/ui/feedback";
import { Checkbox, Field, Input } from "@/components/ui/form-controls";
import { Pagination, Table, Td, Th, Tr } from "@/components/ui/table";
import type { RoleRef } from "@/features/auth/auth";
import type { Role } from "@/features/roles/RolesPage";
import type { Branch } from "@/features/settings/types";
import { ApiError, api, newIdempotencyKey, type Page } from "@/lib/api";
import { formatDateTime, toEnDigits } from "@/lib/format";

export type User = {
  id: string;
  username: string;
  full_name: string;
  is_active: boolean;
  must_change_password: boolean;
  is_locked: boolean;
  last_login_at: string | null;
  roles: RoleRef[];
  all_branches: boolean;
  branch_ids: string[];
  row_version: string;
  created_at: string;
};

const passwordRule = z
  .string()
  .min(8, "حداقل ۸ کاراکتر")
  .regex(/\d/, "باید شامل عدد باشد")
  .regex(/[^\d\s]/, "باید شامل حرف باشد");

const baseSchema = z.object({
  full_name: z.string().trim().min(2, "نام کامل را وارد کنید"),
  role_ids: z.array(z.string()).min(1, "حداقل یک نقش انتخاب کنید"),
  all_branches: z.boolean(),
  branch_ids: z.array(z.string()),
});
const createSchema = baseSchema
  .extend({
    username: z
      .string()
      .trim()
      .min(3, "حداقل ۳ کاراکتر")
      .regex(/^[\w.-]+$/, "فقط حروف لاتین، عدد، نقطه، خط تیره"),
    password: passwordRule,
  })
  .refine((v) => v.all_branches || v.branch_ids.length > 0, {
    path: ["branch_ids"],
    message: "حداقل یک شعبه یا «همه شعب» را انتخاب کنید",
  });
type CreateValues = z.infer<typeof createSchema>;

function useRolesAndBranches() {
  const roles = useQuery({ queryKey: ["roles"], queryFn: () => api.get<Role[]>("/roles") });
  const branches = useQuery({
    queryKey: ["branches"],
    queryFn: () => api.get<Branch[]>("/organization/branches"),
  });
  return { roles: roles.data ?? [], branches: branches.data ?? [] };
}

function RoleAndBranchFields({
  control,
  errors,
}: {
  control: Control<FieldValues>;
  errors: Record<string, { message?: string } | undefined>;
}) {
  const { roles, branches } = useRolesAndBranches();
  const all = Boolean(useWatch({ control, name: "all_branches" }));
  return (
    <>
      <Field label="نقش‌ها" error={errors.role_ids?.message}>
        <Controller
          control={control}
          name="role_ids"
          render={({ field }) => (
            <div className="grid grid-cols-2 gap-2">
              {roles.map((r) => (
                <label key={r.id} className="flex cursor-pointer items-center gap-2 rounded-xl bg-black/[0.03] px-3 py-2 text-sm dark:bg-white/5">
                  <Checkbox
                    checked={field.value.includes(r.id)}
                    onCheckedChange={(c) =>
                      field.onChange(c ? [...field.value, r.id] : field.value.filter((x: string) => x !== r.id))
                    }
                  />
                  {r.name}
                </label>
              ))}
            </div>
          )}
        />
      </Field>
      <Field label="دسترسی به شعب" error={errors.branch_ids?.message}>
        <Controller
          control={control}
          name="all_branches"
          render={({ field }) => (
            <label className="flex cursor-pointer items-center gap-2 text-sm">
              <Checkbox checked={field.value} onCheckedChange={(c) => field.onChange(c === true)} />
              همه شعب (فعلی و آینده)
            </label>
          )}
        />
        <Controller
          control={control}
          name="branch_ids"
          render={({ field }) => {
            return (
              <div className="mt-1 grid grid-cols-2 gap-2">
                {branches.map((b) => (
                  <label key={b.id} className="flex cursor-pointer items-center gap-2 rounded-xl bg-black/[0.03] px-3 py-2 text-sm aria-disabled:opacity-50 dark:bg-white/5" aria-disabled={all || undefined}>
                    <Checkbox
                      disabled={all}
                      checked={field.value.includes(b.id)}
                      onCheckedChange={(c) =>
                        field.onChange(c ? [...field.value, b.id] : field.value.filter((x: string) => x !== b.id))
                      }
                    />
                    {b.name}
                  </label>
                ))}
              </div>
            );
          }}
        />
      </Field>
    </>
  );
}

function CreateUserDialog({ open, onOpenChange }: { open: boolean; onOpenChange: (v: boolean) => void }) {
  const qc = useQueryClient();
  // One key per opened form: double-clicks and retries cannot create two users.
  const keyRef = React.useRef(newIdempotencyKey());
  const form = useForm<CreateValues>({
    resolver: zodResolver(createSchema),
    defaultValues: { username: "", full_name: "", password: "", role_ids: [], all_branches: false, branch_ids: [] },
  });
  React.useEffect(() => {
    if (open) {
      keyRef.current = newIdempotencyKey();
      form.reset();
    }
  }, [open, form]);

  const mutation = useMutation({
    mutationFn: (v: CreateValues) =>
      api.post<User>(
        "/users",
        { ...v, username: toEnDigits(v.username), branch_ids: v.all_branches ? [] : v.branch_ids, must_change_password: true },
        { idempotencyKey: keyRef.current },
      ),
    onSuccess: (u) => {
      toast.success(`کاربر «${u.full_name}» ایجاد شد`);
      qc.invalidateQueries({ queryKey: ["users"] });
      onOpenChange(false);
    },
    onError: (e) => toast.error(e instanceof ApiError ? e.message : "خطا در ایجاد کاربر"),
  });
  const errors = form.formState.errors;

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent title="کاربر جدید" description="کاربر در اولین ورود باید رمز خود را تغییر دهد.">
        <form onSubmit={form.handleSubmit((v) => mutation.mutate(v))} className="flex flex-col gap-4" noValidate>
          <div className="grid gap-4 sm:grid-cols-2">
            <Field label="نام کاربری" htmlFor="u-username" error={errors.username?.message}>
              <Input id="u-username" dir="ltr" autoComplete="off" aria-invalid={!!errors.username} {...form.register("username")} />
            </Field>
            <Field label="نام کامل" htmlFor="u-name" error={errors.full_name?.message}>
              <Input id="u-name" aria-invalid={!!errors.full_name} {...form.register("full_name")} />
            </Field>
          </div>
          <Field label="رمز اولیه" htmlFor="u-pass" error={errors.password?.message} hint="حداقل ۸ کاراکتر، شامل حرف و عدد">
            <Input id="u-pass" type="password" dir="ltr" autoComplete="new-password" aria-invalid={!!errors.password} {...form.register("password")} />
          </Field>
          <RoleAndBranchFields control={form.control as unknown as Control<FieldValues>} errors={errors} />
          <DialogFooter>
            <Button type="submit" loading={mutation.isPending}>ایجاد کاربر</Button>
            <Button type="button" variant="ghost" onClick={() => onOpenChange(false)}>انصراف</Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  );
}

const editSchema = baseSchema.extend({ is_active: z.boolean() }).refine((v) => v.all_branches || v.branch_ids.length > 0, {
  path: ["branch_ids"],
  message: "حداقل یک شعبه یا «همه شعب» را انتخاب کنید",
});
type EditValues = z.infer<typeof editSchema>;

function EditUserDialog({ user, onClose }: { user: User | null; onClose: () => void }) {
  const qc = useQueryClient();
  const form = useForm<EditValues>({ resolver: zodResolver(editSchema) });
  const [resetPw, setResetPw] = React.useState("");

  React.useEffect(() => {
    if (user) {
      form.reset({
        full_name: user.full_name,
        role_ids: user.roles.map((r) => r.id),
        all_branches: user.all_branches,
        branch_ids: user.branch_ids,
        is_active: user.is_active,
      });
      setResetPw("");
    }
  }, [user, form]);

  const save = useMutation({
    mutationFn: (v: EditValues) =>
      api.patch<User>(`/users/${user?.id}`, { ...v, branch_ids: v.all_branches ? [] : v.branch_ids }, user?.row_version ?? ""),
    onSuccess: () => {
      toast.success("تغییرات ذخیره شد");
      qc.invalidateQueries({ queryKey: ["users"] });
      onClose();
    },
    onError: (e) => toast.error(e instanceof ApiError ? e.message : "خطا در ذخیره"),
  });
  const reset = useMutation({
    mutationFn: () => api.post(`/users/${user?.id}/reset-password`, { new_password: resetPw }),
    onSuccess: () => {
      toast.success("رمز جدید تعیین شد؛ کاربر باید در ورود بعدی آن را تغییر دهد");
      setResetPw("");
    },
    onError: (e) => toast.error(e instanceof ApiError ? e.message : "خطا"),
  });
  const unlock = useMutation({
    mutationFn: () => api.post<User>(`/users/${user?.id}/unlock`),
    onSuccess: () => {
      toast.success("قفل حساب برداشته شد");
      qc.invalidateQueries({ queryKey: ["users"] });
      onClose();
    },
  });

  return (
    <Dialog open={!!user} onOpenChange={(o) => !o && onClose()}>
      {user ? (
        <DialogContent title={`ویرایش ${user.full_name}`} description={`نام کاربری: ${user.username}`}>
          <form onSubmit={form.handleSubmit((v) => save.mutate(v))} className="flex flex-col gap-4" noValidate>
            <Field label="نام کامل" htmlFor="e-name" error={form.formState.errors.full_name?.message}>
              <Input id="e-name" {...form.register("full_name")} />
            </Field>
            <RoleAndBranchFields control={form.control as unknown as Control<FieldValues>} errors={form.formState.errors} />
            <Controller
              control={form.control}
              name="is_active"
              render={({ field }) => (
                <label className="flex cursor-pointer items-center gap-2 text-sm">
                  <Checkbox checked={field.value} onCheckedChange={(c) => field.onChange(c === true)} />
                  حساب فعال است
                  <span className="text-xs text-ink-faint">(غیرفعال‌سازی، نشست‌های باز کاربر را می‌بندد)</span>
                </label>
              )}
            />
            <DialogFooter>
              <Button type="submit" loading={save.isPending}>ذخیره</Button>
              <Button type="button" variant="ghost" onClick={onClose}>انصراف</Button>
            </DialogFooter>
          </form>

          <div className="mt-6 flex flex-col gap-3 border-t border-[var(--line)] pt-5">
            <p className="text-sm font-semibold text-ink">امنیت حساب</p>
            <div className="flex gap-2">
              <Input type="password" dir="ltr" placeholder="رمز جدید" value={resetPw} onChange={(e) => setResetPw(e.target.value)} autoComplete="new-password" />
              <Button variant="outline" disabled={resetPw.length < 8} loading={reset.isPending} onClick={() => reset.mutate()}>
                <KeyRound /> تعیین رمز
              </Button>
            </div>
            {user.is_locked ? (
              <Button variant="outline" loading={unlock.isPending} onClick={() => unlock.mutate()}>
                <LockOpen /> رفع قفل حساب
              </Button>
            ) : null}
          </div>
        </DialogContent>
      ) : null}
    </Dialog>
  );
}

export function UsersPage() {
  const [page, setPage] = React.useState(1);
  const [q, setQ] = React.useState("");
  const [search, setSearch] = React.useState("");
  const [creating, setCreating] = React.useState(false);
  const [editing, setEditing] = React.useState<User | null>(null);

  React.useEffect(() => {
    const t = setTimeout(() => {
      setSearch(q);
      setPage(1);
    }, 300);
    return () => clearTimeout(t);
  }, [q]);

  const query = useQuery({
    queryKey: ["users", page, search],
    queryFn: () => api.get<Page<User>>(`/users?page=${page}&page_size=20${search ? `&q=${encodeURIComponent(search)}` : ""}`),
    placeholderData: keepPreviousData,
  });

  return (
    <>
      <PageTitle
        title="کاربران"
        subtitle="تعریف کاربران، نقش‌ها و دسترسی به شعب"
        actions={
          <Button onClick={() => setCreating(true)}>
            <UserPlus /> کاربر جدید
          </Button>
        }
      />
      <Card>
        <div className="flex items-center gap-3 p-4">
          <div className="relative w-full max-w-xs">
            <Search className="pointer-events-none absolute top-1/2 right-3 size-4 -translate-y-1/2 text-ink-faint" />
            <Input value={q} onChange={(e) => setQ(e.target.value)} placeholder="جست‌وجوی نام یا نام کاربری" className="ps-9" />
          </div>
        </div>
        <div className="surface mx-4 mb-4 overflow-hidden rounded-2xl">
          {query.isLoading ? (
            <Spinner />
          ) : query.isError ? (
            <ErrorBox error={query.error} />
          ) : query.data?.items.length === 0 ? (
            <EmptyState icon={Users} title="کاربری یافت نشد" description={search ? "عبارت جست‌وجو را تغییر دهید." : undefined} />
          ) : (
            <>
              <Table>
                <thead>
                  <tr>
                    <Th>کاربر</Th>
                    <Th>نقش‌ها</Th>
                    <Th>شعب</Th>
                    <Th>وضعیت</Th>
                    <Th>آخرین ورود</Th>
                    <Th className="w-12" />
                  </tr>
                </thead>
                <tbody>
                  {query.data?.items.map((u) => (
                    <Tr key={u.id}>
                      <Td>
                        <p className="font-medium text-ink">{u.full_name}</p>
                        <p className="text-xs text-ink-faint" dir="ltr">{u.username}</p>
                      </Td>
                      <Td>
                        <div className="flex flex-wrap gap-1">
                          {u.roles.map((r) => (
                            <Badge key={r.id} tone="brand" icon={false}>{r.name}</Badge>
                          ))}
                        </div>
                      </Td>
                      <Td className="text-ink-soft">{u.all_branches ? "همه شعب" : `${u.branch_ids.length.toLocaleString("fa-IR")} شعبه`}</Td>
                      <Td>
                        {!u.is_active ? (
                          <Badge tone="neutral">غیرفعال</Badge>
                        ) : u.is_locked ? (
                          <Badge tone="danger">قفل‌شده</Badge>
                        ) : u.must_change_password ? (
                          <Badge tone="warning">منتظر تغییر رمز</Badge>
                        ) : (
                          <Badge tone="success">فعال</Badge>
                        )}
                      </Td>
                      <Td className="tabular text-ink-faint">{u.last_login_at ? formatDateTime(u.last_login_at) : "—"}</Td>
                      <Td>
                        <Button variant="ghost" size="icon" aria-label={`ویرایش ${u.full_name}`} onClick={() => setEditing(u)}>
                          <Pencil />
                        </Button>
                      </Td>
                    </Tr>
                  ))}
                </tbody>
              </Table>
              <Pagination page={page} pageSize={20} total={query.data?.total ?? 0} onPage={setPage} />
            </>
          )}
        </div>
      </Card>
      <CreateUserDialog open={creating} onOpenChange={setCreating} />
      <EditUserDialog user={editing} onClose={() => setEditing(null)} />
    </>
  );
}
