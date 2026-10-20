import { useMutation, useQueryClient } from "@tanstack/react-query";
import { ChevronDown, ChevronLeft, FolderTree, Pencil, Plus } from "lucide-react";
import * as React from "react";
import { toast } from "sonner";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { Dialog, DialogContent, DialogFooter } from "@/components/ui/dialog";
import { Badge, ErrorBox, Spinner } from "@/components/ui/feedback";
import { Checkbox, Field, Input, Select } from "@/components/ui/form-controls";
import { useCan } from "@/features/auth/auth";
import { ApiError, api, newIdempotencyKey } from "@/lib/api";
import { toEnDigits, toFaDigits } from "@/lib/format";
import { cn } from "@/lib/utils";
import { type Account, CATEGORY_LABEL, type Category, LEVEL_LABEL, NATURE_LABEL, type Nature, useAccounts } from "./api";

const onError = (e: unknown) => toast.error(e instanceof ApiError ? e.message : "خطا");

type Editing = { mode: "create"; parent: Account | null } | { mode: "edit"; account: Account };

function AccountDialog({ editing, onClose }: { editing: Editing | null; onClose: () => void }) {
  const qc = useQueryClient();
  const [code, setCode] = React.useState("");
  const [name, setName] = React.useState("");
  const [category, setCategory] = React.useState<Category>("asset");
  const [nature, setNature] = React.useState<Nature>("debit");
  const [requiresDetail, setRequiresDetail] = React.useState(false);
  const [active, setActive] = React.useState(true);
  const keyRef = React.useRef(newIdempotencyKey());

  React.useEffect(() => {
    if (!editing) return;
    keyRef.current = newIdempotencyKey();
    if (editing.mode === "edit") {
      const a = editing.account;
      setCode(a.code);
      setName(a.name);
      setNature(a.nature);
      setRequiresDetail(a.requires_detail);
      setActive(a.is_active);
    } else {
      setCode(editing.parent?.code ?? "");
      setName("");
      setNature(editing.parent?.nature ?? "debit");
      setRequiresDetail(false);
      setActive(true);
    }
  }, [editing]);

  const save = useMutation({
    mutationFn: () => {
      if (!editing) throw new Error();
      if (editing.mode === "edit")
        return api.patch<Account>(
          `/accounting/accounts/${editing.account.id}`,
          { name, nature, requires_detail: requiresDetail, is_active: active },
          editing.account.row_version,
        );
      return api.post<Account>(
        "/accounting/accounts",
        {
          code: toEnDigits(code),
          name,
          parent_id: editing.parent?.id ?? null,
          ...(editing.parent ? { nature } : { category, nature }),
          requires_detail: requiresDetail,
        },
        { idempotencyKey: keyRef.current },
      );
    },
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["accounting", "accounts"] });
      toast.success("حساب ذخیره شد");
      onClose();
    },
    onError,
  });

  const parent = editing?.mode === "create" ? editing.parent : null;
  const isLeaf = editing?.mode === "edit" ? editing.account.level === "subsidiary" : parent?.level === "general";
  const title =
    editing?.mode === "edit"
      ? `ویرایش حساب ${toFaDigits(editing.account.code)}`
      : parent
        ? `حساب ${parent.level === "group" ? "کل" : "معین"} جدید زیر «${parent.name}»`
        : "گروه حساب جدید";

  return (
    <Dialog open={!!editing} onOpenChange={(o) => !o && onClose()}>
      <DialogContent title={title}>
        <div className="flex flex-col gap-4">
          <div className="grid grid-cols-[8rem_1fr] gap-3">
            <Field label="کد" hint={parent ? `با ${toFaDigits(parent.code)} شروع شود` : undefined}>
              <Input dir="ltr" value={code} disabled={editing?.mode === "edit"} onChange={(e) => setCode(toEnDigits(e.target.value).replace(/\D/g, ""))} />
            </Field>
            <Field label="نام حساب">
              <Input value={name} onChange={(e) => setName(e.target.value)} />
            </Field>
          </div>
          <div className="grid grid-cols-2 gap-3">
            {!parent && editing?.mode === "create" ? (
              <Field label="نوع حساب">
                <Select value={category} onChange={(e) => setCategory(e.target.value as Category)}>
                  {Object.entries(CATEGORY_LABEL).map(([k, v]) => (
                    <option key={k} value={k}>{v}</option>
                  ))}
                </Select>
              </Field>
            ) : null}
            <Field label="ماهیت">
              <Select value={nature} onChange={(e) => setNature(e.target.value as Nature)}>
                <option value="debit">بدهکار</option>
                <option value="credit">بستانکار</option>
                <option value="none">بدون ماهیت</option>
              </Select>
            </Field>
          </div>
          {isLeaf ? (
            <label className="flex cursor-pointer items-center gap-2 text-sm">
              <Checkbox checked={requiresDetail} onCheckedChange={(c) => setRequiresDetail(c === true)} />
              ثبت در این حساب نیازمند حساب تفصیلی است (مثلاً مشتری یا بانک)
            </label>
          ) : null}
          {editing?.mode === "edit" ? (
            <label className="flex cursor-pointer items-center gap-2 text-sm">
              <Checkbox checked={active} onCheckedChange={(c) => setActive(c === true)} />
              حساب فعال است
            </label>
          ) : null}
        </div>
        <DialogFooter>
          <Button onClick={() => save.mutate()} loading={save.isPending} disabled={!code || name.length < 2}>
            ذخیره
          </Button>
          <Button variant="ghost" onClick={onClose}>انصراف</Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}

