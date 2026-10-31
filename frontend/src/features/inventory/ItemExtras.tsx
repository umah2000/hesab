import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { AlertTriangle, CalendarClock, CheckCircle2, ImagePlus, Plus, X } from "lucide-react";
import * as React from "react";
import { toast } from "sonner";
import { Button } from "@/components/ui/button";
import { Dialog, DialogContent, DialogFooter } from "@/components/ui/dialog";
import { Badge, Spinner } from "@/components/ui/feedback";
import { Checkbox, Field, Input, Select } from "@/components/ui/form-controls";
import { Table, Td, Th, Tr } from "@/components/ui/table";
import { JalaliDateInput, MoneyInput } from "@/features/accounting/inputs";
import { ApiError, api, newIdempotencyKey, upload } from "@/lib/api";
import { toEnDigits, toFaDigits } from "@/lib/format";
import { isoToJalaliFa } from "@/lib/jalali";
import { type Group, type ItemImage, trimQty, useGroups, useWarehouses } from "./api";

/** «+» beside the group list: a new item group without leaving the item form. */
export function NewGroupButton({ onCreated }: { onCreated: (id: string) => void }) {
  const qc = useQueryClient();
  const groups = useGroups();
  const [open, setOpen] = React.useState(false);
  const [name, setName] = React.useState("");
  const [code, setCode] = React.useState("");
  const keyRef = React.useRef(newIdempotencyKey());
  const start = () => {
    keyRef.current = newIdempotencyKey();
    setName("");
    // A free code suggestion; the user may type another.
    const taken = new Set(groups.data?.map((g) => g.code) ?? []);
    let n = (groups.data?.length ?? 0) + 1;
    while (taken.has(`G${n}`)) n += 1;
    setCode(`G${n}`);
    setOpen(true);
  };
  const save = useMutation({
    mutationFn: () =>
      api.post<Group>("/inventory/groups", { name: name.trim(), code: toEnDigits(code.trim()).toUpperCase() }, { idempotencyKey: keyRef.current }),
    onSuccess: (g) => {
      qc.invalidateQueries({ queryKey: ["inventory", "groups"] });
      toast.success(`گروه «${g.name}» ساخته شد`);
      onCreated(g.id);
      setOpen(false);
    },
    onError: (e) => toast.error(e instanceof ApiError ? e.message : "خطا"),
  });
  return (
    <>
      <Button type="button" variant="outline" size="icon" aria-label="گروه جدید" title="گروه جدید" onClick={start}>
        <Plus />
      </Button>
      <Dialog open={open} onOpenChange={setOpen}>
        <DialogContent title="گروه کالای جدید" className="max-w-sm">
          <div className="flex flex-col gap-3">
            <Field label="نام گروه">
              <Input autoFocus value={name} onChange={(e) => setName(e.target.value)} placeholder="مثلاً لبنیات" />
            </Field>
            <Field label="کد گروه" hint="حروف لاتین و رقم">
              <Input dir="ltr" value={code} onChange={(e) => setCode(e.target.value)} />
            </Field>
          </div>
          <DialogFooter>
            <Button onClick={() => save.mutate()} loading={save.isPending} disabled={name.trim().length < 2 || !code.trim()}>
              ساخت گروه
            </Button>
            <Button variant="ghost" onClick={() => setOpen(false)}>انصراف</Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </>
  );
}

const ACCEPT = "image/jpeg,image/png,image/webp";
const MAX_BYTES = 15 * 1024 * 1024;
const MAX_IMAGES = 6;

