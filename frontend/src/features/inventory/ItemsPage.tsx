import { keepPreviousData, useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { PackagePlus, Pencil, Plus, ScanBarcode, Search, Trash2 } from "lucide-react";
import * as React from "react";
import { toast } from "sonner";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { Dialog, DialogContent, DialogFooter } from "@/components/ui/dialog";
import { Badge, EmptyState, ErrorBox, Spinner } from "@/components/ui/feedback";
import { Checkbox, Field, Input, Select } from "@/components/ui/form-controls";
import { Pagination, Table, Td, Th, Tr } from "@/components/ui/table";
import { useCurrency } from "@/features/accounting/api";
import { MoneyInput } from "@/features/accounting/inputs";
import { useCan } from "@/features/auth/auth";
import { ApiError, api, newIdempotencyKey, type Page } from "@/lib/api";
import { formatMoney, toEnDigits, toFaDigits } from "@/lib/format";
import { inputToRials, rialsToInput } from "@/lib/money";
import { cn } from "@/lib/utils";
import { type Item, type ItemSummary, trimQty, useGroups, useUnits } from "./api";

type FormState = {
  code: string;
  name: string;
  group_id: string;
  base_unit_id: string;
  item_type: "goods" | "service";
  is_weighted: boolean;
  scale_code: string;
  track_expiry: boolean;
  vat_exempt: boolean;
  vat_rate: string;
  min_qty: string;
  is_active: boolean;
  units: { unit_id: string; factor: string }[];
  barcodes: { barcode: string; unit_id: string }[];
  prices: Record<string, string>; // unit_id → display-currency text (default list)
};

const blank = (unit: string): FormState => ({
  code: "",
  name: "",
  group_id: "",
  base_unit_id: unit,
  item_type: "goods",
  is_weighted: false,
  scale_code: "",
  track_expiry: false,
  vat_exempt: false,
  vat_rate: "",
  min_qty: "",
  is_active: true,
  units: [],
  barcodes: [],
  prices: {},
});

function ItemDialog({ itemId, open, onClose }: { itemId: string | null; open: boolean; onClose: () => void }) {
  const qc = useQueryClient();
  const can = useCan();
  const currency = useCurrency();
  const units = useUnits();
  const groups = useGroups();
  const item = useQuery({
    queryKey: ["inventory", "item", itemId],
    queryFn: () => api.get<Item>(`/inventory/items/${itemId}`),
    enabled: open && !!itemId,
  });
  const [f, setF] = React.useState<FormState>(blank(""));
  const [scan, setScan] = React.useState("");
  const keyRef = React.useRef(newIdempotencyKey());
  const canPrice = can("inventory.price.manage");

  React.useEffect(() => {
    if (!open) return;
    keyRef.current = newIdempotencyKey();
    const it = item.data;
    if (itemId && !it) return;
    if (!it) {
      setF(blank(units.data?.find((u) => u.code === "PCS")?.id ?? units.data?.[0]?.id ?? ""));
      return;
    }
    setF({
      code: it.code,
      name: it.name,
      group_id: it.group_id ?? "",
      base_unit_id: it.base_unit_id,
      item_type: it.item_type,
      is_weighted: it.is_weighted,
      scale_code: it.scale_code ?? "",
      track_expiry: it.track_expiry,
      vat_exempt: it.vat_exempt,
      vat_rate: it.vat_rate ?? "",
      min_qty: it.min_qty ? trimQty(it.min_qty) : "",
      is_active: it.is_active,
      units: it.units.map((u) => ({ unit_id: u.unit_id, factor: trimQty(u.factor) })),
      barcodes: it.barcodes.map((b) => ({ barcode: b.barcode, unit_id: b.unit_id ?? "" })),
      prices: Object.fromEntries(it.prices.filter((p) => p.unit_id).map((p) => [p.unit_id as string, rialsToInput(p.price, currency)])),
    });
  }, [open, item.data, itemId, units.data, currency]);

  const unitName = (id: string) => units.data?.find((u) => u.id === id)?.name ?? "";
  const set = <K extends keyof FormState>(k: K, v: FormState[K]) => setF((s) => ({ ...s, [k]: v }));

  const save = useMutation({
    mutationFn: () => {
      const prices = Object.entries(f.prices)
        .filter(([, v]) => v !== "")
        .map(([unit_id, v]) => {
          const r = inputToRials(v, currency);
          if (r === null) throw new ApiError(0, "invalid", `قیمت «${unitName(unit_id)}» نامعتبر است`);
          return { unit_id, price: r };
        });
      const body = {
        code: toEnDigits(f.code.trim()),
        name: f.name.trim(),
        group_id: f.group_id || null,
        base_unit_id: f.base_unit_id,
        item_type: f.item_type,
        is_weighted: f.is_weighted,
        scale_code: toEnDigits(f.scale_code.trim()) || null,
        track_expiry: f.track_expiry,
        vat_exempt: f.vat_exempt,
        vat_rate: f.vat_exempt || !f.vat_rate ? null : toEnDigits(f.vat_rate),
        min_qty: f.min_qty ? toEnDigits(f.min_qty) : null,
        is_active: f.is_active,
        units: f.units.filter((u) => u.unit_id && u.factor).map((u) => ({ unit_id: u.unit_id, factor: toEnDigits(u.factor) })),
        barcodes: f.barcodes.map((b) => ({ barcode: b.barcode, unit_id: b.unit_id || null })),
        prices: canPrice ? prices : [],
      };
      return itemId
        ? api.put<Item>(`/inventory/items/${itemId}`, body, item.data?.row_version ?? "")
        : api.post<Item>("/inventory/items", body, { idempotencyKey: keyRef.current });
    },
    onSuccess: (it) => {
      qc.invalidateQueries({ queryKey: ["inventory"] });
      toast.success(`کالای «${it.name}» ذخیره شد`);
      onClose();
    },
    onError: (e) => toast.error(e instanceof ApiError ? e.message : "خطا"),
  });

  const addBarcode = () => {
    const b = toEnDigits(scan.trim()).toUpperCase();
    if (!b) return;
    if (f.barcodes.some((x) => x.barcode === b)) {
      toast.error("این بارکد قبلاً اضافه شده است");
    } else {
      set("barcodes", [...f.barcodes, { barcode: b, unit_id: "" }]);
    }
    setScan("");
  };

  const allUnits = [f.base_unit_id, ...f.units.map((u) => u.unit_id)].filter(Boolean);

  return (
    <Dialog open={open} onOpenChange={(o) => !o && onClose()}>
      <DialogContent title={itemId ? `ویرایش ${item.data?.name ?? ""}` : "کالای جدید"} className="max-w-3xl">
        {itemId && item.isLoading ? (
          <Spinner />
        ) : (
          <div className="flex flex-col gap-5">
            <div className="grid gap-3 sm:grid-cols-[9rem_1fr_12rem]">
              <Field label="کد کالا">
                <Input dir="ltr" value={f.code} onChange={(e) => set("code", e.target.value)} />
              </Field>
              <Field label="نام کالا">
                <Input value={f.name} onChange={(e) => set("name", e.target.value)} />
              </Field>
              <Field label="گروه">
                <Select value={f.group_id} onChange={(e) => set("group_id", e.target.value)}>
                  <option value="">بدون گروه</option>
                  {groups.data?.map((g) => (
                    <option key={g.id} value={g.id}>{g.name}</option>
                  ))}
                </Select>
              </Field>
            </div>
            <div className="grid gap-3 sm:grid-cols-4">
              <Field label="واحد اصلی">
                <Select value={f.base_unit_id} onChange={(e) => set("base_unit_id", e.target.value)}>
                  {units.data?.map((u) => (
                    <option key={u.id} value={u.id}>{u.name}</option>
                  ))}
                </Select>
              </Field>
              <Field label="نوع">
                <Select value={f.item_type} onChange={(e) => set("item_type", e.target.value as FormState["item_type"])}>
                  <option value="goods">کالا</option>
                  <option value="service">خدمت</option>
                </Select>
              </Field>
              <Field label="حداقل موجودی" hint="برای هشدار کمبود">
                <Input dir="ltr" inputMode="decimal" value={f.min_qty} onChange={(e) => set("min_qty", e.target.value)} />
              </Field>
              <Field label="کد ترازو (PLU)" hint="برای برچسب ترازو">
                <Input dir="ltr" inputMode="numeric" value={f.scale_code} onChange={(e) => set("scale_code", e.target.value)} />
              </Field>
            </div>
            <div className="flex flex-wrap gap-x-6 gap-y-2 text-sm">
              {(
                [
                  ["is_weighted", "کالای وزنی"],
                  ["track_expiry", "تاریخ انقضا دارد"],
                  ["vat_exempt", "معاف از مالیات بر ارزش افزوده"],
                  ["is_active", "فعال"],
                ] as const
              ).map(([k, label]) => (
                <label key={k} className="flex cursor-pointer items-center gap-2">
                  <Checkbox checked={f[k]} onCheckedChange={(c) => set(k, c === true)} />
                  {label}
                </label>
              ))}
              {!f.vat_exempt ? (
                <label className="flex items-center gap-2">
                  نرخ اختصاصی مالیات (٪):
                  <Input className="h-8 w-20" dir="ltr" placeholder="پیش‌فرض" value={f.vat_rate} onChange={(e) => set("vat_rate", e.target.value)} />
                </label>
              ) : null}
            </div>

            <fieldset className="surface rounded-2xl p-4">
              <legend className="px-1 text-sm font-semibold text-ink">واحدهای فرعی</legend>
              <div className="flex flex-col gap-2">
                {f.units.map((u, i) => (
                  <div key={i} className="flex items-center gap-2 text-sm">
                    <span>هر</span>
                    <Select className="w-36" value={u.unit_id} onChange={(e) => set("units", f.units.map((x, j) => (j === i ? { ...x, unit_id: e.target.value } : x)))}>
                      <option value="">انتخاب</option>
                      {units.data?.filter((x) => x.id !== f.base_unit_id).map((x) => (
                        <option key={x.id} value={x.id}>{x.name}</option>
                      ))}
                    </Select>
                    <span>=</span>
                    <Input className="w-24" dir="ltr" value={u.factor} onChange={(e) => set("units", f.units.map((x, j) => (j === i ? { ...x, factor: e.target.value } : x)))} />
                    <span>{unitName(f.base_unit_id)}</span>
                    <Button variant="ghost" size="icon" aria-label="حذف واحد" onClick={() => set("units", f.units.filter((_, j) => j !== i))}>
                      <Trash2 />
                    </Button>
                  </div>
                ))}
                <Button variant="ghost" size="sm" className="self-start" onClick={() => set("units", [...f.units, { unit_id: "", factor: "" }])}>
                  <Plus /> واحد فرعی (مثلاً کارتن)
                </Button>
              </div>
            </fieldset>

            <fieldset className="surface rounded-2xl p-4">
              <legend className="px-1 text-sm font-semibold text-ink">بارکدها</legend>
              <div className="flex gap-2">
                <div className="relative flex-1">
                  <ScanBarcode className="pointer-events-none absolute top-1/2 right-3 size-4 -translate-y-1/2 text-brand-500" />
                  <Input
                    className="ps-9"
                    dir="ltr"
                    placeholder="بارکد را اسکن کنید و Enter"
                    value={scan}
                    onChange={(e) => setScan(e.target.value)}
                    onKeyDown={(e) => {
                      if (e.key === "Enter") {
                        e.preventDefault();
                        addBarcode();
                      }
                    }}
                  />
                </div>
                <Button variant="outline" onClick={addBarcode}>افزودن</Button>
              </div>
              <div className="mt-3 flex flex-col gap-2">
                {f.barcodes.map((b, i) => (
                  <div key={b.barcode} className="flex items-center gap-2 text-sm">
                    <span className="tabular flex-1 rounded-lg bg-black/[0.03] px-3 py-1.5 dark:bg-white/5" dir="ltr">{b.barcode}</span>
                    <Select className="h-9 w-36" value={b.unit_id} onChange={(e) => set("barcodes", f.barcodes.map((x, j) => (j === i ? { ...x, unit_id: e.target.value } : x)))} aria-label="واحد بارکد">
                      <option value="">{unitName(f.base_unit_id) || "واحد اصلی"}</option>
                      {f.units.filter((u) => u.unit_id).map((u) => (
                        <option key={u.unit_id} value={u.unit_id}>{unitName(u.unit_id)}</option>
                      ))}
                    </Select>
                    <Button variant="ghost" size="icon" aria-label={`حذف ${b.barcode}`} onClick={() => set("barcodes", f.barcodes.filter((_, j) => j !== i))}>
                      <Trash2 />
                    </Button>
                  </div>
                ))}
              </div>
            </fieldset>

            <fieldset className="surface rounded-2xl p-4" disabled={!canPrice}>
              <legend className="px-1 text-sm font-semibold text-ink">
                قیمت فروش ({currency === "IRT" ? "تومان" : "ریال"}){!canPrice ? " — نیازمند مجوز مدیریت قیمت" : ""}
              </legend>
              <div className="grid gap-3 sm:grid-cols-3">
                {allUnits.map((uid) => (
                  <Field key={uid} label={`هر ${unitName(uid)}`}>
                    <MoneyInput value={f.prices[uid] ?? ""} onChange={(v) => set("prices", { ...f.prices, [uid]: v })} />
                  </Field>
                ))}
              </div>
            </fieldset>
          </div>
        )}
        <DialogFooter>
          <Button onClick={() => save.mutate()} loading={save.isPending} disabled={!f.code || f.name.length < 2 || !f.base_unit_id}>
            ذخیره کالا
          </Button>
          <Button variant="ghost" onClick={onClose}>انصراف</Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}

export function ItemsPage() {
  const can = useCan();
  const currency = useCurrency();
  const groups = useGroups();
  const [q, setQ] = React.useState("");
  const [search, setSearch] = React.useState("");
  const [group, setGroup] = React.useState("");
  const [belowMin, setBelowMin] = React.useState(false);
  const [page, setPage] = React.useState(1);
  const [editing, setEditing] = React.useState<string | null>(null);
  const [creating, setCreating] = React.useState(false);

  React.useEffect(() => {
    const t = setTimeout(() => {
      setSearch(q.trim());
      setPage(1);
    }, 250);
    return () => clearTimeout(t);
  }, [q]);

  const params = new URLSearchParams({ page: String(page), page_size: "30" });
  if (search) params.set("q", search);
  if (group) params.set("group_id", group);
  if (belowMin) params.set("below_min", "true");
  const items = useQuery({
    queryKey: ["inventory", "items", params.toString()],
    queryFn: () => api.get<Page<ItemSummary>>(`/inventory/items?${params}`),
    placeholderData: keepPreviousData,
  });

  return (
    <Card>
      <div className="flex flex-wrap items-center gap-3 p-4">
        <div className="relative w-full max-w-sm">
          <Search className="pointer-events-none absolute top-1/2 right-3 size-4 -translate-y-1/2 text-ink-faint" />
          <Input className="ps-9" placeholder="نام، کد یا اسکن بارکد" value={q} onChange={(e) => setQ(e.target.value)} />
        </div>
        <Select className="w-44" value={group} onChange={(e) => { setGroup(e.target.value); setPage(1); }} aria-label="گروه">
          <option value="">همه گروه‌ها</option>
          {groups.data?.map((g) => (
            <option key={g.id} value={g.id}>{g.name}</option>
          ))}
        </Select>
        <label className="flex cursor-pointer items-center gap-2 text-sm text-ink-soft">
          <Checkbox checked={belowMin} onCheckedChange={(c) => { setBelowMin(c === true); setPage(1); }} />
          زیر حداقل موجودی
        </label>
        <div className="flex-1" />
        {can("inventory.item.manage") ? (
          <Button onClick={() => setCreating(true)}>
            <PackagePlus /> کالای جدید
          </Button>
        ) : null}
      </div>
      <div className="surface mx-4 mb-4 overflow-hidden rounded-2xl">
        {items.isLoading ? (
          <Spinner />
        ) : items.isError ? (
          <ErrorBox error={items.error} />
        ) : !items.data?.items.length ? (
          <EmptyState icon={PackagePlus} title="کالایی یافت نشد" description="کالاها را تک‌به‌تک تعریف کنید یا از «ورود از Excel» استفاده کنید." />
        ) : (
          <>
            <Table>
              <thead>
                <tr>
                  <Th className="w-28">کد</Th>
                  <Th>نام کالا</Th>
                  <Th className="w-36">گروه</Th>
                  <Th className="w-36">بارکد</Th>
                  <Th className="w-36">قیمت</Th>
                  <Th className="w-32">موجودی</Th>
                  <Th className="w-12" />
                </tr>
              </thead>
              <tbody>
                {items.data.items.map((it) => (
                  <Tr
                    key={it.id}
                    className={cn(can("inventory.item.manage") && "cursor-pointer", !it.is_active && "opacity-50")}
                    onClick={() => can("inventory.item.manage") && setEditing(it.id)}
                  >
                    <Td className="tabular" dir="ltr">{it.code}</Td>
                    <Td>
                      <span className="font-medium text-ink">{it.name}</span>
                      {it.is_weighted ? <Badge tone="info" icon={false} className="ms-2">وزنی</Badge> : null}
                      {!it.is_active ? <Badge tone="neutral" className="ms-2">غیرفعال</Badge> : null}
                    </Td>
                    <Td className="text-ink-soft">{it.group_name ?? "—"}</Td>
                    <Td className="tabular text-ink-soft" dir="ltr">{it.barcode ?? "—"}</Td>
                    <Td className="tabular">{it.price ? formatMoney(it.price, currency) : <span className="text-ink-faint">بدون قیمت</span>}</Td>
                    <Td className="tabular">
                      {toFaDigits(trimQty(it.stock_qty))} <span className="text-xs text-ink-faint">{it.base_unit_name}</span>
                    </Td>
                    <Td>
                      {can("inventory.item.manage") ? (
                        <Button variant="ghost" size="icon" aria-label={`ویرایش ${it.name}`} onClick={(e) => { e.stopPropagation(); setEditing(it.id); }}>
                          <Pencil />
                        </Button>
                      ) : null}
                    </Td>
                  </Tr>
                ))}
              </tbody>
            </Table>
            <Pagination page={page} pageSize={30} total={items.data.total} onPage={setPage} />
          </>
        )}
      </div>
      <ItemDialog itemId={editing} open={!!editing} onClose={() => setEditing(null)} />
      <ItemDialog itemId={null} open={creating} onClose={() => setCreating(false)} />
    </Card>
  );
}