export function AccountsPage() {
  const can = useCan();
  const accounts = useAccounts();
  const [collapsed, setCollapsed] = React.useState<Set<string>>(new Set());
  const [editing, setEditing] = React.useState<Editing | null>(null);
  const [filter, setFilter] = React.useState("");
  const manage = can("accounting.account.manage");

  const children = React.useMemo(() => {
    const m = new Map<string | null, Account[]>();
    for (const a of accounts.data ?? []) m.set(a.parent_id, [...(m.get(a.parent_id) ?? []), a]);
    return m;
  }, [accounts.data]);

  const q = toEnDigits(filter.trim());
  const matches = (a: Account) => !q || a.code.startsWith(q) || a.name.includes(q);
  const visibleTree = (a: Account): boolean => matches(a) || (children.get(a.id) ?? []).some(visibleTree);

  const render = (a: Account, depth: number): React.ReactNode => {
    if (!visibleTree(a)) return null;
    const kids = children.get(a.id) ?? [];
    const open = q ? true : !collapsed.has(a.id);
    return (
      <React.Fragment key={a.id}>
        <tr className={cn("border-t border-[var(--line)] transition-colors hover:bg-brand-500/[0.04]", !a.is_active && "opacity-50")}>
          <td className="py-2.5 pe-3" style={{ paddingInlineStart: `${depth * 1.5 + 0.75}rem` }}>
            <div className="flex items-center gap-2">
              {kids.length ? (
                <button
                  type="button"
                  aria-label={open ? "بستن" : "باز کردن"}
                  onClick={() =>
                    setCollapsed((s) => {
                      const n = new Set(s);
                      if (n.has(a.id)) n.delete(a.id);
                      else n.add(a.id);
                      return n;
                    })
                  }
                  className="text-ink-faint hover:text-ink"
                >
                  {open ? <ChevronDown className="size-4" /> : <ChevronLeft className="size-4" />}
                </button>
              ) : (
                <span className="w-4" />
              )}
              <span className={cn("tabular text-ink-faint", a.level === "group" && "font-bold text-ink")}>{toFaDigits(a.code)}</span>
              <span className={cn(a.level === "group" ? "font-bold" : a.level === "general" ? "font-semibold" : "", "text-ink")}>{a.name}</span>
            </div>
          </td>
          <td className="px-3 text-ink-soft">{LEVEL_LABEL[a.level]}</td>
          <td className="px-3 text-ink-soft">{CATEGORY_LABEL[a.category]}</td>
          <td className="px-3 text-ink-soft">{NATURE_LABEL[a.nature]}</td>
          <td className="px-3">
            {a.requires_detail ? <Badge tone="info" icon={false}>تفصیلی</Badge> : null}
            {!a.is_active ? <Badge tone="neutral">غیرفعال</Badge> : null}
          </td>
          <td className="px-2 whitespace-nowrap">
            {manage ? (
              <div className="flex justify-end gap-1">
                {a.level !== "subsidiary" ? (
                  <Button variant="ghost" size="icon" aria-label={`زیرحساب برای ${a.name}`} onClick={() => setEditing({ mode: "create", parent: a })}>
                    <Plus />
                  </Button>
                ) : null}
                <Button variant="ghost" size="icon" aria-label={`ویرایش ${a.name}`} onClick={() => setEditing({ mode: "edit", account: a })}>
                  <Pencil />
                </Button>
              </div>
            ) : null}
          </td>
        </tr>
        {open ? kids.map((k) => render(k, depth + 1)) : null}
      </React.Fragment>
    );
  };

  return (
    <Card>
      <div className="flex flex-wrap items-center gap-3 p-4">
        <Input className="max-w-xs" placeholder="جست‌وجوی کد یا نام حساب" value={filter} onChange={(e) => setFilter(e.target.value)} />
        <Button variant="ghost" size="sm" onClick={() => setCollapsed(new Set((accounts.data ?? []).filter((a) => a.level !== "subsidiary").map((a) => a.id)))}>
          بستن همه
        </Button>
        <Button variant="ghost" size="sm" onClick={() => setCollapsed(new Set())}>
          باز کردن همه
        </Button>
        <div className="flex-1" />
        {manage ? (
          <Button onClick={() => setEditing({ mode: "create", parent: null })}>
            <FolderTree /> گروه جدید
          </Button>
        ) : null}
      </div>
      <div className="surface mx-4 mb-4 overflow-x-auto rounded-2xl">
        {accounts.isLoading ? (
          <Spinner />
        ) : accounts.isError ? (
          <ErrorBox error={accounts.error} />
        ) : (
          <table className="w-full min-w-[48rem] text-sm">
            <thead>
              <tr className="text-xs text-ink-faint">
                <th className="px-3 py-3 text-start">حساب</th>
                <th className="w-20 px-3 py-3 text-start">سطح</th>
                <th className="w-28 px-3 py-3 text-start">نوع</th>
                <th className="w-24 px-3 py-3 text-start">ماهیت</th>
                <th className="w-32 px-3 py-3 text-start" />
                <th className="w-24" />
              </tr>
            </thead>
            <tbody>{(children.get(null) ?? []).map((g) => render(g, 0))}</tbody>
          </table>
        )}
      </div>
      <AccountDialog editing={editing} onClose={() => setEditing(null)} />
    </Card>
  );
}