/** Photos chosen before the item exists; uploaded right after it is saved. */
export function PendingImages({ files, onChange }: { files: File[]; onChange: (f: File[]) => void }) {
  const input = React.useRef<HTMLInputElement>(null);
  const urls = React.useMemo(() => files.map((f) => URL.createObjectURL(f)), [files]);
  React.useEffect(() => () => urls.forEach((u) => URL.revokeObjectURL(u)), [urls]);
  const add = (list: FileList | null) => {
    if (!list?.length) return;
    const ok = Array.from(list).filter((f) => {
      if (f.size > MAX_BYTES) toast.error(`«${f.name}» بیش از ۱۵ مگابایت است`);
      return f.size <= MAX_BYTES;
    });
    const all = [...files, ...ok];
    if (all.length > MAX_IMAGES) toast.warning(`هر کالا حداکثر ${toFaDigits(MAX_IMAGES)} عکس دارد`);
    onChange(all.slice(0, MAX_IMAGES));
  };
  return (
    <fieldset className="flex flex-col gap-2">
      <legend className="mb-1 text-sm font-semibold text-ink">عکس‌های کالا</legend>
      <div className="flex flex-wrap gap-3">
        {urls.map((u, i) => (
          <div key={u} className="relative size-28 overflow-hidden rounded-xl ring-1 ring-[var(--line)]">
            <img src={u} alt="" className="size-full object-cover" />
            {i === 0 ? <Badge tone="success" className="absolute top-1 right-1">اصلی</Badge> : null}
            <Button
              type="button"
              variant="ghost"
              size="icon"
              className="absolute top-1 left-1 size-7 bg-white/80 dark:bg-black/60"
              aria-label="برداشتن عکس"
              onClick={() => onChange(files.filter((_, j) => j !== i))}
            >
              <X />
            </Button>
          </div>
        ))}
        {files.length < MAX_IMAGES ? (
          <button
            type="button"
            onClick={() => input.current?.click()}
            className="flex size-28 flex-col items-center justify-center gap-1 rounded-xl border-2 border-dashed border-[var(--line)] text-xs text-ink-soft hover:border-brand-500 hover:text-brand-600"
          >
            <ImagePlus className="size-6" />
            افزودن عکس
          </button>
        ) : null}
      </div>
      <input ref={input} type="file" accept={ACCEPT} multiple hidden onChange={(e) => { add(e.target.files); e.target.value = ""; }} />
      <p className="text-xs text-ink-faint">عکس‌ها با ذخیره‌ی کالا بارگذاری می‌شوند؛ اولی عکس اصلی است.</p>
    </fieldset>
  );
}

/** Upload the chosen photos to the new item, in order; failures are reported, not fatal. */
export async function uploadPending(itemId: string, files: File[]): Promise<number> {
  let done = 0;
  for (const f of files) {
    try {
      await upload<ItemImage>(`/inventory/items/${itemId}/images`, f);
      done += 1;
    } catch (e) {
      toast.error(e instanceof ApiError ? `«${f.name}»: ${e.message}` : `«${f.name}» بارگذاری نشد`);
    }
  }
  return done;
}

export type OpeningState = { on: boolean; warehouse_id: string; qty: string; cost: string; expiry: string | null };
export const noOpening: OpeningState = { on: false, warehouse_id: "", qty: "", cost: "", expiry: null };

