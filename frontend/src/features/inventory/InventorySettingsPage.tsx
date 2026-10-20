import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { FlaskConical, Pencil, Plus, Scale, Warehouse as WarehouseIcon } from "lucide-react";
import * as React from "react";
import { toast } from "sonner";
import { Button } from "@/components/ui/button";
import { Card, CardBody, CardHeader } from "@/components/ui/card";
import { Dialog, DialogContent, DialogFooter } from "@/components/ui/dialog";
import { Badge, EmptyState, Spinner } from "@/components/ui/feedback";
import { Checkbox, Field, Input, Select } from "@/components/ui/form-controls";
import { Table, Td, Th, Tr } from "@/components/ui/table";
import { useCurrency } from "@/features/accounting/api";
import { useCan } from "@/features/auth/auth";
import type { Branch } from "@/features/settings/types";
import { ApiError, api, newIdempotencyKey } from "@/lib/api";
import { formatMoney, toEnDigits, toFaDigits } from "@/lib/format";
import { cn } from "@/lib/utils";
import { type Lookup, type ScaleRule, trimQty, useGroups, useWarehouses } from "./api";

const onError = (e: unknown) => toast.error(e instanceof ApiError ? e.message : "خطا");

function Groups() {
  const qc = useQueryClient();
  const can = useCan();
  const groups = useGroups();
  const [code, setCode] = React.useState("");
  const [name, setName] = React.useState("");
  const keyRef = React.useRef(newIdempotencyKey());
  const add = useMutation({
    mutationFn: () => api.post("/inventory/groups", { code: toEnDigits(code.trim()), name: name.trim() }, { idempotencyKey: keyRef.current }),
    onSuccess: () => {
      keyRef.current = newIdempotencyKey();
      setCode("");
      setName("");
      qc.invalidateQueries({ queryKey: ["inventory", "groups"] });
      toast.success("گروه اضافه شد");
    },
    onError,
  });
  return (
    <Card>
      <CardHeader title="گروه‌های کالا" description="برای جست‌وجو، گزارش و ورود از Excel" />
      <CardBody className="flex flex-col gap-3">
        {can("inventory.item.manage") ? (
          <form
            className="flex gap-2"
            onSubmit={(e) => {
              e.preventDefault();
              add.mutate();
            }}
          >
            <Input className="w-28" dir="ltr" placeholder="کد" aria-label="کد گروه" value={code} onChange={(e) => setCode(e.target.value)} />
            <Input className="flex-1" placeholder="نام گروه" aria-label="نام گروه" value={name} onChange={(e) => setName(e.target.value)} />
            <Button type="submit" loading={add.isPending} disabled={!code.trim() || name.trim().length < 2}>
              <Plus /> افزودن
            </Button>
          </form>
        ) : null}
        <div className="flex flex-wrap gap-2">
          {groups.data?.length ? (
            groups.data.map((g) => (
              <span key={g.id} className="surface rounded-xl px-3 py-1.5 text-sm">
                <span className="tabular text-ink-faint" dir="ltr">{g.code}</span> {g.name}
              </span>
            ))
          ) : (
            <p className="text-sm text-ink-faint">هنوز گروهی تعریف نشده است.</p>
          )}
        </div>
      </CardBody>
    </Card>
  );
}

