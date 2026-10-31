import { keepPreviousData, useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { ArrowRight, CheckCheck, ClipboardList, FilePlus2, Save, Trash2 } from "lucide-react";
import * as React from "react";
import { Link, useNavigate, useParams, useSearchParams } from "react-router";
import { toast } from "sonner";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { Badge, EmptyState, ErrorBox, Spinner } from "@/components/ui/feedback";
import { Field, Input, Select } from "@/components/ui/form-controls";
import { Pagination, Table, Td, Th, Tr } from "@/components/ui/table";
import { useCurrency } from "@/features/accounting/api";
import { JalaliDateInput, MoneyInput } from "@/features/accounting/inputs";
import { useCan } from "@/features/auth/auth";
import { ApiError, api, newIdempotencyKey, type Page } from "@/lib/api";
import { formatMoney, toEnDigits, toFaDigits } from "@/lib/format";
import { isoToJalaliFa, todayIso } from "@/lib/jalali";
import { inputToRials, rialsToInput, sumRials } from "@/lib/money";
import { DOC_LABEL, type DocType, type Item, type StockDoc, type StockDocSummary, trimQty, useUnits, useWarehouses } from "./api";
import { ItemSearch, type Picked } from "./ItemSearch";

const onError = (e: unknown) => toast.error(e instanceof ApiError ? e.message : "خطا");

export function StockDocsPage() {
  const navigate = useNavigate();
  const can = useCan();
  const warehouses = useWarehouses();
  const [type, setType] = React.useState("");
  const [status, setStatus] = React.useState("");
  const [page, setPage] = React.useState(1);
  const params = new URLSearchParams({ page: String(page), page_size: "25" });
  if (type) params.set("doc_type", type);
  if (status) params.set("status", status);
  const docs = useQuery({
    queryKey: ["inventory", "docs", params.toString()],
    queryFn: () => api.get<Page<StockDocSummary>>(`/inventory/stock-documents?${params}`),
    placeholderData: keepPreviousData,
  });
  const whName = (id: string | null) => warehouses.data?.find((w) => w.id === id)?.name ?? "";

  return (
    <Card>
      <div className="flex flex-wrap items-center gap-3 p-4">
        <Select className="w-48" value={type} onChange={(e) => { setType(e.target.value); setPage(1); }} aria-label="نوع سند">
          <option value="">همه انواع</option>
          {Object.entries(DOC_LABEL).map(([k, v]) => (
            <option key={k} value={k}>{v}</option>
          ))}
        </Select>
        <Select className="w-36" value={status} onChange={(e) => { setStatus(e.target.value); setPage(1); }} aria-label="وضعیت">
          <option value="">همه وضعیت‌ها</option>
          <option value="draft">پیش‌نویس</option>
          <option value="final">قطعی</option>
        </Select>
        <div className="flex-1" />
        {can("inventory.stock.create")
          ? (["opening", "transfer", "count", "adjustment"] as DocType[])
              .filter((t) => t !== "adjustment" || can("inventory.stock.adjust"))
              .map((t) => (
                <Button key={t} variant={t === "opening" ? "primary" : "secondary"} size="sm" asChild>
                  <Link to={`/inventory/documents/new?type=${t}`}>
                    <FilePlus2 /> {DOC_LABEL[t]}
                  </Link>
                </Button>
              ))
          : null}
      </div>
      <div className="surface mx-4 mb-4 overflow-hidden rounded-2xl">
        {docs.isLoading ? (
          <Spinner />
        ) : docs.isError ? (
          <ErrorBox error={docs.error} />
        ) : !docs.data?.items.length ? (
          <EmptyState icon={ClipboardList} title="سند انباری ثبت نشده است" description="برای شروع، موجودی اول دوره را ثبت یا از Excel وارد کنید." />
        ) : (
          <>
            <Table>
              <thead>
                <tr>
                  <Th className="w-20">شماره</Th>
                  <Th className="w-28">تاریخ</Th>
                  <Th className="w-40">نوع</Th>
                  <Th>انبار</Th>
                  <Th>شرح</Th>
                  <Th className="w-20">ردیف</Th>
                  <Th className="w-28">وضعیت</Th>
                </tr>
              </thead>
              <tbody>
                {docs.data.items.map((d) => (
                  <Tr key={d.id} className="cursor-pointer" onClick={() => navigate(`/inventory/documents/${d.id}`)}>
                    <Td className="tabular font-semibold">{d.number ? toFaDigits(d.number) : "—"}</Td>
                    <Td className="tabular text-ink-soft">{isoToJalaliFa(d.document_date)}</Td>
                    <Td>{DOC_LABEL[d.doc_type]}</Td>
                    <Td className="text-ink-soft">
                      {whName(d.warehouse_id)}
                      {d.dest_warehouse_id ? ` ← ${whName(d.dest_warehouse_id)}` : ""}
                    </Td>
                    <Td className="max-w-xs truncate text-ink-soft">{d.description ?? ""}</Td>
                    <Td className="tabular">{toFaDigits(d.line_count)}</Td>
                    <Td>{d.status === "final" ? <Badge tone="success">قطعی</Badge> : <Badge tone="warning">پیش‌نویس</Badge>}</Td>
                  </Tr>
                ))}
              </tbody>
            </Table>
            <Pagination page={page} pageSize={25} total={docs.data.total} onPage={setPage} />
          </>
        )}
      </div>
    </Card>
  );
}

type Row = {
  key: string;
  item_id: string;
  code: string;
  name: string;
  unit_id: string;
  units: { id: string; name: string }[];
  qty: string;
  cost: string; // display currency per line unit
  expiry: string | null;
};

export function StockDocEditorPage() {
  const { id } = useParams();
  const isNew = !id || id === "new";
  const doc = useQuery({
    queryKey: ["inventory", "doc", id],
    queryFn: () => api.get<StockDoc>(`/inventory/stock-documents/${id}`),
    enabled: !isNew,
  });
  if (!isNew && doc.isLoading) return <Spinner />;
  if (!isNew && doc.isError) return <ErrorBox error={doc.error} />;
  return <DocForm key={doc.data?.row_version ?? "new"} doc={doc.data} />;
}

function DocForm({ doc }: { doc?: StockDoc }) {
  const qc = useQueryClient();
  const navigate = useNavigate();
  const can = useCan();
  const currency = useCurrency();
  const units = useUnits();
  const warehouses = useWarehouses();
  const [params] = useSearchParams();
  const type: DocType = doc?.doc_type ?? ((params.get("type") as DocType) || "opening");
  const readOnly = doc?.status === "final";
  const [warehouse, setWarehouse] = React.useState(doc?.warehouse_id ?? "");
  const [dest, setDest] = React.useState(doc?.dest_warehouse_id ?? "");
  const [date, setDate] = React.useState<string | null>(doc?.document_date ?? todayIso());
  const [description, setDescription] = React.useState(doc?.description ?? "");
  const [rows, setRows] = React.useState<Row[]>(() =>
    (doc?.lines ?? []).map((l) => ({
      key: l.id,
      item_id: l.item_id,
      code: l.item_code,
      name: l.item_name,
      unit_id: l.unit_id,
      units: [{ id: l.unit_id, name: l.unit_name }],
      qty: trimQty(l.qty),
      cost: l.unit_cost ? rialsToInput(l.unit_cost, currency) : "",
      expiry: l.expiry_date,
    })),
  );
  const keyRef = React.useRef(newIdempotencyKey());
  const searchRef = React.useRef<HTMLInputElement>(null);
  const unitName = (uid: string) => units.data?.find((u) => u.id === uid)?.name ?? "";
  const showCost = type === "opening" || type === "adjustment";

  React.useEffect(() => {
    if (!warehouse && warehouses.data?.length) setWarehouse(warehouses.data[0].id);
  }, [warehouses.data, warehouse]);

  const addItem = async (p: Picked) => {
    // Scanning the same item again adds to its quantity, like at a till.
    const existing = rows.find((r) => r.item_id === p.item_id && (!p.unit_id || r.unit_id === p.unit_id));
    if (existing) {
      // Decimal string math: 0.1 + 0.2 must stay 0.3 (weights).
      const add = toEnDigits(p.qty ?? "1");
      setRows((rs) => rs.map((r) => (r.key === existing.key ? { ...r, qty: trimQty(sumRials([toEnDigits(r.qty || "0"), add])) } : r)));
      return;
    }
    const item = await qc.fetchQuery({
      queryKey: ["inventory", "item", p.item_id],
      queryFn: () => api.get<Item>(`/inventory/items/${p.item_id}`),
      staleTime: 60_000,
    });
    const options = [item.base_unit_id, ...item.units.map((u) => u.unit_id)].map((uid) => ({ id: uid, name: unitName(uid) }));
    setRows((rs) => [
      ...rs,
      {
        key: crypto.randomUUID(),
        item_id: item.id,
        code: item.code,
        name: item.name,
        unit_id: p.unit_id ?? item.base_unit_id,
        units: options,
        qty: type === "count" ? "" : (p.qty ?? "1"),
        cost: "",
        expiry: null,
      },
    ]);
  };

  const payload = () => {
    if (!date) throw new ApiError(0, "date", "تاریخ سند نامعتبر است");
    if (!rows.length) throw new ApiError(0, "lines", "حداقل یک کالا اضافه کنید");
    return {
      doc_type: type,
      warehouse_id: warehouse,
      dest_warehouse_id: type === "transfer" ? dest || null : null,
      document_date: date,
      description: description || null,
      lines: rows.map((r, i) => {
        const cost = r.cost ? inputToRials(r.cost, currency) : null;
        if (r.cost && cost === null) throw new ApiError(0, "cost", `ردیف ${toFaDigits(i + 1)}: بها نامعتبر است`);
        const qty = toEnDigits(r.qty).trim();
        if (!qty) throw new ApiError(0, "qty", `ردیف ${toFaDigits(i + 1)}: مقدار را وارد کنید`);
        return { item_id: r.item_id, unit_id: r.unit_id, qty, unit_cost: cost, expiry_date: r.expiry };
      }),
    };
  };

  const save = async () => {
    const body = payload();
    return doc
      ? api.put<StockDoc>(`/inventory/stock-documents/${doc.id}`, body, doc.row_version)
      : api.post<StockDoc>("/inventory/stock-documents", body, { idempotencyKey: keyRef.current });
  };

  const saveDraft = useMutation({
    mutationFn: save,
    onSuccess: (d) => {
      qc.invalidateQueries({ queryKey: ["inventory"] });
      toast.success("پیش‌نویس ذخیره شد");
      if (!doc) navigate(`/inventory/documents/${d.id}`, { replace: true });
    },
    onError,
  });
  const finalize = useMutation({
    mutationFn: async () => {
      const saved = await save();
      try {
        return await api.post<StockDoc>(`/inventory/stock-documents/${saved.id}/finalize`, undefined, { version: saved.row_version });
      } catch (e) {
        if (!doc) navigate(`/inventory/documents/${saved.id}`, { replace: true });
        qc.invalidateQueries({ queryKey: ["inventory", "doc", saved.id] });
        throw e;
      }
    },
    onSuccess: (d) => {
      qc.invalidateQueries({ queryKey: ["inventory"] });
      qc.invalidateQueries({ queryKey: ["accounting"] });
      toast.success(`سند انبار شماره ${toFaDigits(d.number ?? 0)} قطعی شد`);
      navigate(`/inventory/documents/${d.id}`, { replace: true });
    },
    onError,
  });
  const remove = useMutation({
    mutationFn: () => api.del(`/inventory/stock-documents/${doc?.id}`, doc?.row_version ?? ""),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["inventory"] });
      navigate("/inventory/documents");
    },
    onError,
  });

  const busy = saveDraft.isPending || finalize.isPending;
  const wh = (wid: string | null) => warehouses.data?.find((w) => w.id === wid)?.name ?? "";

  return (
    <div className="flex flex-col gap-4">
      <div className="flex flex-wrap items-center gap-3">
        <Button variant="ghost" size="icon" asChild aria-label="بازگشت">
          <Link to="/inventory/documents">
            <ArrowRight />
          </Link>
        </Button>
        <h1 className="text-xl font-extrabold text-ink">
          {DOC_LABEL[type]} {doc?.number ? `شماره ${toFaDigits(doc.number)}` : ""}
        </h1>
        {readOnly ? <Badge tone="success">قطعی</Badge> : <Badge tone="warning">پیش‌نویس</Badge>}
        {doc?.voucher_id ? (
          <Link className="text-sm text-brand-600 underline dark:text-brand-300" to={`/accounting/vouchers/${doc.voucher_id}`}>
            سند حسابداری {toFaDigits(doc.voucher_number ?? 0)}
          </Link>
        ) : null}
        {doc?.source_document_id ? (
          <Link className="text-sm text-brand-600 underline dark:text-brand-300" to={`/inventory/documents/${doc.source_document_id}`}>
            برگه شمارش مبدأ
          </Link>
        ) : null}
      </div>

      <Card className="grid gap-4 p-5 md:grid-cols-[10rem_14rem_14rem_1fr]">
        <Field label="تاریخ">
          {readOnly ? <p className="tabular py-2">{isoToJalaliFa(doc!.document_date)}</p> : <JalaliDateInput value={date} onChange={setDate} />}
        </Field>
        <Field label={type === "transfer" ? "انبار مبدأ" : "انبار"}>
          {readOnly ? (
            <p className="py-2">{wh(doc!.warehouse_id)}</p>
          ) : (
            <Select value={warehouse} onChange={(e) => setWarehouse(e.target.value)}>
              {warehouses.data?.map((w) => (
                <option key={w.id} value={w.id}>{w.name}</option>
              ))}
            </Select>
          )}
        </Field>
        {type === "transfer" ? (
          <Field label="انبار مقصد">
            {readOnly ? (
              <p className="py-2">{wh(doc!.dest_warehouse_id)}</p>
            ) : (
              <Select value={dest} onChange={(e) => setDest(e.target.value)}>
                <option value="">انتخاب کنید</option>
                {warehouses.data?.filter((w) => w.id !== warehouse).map((w) => (
                  <option key={w.id} value={w.id}>{w.name}</option>
                ))}
              </Select>
            )}
          </Field>
        ) : (
          <div />
        )}
        <Field label="شرح">
          {readOnly ? <p className="py-2">{doc!.description ?? "—"}</p> : <Input value={description} onChange={(e) => setDescription(e.target.value)} />}
        </Field>
      </Card>

      {!readOnly ? (
        <Card className="p-4">
          <ItemSearch ref={searchRef} autoFocus onPick={(p) => void addItem(p).then(() => searchRef.current?.focus())} />
          <p className="mt-2 text-xs text-ink-faint">
            {type === "count"
              ? "مقدار شمارش‌شده را وارد کنید؛ پس از قطعی شدن، مغایرت با موجودی سیستم خودکار تعدیل می‌شود."
              : type === "adjustment"
                ? "مقدار مثبت = اضافه انبار، منفی = کسری. بها برای اضافه کالایی که هنوز بهای تمام‌شده ندارد لازم است."
                : "اسکن دوباره یک کالا، مقدار همان ردیف را افزایش می‌دهد."}
          </p>
        </Card>
      ) : null}

      <Card className="p-2">
        <div className="surface overflow-x-auto rounded-2xl">
          <table className="w-full min-w-[52rem] text-sm">
            <thead>
              <tr className="text-xs text-ink-faint">
                <th className="w-10 px-2 py-3">#</th>
                <th className="px-2 py-3 text-start">کالا</th>
                <th className="w-32 px-2 py-3 text-start">واحد</th>
                <th className="w-32 px-2 py-3 text-start">{type === "count" ? "شمارش‌شده" : "مقدار"}</th>
                {readOnly && type === "count" ? <th className="w-28 px-2 py-3 text-start">موجودی سیستم</th> : null}
                {showCost ? <th className="w-40 px-2 py-3 text-start">بهای واحد ({currency === "IRT" ? "تومان" : "ریال"})</th> : null}
                {readOnly ? <th className="w-40 px-2 py-3 text-start">ارزش</th> : null}
                {!readOnly ? <th className="w-10" /> : null}
              </tr>
            </thead>
            <tbody>
              {readOnly
                ? doc!.lines.map((l) => (
                    <tr key={l.id} className="border-t border-[var(--line)]">
                      <td className="tabular px-2 py-2.5 text-center text-ink-faint">{toFaDigits(l.line_no)}</td>
                      <td className="px-2 py-2.5"><span className="tabular text-ink-faint" dir="ltr">{l.item_code}</span> {l.item_name}</td>
                      <td className="px-2 py-2.5">{l.unit_name}</td>
                      <td className="tabular px-2 py-2.5">{toFaDigits(trimQty(l.qty))}</td>
                      {type === "count" ? <td className="tabular px-2 py-2.5">{toFaDigits(trimQty(l.system_qty))}</td> : null}
                      {showCost ? <td className="tabular px-2 py-2.5">{l.unit_cost ? formatMoney(l.unit_cost, currency) : "—"}</td> : null}
                      <td className="tabular px-2 py-2.5">{l.total_cost ? formatMoney(l.total_cost.replace("-", ""), currency) : "—"}</td>
                    </tr>
                  ))
                : rows.map((r, i) => (
                    <tr key={r.key} className="border-t border-[var(--line)]">
                      <td className="tabular px-2 py-2 text-center text-ink-faint">{toFaDigits(i + 1)}</td>
                      <td className="px-2 py-2"><span className="tabular text-ink-faint" dir="ltr">{r.code}</span> {r.name}</td>
                      <td className="px-2 py-2">
                        <Select className="h-9" value={r.unit_id} onChange={(e) => setRows((rs) => rs.map((x) => (x.key === r.key ? { ...x, unit_id: e.target.value } : x)))}>
                          {r.units.map((u) => (
                            <option key={u.id} value={u.id}>{u.name || unitName(u.id)}</option>
                          ))}
                        </Select>
                      </td>
                      <td className="px-2 py-2">
                        <Input
                          className="h-9 text-end"
                          dir="ltr"
                          inputMode="decimal"
                          aria-label={`مقدار ردیف ${i + 1}`}
                          value={r.qty}
                          onChange={(e) => setRows((rs) => rs.map((x) => (x.key === r.key ? { ...x, qty: e.target.value } : x)))}
                        />
                      </td>
                      {showCost ? (
                        <td className="px-2 py-2">
                          <MoneyInput compact className="h-9" aria-label={`بهای ردیف ${i + 1}`} value={r.cost} onChange={(v) => setRows((rs) => rs.map((x) => (x.key === r.key ? { ...x, cost: v } : x)))} />
                        </td>
                      ) : null}
                      <td className="px-1 py-2">
                        <Button variant="ghost" size="icon" aria-label={`حذف ردیف ${i + 1}`} onClick={() => setRows((rs) => rs.filter((x) => x.key !== r.key))}>
                          <Trash2 />
                        </Button>
                      </td>
                    </tr>
                  ))}
              {!readOnly && rows.length === 0 ? (
                <tr>
                  <td colSpan={6} className="py-10 text-center text-sm text-ink-faint">کالایی اضافه نشده است — بارکد را اسکن کنید</td>
                </tr>
              ) : null}
            </tbody>
            {readOnly && doc?.total_value ? (
              <tfoot>
                <tr className="border-t-2 border-[var(--line)] bg-[var(--surface-muted)] font-bold">
                  <td colSpan={showCost ? 5 : 4} className="px-2 py-3 text-end">جمع ارزش</td>
                  <td className="tabular px-2 py-3">{formatMoney(doc.total_value.replace("-", ""), currency)}</td>
                </tr>
              </tfoot>
            ) : null}
          </table>
        </div>
      </Card>

      {!readOnly ? (
        <div className="flex flex-wrap items-center gap-2">
          <Button onClick={() => finalize.mutate()} loading={finalize.isPending} disabled={busy || !rows.length}>
            <CheckCheck /> ذخیره و قطعی کردن
          </Button>
          <Button variant="outline" onClick={() => saveDraft.mutate()} loading={saveDraft.isPending} disabled={busy || !rows.length}>
            <Save /> ذخیره پیش‌نویس
          </Button>
          <div className="flex-1" />
          {doc && can("inventory.stock.create") ? (
            <Button variant="ghost" className="text-danger" onClick={() => remove.mutate()} loading={remove.isPending}>
              <Trash2 /> حذف پیش‌نویس
            </Button>
          ) : null}
        </div>
      ) : null}
    </div>
  );
}