/** Optional stock the new item starts with: one opening stock document (ADR-0027). */
export function OpeningStock({
  value,
  onChange,
  unitName,
  trackExpiry,
}: {
  value: OpeningState;
  onChange: (v: OpeningState) => void;
  unitName: string;
  trackExpiry: boolean;
}) {
  const warehouses = useWarehouses();
  const set = <K extends keyof OpeningState>(k: K, v: OpeningState[K]) => onChange({ ...value, [k]: v });
  React.useEffect(() => {
    if (value.on && !value.warehouse_id && warehouses.data?.length) set("warehouse_id", warehouses.data[0].id);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [value.on, warehouses.data]);
  return (
    <fieldset className="surface rounded-2xl p-4">
      <legend className="px-1 text-sm font-semibold text-ink">موجودی اولیه</legend>
      <label className="flex cursor-pointer items-center gap-2 text-sm">
        <Checkbox checked={value.on} onCheckedChange={(c) => set("on", c === true)} />
        این کالا را با موجودی ثبت کن (سند موجودی اول دوره)
      </label>
      {value.on ? (
        <div className="mt-3 grid gap-3 sm:grid-cols-4">
          <Field label="انبار">
            <Select value={value.warehouse_id} onChange={(e) => set("warehouse_id", e.target.value)}>
              {warehouses.data?.map((w) => (
                <option key={w.id} value={w.id}>{w.name}</option>
              ))}
            </Select>
          </Field>
          <Field label={`تعداد (${unitName || "واحد اصلی"})`}>
            <Input dir="ltr" inputMode="decimal" value={value.qty} onChange={(e) => set("qty", e.target.value)} />
          </Field>
          <Field label="بهای خرید هر واحد">
            <MoneyInput value={value.cost} onChange={(v) => set("cost", v)} />
          </Field>
          {trackExpiry ? (
            <Field label="تاریخ انقضا" hint="شمسی، مثلاً ۱۴۰۵/۱۲/۲۹">
              <JalaliDateInput value={value.expiry} onChange={(v) => set("expiry", v)} invalid={!value.expiry} />
            </Field>
          ) : null}
        </div>
      ) : null}
    </fieldset>
  );
}

type Lot = {
  warehouse_id: string;
  warehouse_name: string;
  expiry_date: string | null;
  days_left: number | null;
  qty: string;
  first_received: string;
};

/** How soon a lot expires, as text and icon (never colour alone). */
export function ExpiryBadge({ days, urgent = 7, warn = 30 }: { days: number | null; urgent?: number; warn?: number }) {
  if (days === null) return <Badge tone="neutral" icon={false}>بدون تاریخ</Badge>;
  if (days < 0)
    return (
      <Badge tone="danger" icon={false}>
        <AlertTriangle className="size-3.5" /> منقضی ({toFaDigits(-days)} روز پیش)
      </Badge>
    );
  if (days <= urgent)
    return (
      <Badge tone="danger" icon={false}>
        <CalendarClock className="size-3.5" /> {toFaDigits(days)} روز مانده
      </Badge>
    );
  if (days <= warn)
    return (
      <Badge tone="warning" icon={false}>
        <CalendarClock className="size-3.5" /> {toFaDigits(days)} روز مانده
      </Badge>
    );
  return (
    <Badge tone="success" icon={false}>
      <CheckCircle2 className="size-3.5" /> {toFaDigits(days)} روز مانده
    </Badge>
  );
}

/** The item's batches by expiry date, earliest first. */
export function ItemLots({ itemId, unitName, urgent, warn }: { itemId: string; unitName: string; urgent?: number; warn?: number }) {
  const lots = useQuery({ queryKey: ["inventory", "item-lots", itemId], queryFn: () => api.get<Lot[]>(`/inventory/items/${itemId}/lots`) });
  return (
    <fieldset className="surface rounded-2xl p-4">
      <legend className="px-1 text-sm font-semibold text-ink">دسته‌ها و تاریخ انقضا</legend>
      {lots.isLoading ? (
        <Spinner />
      ) : !lots.data?.length ? (
        <p className="text-sm text-ink-soft">موجودی ندارد.</p>
      ) : (
        <Table>
          <thead>
            <tr>
              <Th>انبار</Th>
              <Th>تاریخ انقضا</Th>
              <Th>وضعیت</Th>
              <Th className="text-end">مقدار ({unitName})</Th>
            </tr>
          </thead>
          <tbody>
            {lots.data.map((l) => (
              <Tr key={`${l.warehouse_id}-${l.expiry_date}`}>
                <Td>{l.warehouse_name}</Td>
                <Td className="tabular">{l.expiry_date ? isoToJalaliFa(l.expiry_date) : "—"}</Td>
                <Td><ExpiryBadge days={l.days_left} urgent={urgent} warn={warn} /></Td>
                <Td className="tabular text-end">{toFaDigits(trimQty(l.qty))}</Td>
              </Tr>
            ))}
          </tbody>
        </Table>
      )}
      <p className="mt-2 text-xs text-ink-faint">فروش و خروج از زودانقضاترین دسته کم می‌شود.</p>
    </fieldset>
  );
}