function Warehouses() {
  const qc = useQueryClient();
  const can = useCan();
  const warehouses = useWarehouses();
  const branches = useQuery({ queryKey: ["branches"], queryFn: () => api.get<Branch[]>("/organization/branches") });
  const [branchId, setBranchId] = React.useState("");
  const [code, setCode] = React.useState("");
  const [name, setName] = React.useState("");
  const keyRef = React.useRef(newIdempotencyKey());
  const branchName = (id: string) => branches.data?.find((b) => b.id === id)?.name ?? "";
  React.useEffect(() => {
    if (!branchId && branches.data?.length) setBranchId(branches.data[0].id);
  }, [branches.data, branchId]);

  const add = useMutation({
    mutationFn: () =>
      api.post("/inventory/warehouses", { branch_id: branchId, code: toEnDigits(code.trim()), name: name.trim() }, { idempotencyKey: keyRef.current }),
    onSuccess: () => {
      keyRef.current = newIdempotencyKey();
      setCode("");
      setName("");
      qc.invalidateQueries({ queryKey: ["inventory", "warehouses"] });
      toast.success("انبار اضافه شد");
    },
    onError,
  });
  return (
    <Card>
      <CardHeader icon={<WarehouseIcon className="size-5" />} title="انبارها" description="هر شعبه یک انبار اصلی دارد؛ انبار دیگر را این‌جا اضافه کنید" />
      <CardBody className="flex flex-col gap-3">
        {can("branches.manage") ? (
          <form
            className="flex flex-wrap gap-2"
            onSubmit={(e) => {
              e.preventDefault();
              add.mutate();
            }}
          >
            <Select className="w-40" aria-label="شعبه" value={branchId} onChange={(e) => setBranchId(e.target.value)}>
              {branches.data?.map((b) => (
                <option key={b.id} value={b.id}>{b.name}</option>
              ))}
            </Select>
            <Input className="w-24" dir="ltr" placeholder="کد" aria-label="کد انبار" value={code} onChange={(e) => setCode(e.target.value)} />
            <Input className="min-w-40 flex-1" placeholder="نام انبار" aria-label="نام انبار" value={name} onChange={(e) => setName(e.target.value)} />
            <Button type="submit" loading={add.isPending} disabled={!branchId || !code.trim() || name.trim().length < 2}>
              <Plus /> افزودن
            </Button>
          </form>
        ) : null}
        <ul className="flex flex-col gap-1.5">
          {warehouses.data?.map((w) => (
            <li key={w.id} className="surface flex items-center gap-3 rounded-xl px-3 py-2 text-sm">
              <span className="tabular w-16 text-ink-faint" dir="ltr">{w.code}</span>
              <span className="flex-1 text-ink">{w.name}</span>
              <span className="text-xs text-ink-faint">{branchName(w.branch_id)}</span>
            </li>
          ))}
        </ul>
      </CardBody>
    </Card>
  );
}

type RuleForm = Omit<ScaleRule, "id" | "row_version">;

/** Common layouts, offered as starting points only — the real layout must be read off a printed label. */
const PRESETS: { label: string; rule: RuleForm }[] = [
  {
    label: "پیشوند ۲ رقمی + کد ۵ رقمی + وزن ۵ رقمی به گرم",
    rule: { name: "ترازو — وزن", prefix: "21", item_code_length: 5, value_length: 5, value_type: "weight", value_decimals: 3, is_active: true },
  },
  {
    label: "پیشوند ۲ رقمی + کد ۵ رقمی + مبلغ ۵ رقمی به تومان",
    rule: { name: "ترازو — مبلغ", prefix: "22", item_code_length: 5, value_length: 5, value_type: "price", value_decimals: 1, is_active: true },
  },
  {
    label: "پیشوند ۱ رقمی + کد ۶ رقمی + وزن ۵ رقمی به گرم",
    rule: { name: "ترازو — وزن", prefix: "2", item_code_length: 6, value_length: 5, value_type: "weight", value_decimals: 3, is_active: true },
  },
];

const EMPTY_RULE: RuleForm = PRESETS[0].rule;

function decimalsHint(f: RuleForm) {
  if (f.value_type === "weight") {
    const kg = (1250 / 10 ** f.value_decimals).toString();
    return `مثال: ${toFaDigits("01250")} ← ${toFaDigits(kg)} کیلوگرم (۳ یعنی گرم)`;
  }
  return `مبلغ چاپ‌شده × ${toFaDigits(10 ** f.value_decimals)} = ریال (۱ یعنی تومان)`;
}

function RuleDialog({ rule, onClose }: { rule: ScaleRule | null; onClose: () => void }) {
  const qc = useQueryClient();
  const [f, setF] = React.useState<RuleForm>(() => (rule ? { ...rule } : { ...EMPTY_RULE }));
  const keyRef = React.useRef(newIdempotencyKey());
  const set = <K extends keyof RuleForm>(k: K, v: RuleForm[K]) => setF((s) => ({ ...s, [k]: v }));
  const total = f.prefix.length + f.item_code_length + f.value_length;
  const save = useMutation({
    mutationFn: () => {
      const body = { ...f, prefix: toEnDigits(f.prefix) };
      return rule
        ? api.put<ScaleRule>(`/inventory/scale-rules/${rule.id}`, body, rule.row_version)
        : api.post<ScaleRule>("/inventory/scale-rules", body, { idempotencyKey: keyRef.current });
    },
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["inventory", "scale-rules"] });
      toast.success("قاعده ذخیره شد");
      onClose();
    },
    onError,
  });
  const num = (v: string) => Number.parseInt(toEnDigits(v), 10) || 0;

  return (
    <Dialog open onOpenChange={(o) => !o && onClose()}>
      <DialogContent title={rule ? "ویرایش قاعده بارکد ترازو" : "قاعده بارکد ترازو"} description="ساختار ۱۳ رقمی برچسب ترازو: پیشوند + کد کالا در ترازو + مقدار + رقم کنترل" className="max-w-xl">
        <form
          className="flex flex-col gap-4"
          onSubmit={(e) => {
            e.preventDefault();
            save.mutate();
          }}
        >
          {!rule ? (
            <Field label="الگوی آماده (قابل ویرایش)">
              <Select onChange={(e) => e.target.value && setF({ ...PRESETS[Number(e.target.value)].rule })} defaultValue="0">
                {PRESETS.map((p, i) => (
                  <option key={p.label} value={i}>{p.label}</option>
                ))}
              </Select>
            </Field>
          ) : null}
          <div className="grid grid-cols-2 gap-3">
            <Field label="نام">
              <Input value={f.name} onChange={(e) => set("name", e.target.value)} />
            </Field>
            <Field label="پیشوند" hint="معمولاً با ۲ شروع می‌شود">
              <Input dir="ltr" inputMode="numeric" value={f.prefix} onChange={(e) => set("prefix", toEnDigits(e.target.value).replace(/\D/g, "").slice(0, 4))} />
            </Field>
            <Field label="طول کد کالا">
              <Input dir="ltr" inputMode="numeric" value={String(f.item_code_length)} onChange={(e) => set("item_code_length", num(e.target.value))} />
            </Field>
            <Field label="طول مقدار">
              <Input dir="ltr" inputMode="numeric" value={String(f.value_length)} onChange={(e) => set("value_length", num(e.target.value))} />
            </Field>
            <Field label="نوع مقدار">
              <Select value={f.value_type} onChange={(e) => set("value_type", e.target.value as RuleForm["value_type"])}>
                <option value="weight">وزن</option>
                <option value="price">مبلغ</option>
              </Select>
            </Field>
            <Field label={f.value_type === "weight" ? "تعداد رقم اعشار وزن" : "ضریب مبلغ (توان ۱۰)"} hint={decimalsHint(f)}>
              <Select value={String(f.value_decimals)} onChange={(e) => set("value_decimals", Number(e.target.value))}>
                {[0, 1, 2, 3, 4].map((d) => (
                  <option key={d} value={d}>{toFaDigits(d)}</option>
                ))}
              </Select>
            </Field>
          </div>
          <LayoutStrip f={f} />
          {total !== 12 ? (
            <p role="alert" className="text-sm text-danger">
              جمع طول‌ها {toFaDigits(total)} است؛ باید ۱۲ باشد (رقم سیزدهم کنترلی است).
            </p>
          ) : null}
          <label className="flex cursor-pointer items-center gap-2 text-sm text-ink-soft">
            <Checkbox checked={f.is_active} onCheckedChange={(c) => set("is_active", c === true)} />
            فعال
          </label>
          <DialogFooter>
            <Button type="submit" loading={save.isPending} disabled={total !== 12 || !f.prefix || f.name.trim().length < 2}>
              ذخیره
            </Button>
            <Button type="button" variant="ghost" onClick={onClose}>
              انصراف
            </Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  );
}

const SEG = {
  prefix: "bg-brand-500/15 text-brand-700 dark:text-brand-200",
  item: "bg-success/15 text-success",
  value: "bg-warning/20 text-warning",
  check: "bg-black/5 text-ink-faint dark:bg-white/10",
};

/** The 13 digits of a label coloured by segment; with `code`, shows those digits instead of placeholders. */
function LayoutStrip({ f, code }: { f: Pick<ScaleRule, "prefix" | "item_code_length" | "value_length">; code?: string }) {
  const parts: [keyof typeof SEG, number, string][] = [
    ["prefix", f.prefix.length, "پیشوند"],
    ["item", f.item_code_length, "کد کالا"],
    ["value", f.value_length, "مقدار"],
    ["check", 1, "کنترل"],
  ];
  let pos = 0;
  return (
    <div className="flex flex-wrap gap-1" dir="ltr" aria-label="ساختار بارکد">
      {parts.map(([k, len, label]) => {
        const digits = code ? code.slice(pos, pos + len) : (k === "prefix" ? f.prefix : "#".repeat(len));
        pos += len;
        return len > 0 ? (
          <div key={k} className={cn("flex flex-col items-center rounded-lg px-2 py-1", SEG[k])}>
            <span className="tabular font-mono text-base tracking-widest">{digits}</span>
            <span className="text-[10px]" dir="rtl">{label}</span>
          </div>
        ) : null;
      })}
    </div>
  );
}

const SOURCE_LABEL: Record<Lookup["source"], string> = {
  barcode: "بارکد کالا",
  pack_barcode: "بارکد بسته",
  scale_weight: "برچسب ترازو (وزن)",
  scale_price: "برچسب ترازو (مبلغ)",
  code: "کد کالا",
};

function Tester({ rules }: { rules: ScaleRule[] }) {
  const currency = useCurrency();
  const [text, setText] = React.useState("");
  const [result, setResult] = React.useState<{ code: string; lookup?: Lookup; error?: string } | null>(null);
  const test = useMutation({
    mutationFn: (code: string) => api.get<Lookup>(`/inventory/items/lookup?barcode=${encodeURIComponent(code)}`),
    onSuccess: (lookup, code) => setResult({ code, lookup }),
    onError: (e, code) => setResult({ code, error: e instanceof ApiError ? e.message : "خطا" }),
  });
  const code = result?.code ?? "";
  const rule = /^\d{13}$/.test(code) ? rules.find((r) => r.is_active && code.startsWith(r.prefix)) : undefined;

  return (
    <Card>
      <CardHeader icon={<FlaskConical className="size-5" />} title="آزمایش بارکد" description="برچسب ترازو یا هر بارکدی را اسکن کنید تا ببینید صندوق آن را چطور می‌خواند" />
      <CardBody className="flex flex-col gap-3">
        <form
          className="flex gap-2"
          onSubmit={(e) => {
            e.preventDefault();
            const c = toEnDigits(text.trim());
            if (c) test.mutate(c);
            setText("");
          }}
        >
          <Input className="tabular h-12 flex-1 text-base" dir="ltr" placeholder="2100125012504" aria-label="بارکد آزمایشی" value={text} onChange={(e) => setText(e.target.value)} />
          <Button type="submit" loading={test.isPending}>
            آزمایش
          </Button>
        </form>
        {result ? (
          <div className="surface flex flex-col gap-3 rounded-2xl p-4">
            {rule ? <LayoutStrip f={rule} code={code} /> : <span className="tabular font-mono text-ink-soft" dir="ltr">{code}</span>}
            {result.lookup ? (
              <dl className="grid grid-cols-[auto_1fr] gap-x-4 gap-y-1.5 text-sm">
                <dt className="text-ink-faint">نوع</dt>
                <dd><Badge tone="success">{SOURCE_LABEL[result.lookup.source]}</Badge></dd>
                <dt className="text-ink-faint">کالا</dt>
                <dd className="font-semibold text-ink">
                  <span className="tabular text-ink-faint" dir="ltr">{result.lookup.code}</span> {result.lookup.name}
                </dd>
                <dt className="text-ink-faint">مقدار</dt>
                <dd className="tabular">{toFaDigits(trimQty(result.lookup.qty))} {result.lookup.unit_name}</dd>
                <dt className="text-ink-faint">فی</dt>
                <dd className="tabular">{result.lookup.unit_price ? formatMoney(result.lookup.unit_price, currency) : "قیمت ندارد"}</dd>
                <dt className="text-ink-faint">مبلغ ردیف</dt>
                <dd className="tabular font-bold">{result.lookup.line_price ? formatMoney(result.lookup.line_price, currency) : "—"}</dd>
              </dl>
            ) : (
              <p role="alert" className="text-sm text-danger">{result.error}</p>
            )}
          </div>
        ) : null}
      </CardBody>
    </Card>
  );
}

function ScaleRules() {
  const can = useCan();
  const [editing, setEditing] = React.useState<ScaleRule | "new" | null>(null);
  const rules = useQuery({ queryKey: ["inventory", "scale-rules"], queryFn: () => api.get<ScaleRule[]>("/inventory/scale-rules") });
  return (
    <>
      <Card>
        <CardHeader
          icon={<Scale className="size-5" />}
          title="بارکد ترازو"
          description="ساختار برچسب ترازوی فروشگاه. کالای وزنی با «کد ترازو» در کارت کالا به این برچسب‌ها وصل می‌شود."
          actions={
            can("inventory.item.manage") ? (
              <Button size="sm" onClick={() => setEditing("new")}>
                <Plus /> قاعده جدید
              </Button>
            ) : null
          }
        />
        <CardBody>
          {rules.isLoading ? (
            <Spinner />
          ) : !rules.data?.length ? (
            <EmptyState
              icon={Scale}
              title="قاعده‌ای تعریف نشده"
              description="مدل ترازو هنوز مشخص نیست. با یک برچسب چاپ‌شده واقعی، پیشوند و طول بخش‌ها را تعیین و این‌جا ثبت کنید."
            />
          ) : (
            <div className="surface overflow-hidden rounded-2xl">
              <Table>
                <thead>
                  <tr>
                    <Th>نام</Th>
                    <Th>ساختار</Th>
                    <Th className="w-12" />
                  </tr>
                </thead>
                <tbody>
                  {rules.data.map((r) => (
                    <Tr key={r.id}>
                      <Td>
                        <div className="font-medium text-ink">{r.name}</div>
                        <div className="mt-1 flex gap-1.5">
                          <Badge tone="info" icon={false}>{r.value_type === "weight" ? "وزن" : "مبلغ"}</Badge>
                          {r.is_active ? <Badge tone="success">فعال</Badge> : <Badge tone="neutral">غیرفعال</Badge>}
                        </div>
                      </Td>
                      <Td>
                        <span className="tabular font-mono text-sm whitespace-nowrap" dir="ltr">
                          <span className="text-brand-600 dark:text-brand-300">{r.prefix}</span>
                          <span className="text-success">{"C".repeat(r.item_code_length)}</span>
                          <span className="text-warning">{(r.value_type === "weight" ? "W" : "P").repeat(r.value_length)}</span>
                          <span className="text-ink-faint">K</span>
                        </span>
                      </Td>
                      <Td>
                        {can("inventory.item.manage") ? (
                          <Button variant="ghost" size="icon" aria-label={`ویرایش ${r.name}`} onClick={() => setEditing(r)}>
                            <Pencil />
                          </Button>
                        ) : null}
                      </Td>
                    </Tr>
                  ))}
                </tbody>
              </Table>
            </div>
          )}
        </CardBody>
      </Card>
      <Tester rules={rules.data ?? []} />
      {editing ? <RuleDialog rule={editing === "new" ? null : editing} onClose={() => setEditing(null)} /> : null}
    </>
  );
}

export function InventorySettingsPage() {
  return (
    <div className="grid gap-4 xl:grid-cols-2">
      <div className="flex flex-col gap-4">
        <ScaleRules />
      </div>
      <div className="flex flex-col gap-4">
        <Warehouses />
        <Groups />
      </div>
    </div>
  );
}
