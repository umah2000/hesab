import { useMutation, useQueryClient } from "@tanstack/react-query";
import { CheckCircle2, Download, FileSpreadsheet, Upload } from "lucide-react";
import * as React from "react";
import { Link } from "react-router";
import { toast } from "sonner";
import { Button } from "@/components/ui/button";
import { Card, CardBody, CardHeader } from "@/components/ui/card";
import { Badge } from "@/components/ui/feedback";
import { Field, Select } from "@/components/ui/form-controls";
import { JalaliDateInput } from "@/features/accounting/inputs";
import { ApiError, newIdempotencyKey, upload } from "@/lib/api";
import { toFaDigits } from "@/lib/format";
import { todayIso } from "@/lib/jalali";
import { useWarehouses } from "./api";

type Preview = {
  total_rows: number;
  valid_rows: number;
  to_create: number;
  to_update: number;
  errors: { row: number; column: string; message: string }[];
};
type Result = { created: number; updated: number; document_id: string | null };

function Importer({
  kind,
  title,
  description,
  extra,
  ready = true,
  formData,
  onDone,
}: {
  kind: "items" | "opening";
  title: string;
  description: string;
  extra?: React.ReactNode;
  ready?: boolean;
  onDone: (r: Result) => React.ReactNode;
  formData?: Record<string, string>;
}) {
  const qc = useQueryClient();
  const [file, setFile] = React.useState<File | null>(null);
  const [preview, setPreview] = React.useState<Preview | null>(null);
  const [result, setResult] = React.useState<Result | null>(null);
  const keyRef = React.useRef(newIdempotencyKey());
  const inputRef = React.useRef<HTMLInputElement>(null);

  const check = useMutation({
    mutationFn: (f: File) => upload<Preview>(`/inventory/import/${kind}/preview`, f),
    onSuccess: setPreview,
    onError: (e) => toast.error(e instanceof ApiError ? e.message : "خطا"),
  });
  const commit = useMutation({
    mutationFn: () => upload<Result>(`/inventory/import/${kind}/commit`, file as File, formData ?? {}, keyRef.current),
    onSuccess: (r) => {
      setResult(r);
      keyRef.current = newIdempotencyKey();
      qc.invalidateQueries({ queryKey: ["inventory"] });
      toast.success("ورود اطلاعات انجام شد");
    },
    onError: (e) => toast.error(e instanceof ApiError ? e.message : "خطا"),
  });

  return (
    <Card>
      <CardHeader
        icon={<FileSpreadsheet className="size-5" />}
        title={title}
        description={description}
        actions={
          <Button variant="outline" size="sm" asChild>
            <a href={`/api/v1/inventory/import/${kind}/template`}>
              <Download /> دانلود قالب
            </a>
          </Button>
        }
      />
      <CardBody className="flex flex-col gap-4">
        {extra}
        <div className="flex flex-wrap items-center gap-3">
          <input
            ref={inputRef}
            type="file"
            accept=".xlsx,application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
            className="hidden"
            onChange={(e) => {
              const f = e.target.files?.[0] ?? null;
              setFile(f);
              setPreview(null);
              setResult(null);
              keyRef.current = newIdempotencyKey();
              if (f) check.mutate(f);
              e.target.value = "";
            }}
          />
          <Button variant="secondary" onClick={() => inputRef.current?.click()} loading={check.isPending}>
            <Upload /> انتخاب فایل Excel
          </Button>
          {file ? <span className="text-sm text-ink-soft">{file.name}</span> : null}
        </div>

        {preview ? (
          <div className="flex flex-col gap-3">
            <div className="flex flex-wrap gap-2">
              <Badge tone="info" icon={false}>{toFaDigits(preview.total_rows)} ردیف</Badge>
              <Badge tone="success">{toFaDigits(preview.valid_rows)} ردیف معتبر</Badge>
              {kind === "items" ? (
                <>
                  <Badge tone="brand" icon={false}>{toFaDigits(preview.to_create)} کالای جدید</Badge>
                  <Badge tone="brand" icon={false}>{toFaDigits(preview.to_update)} به‌روزرسانی</Badge>
                </>
              ) : null}
              {preview.errors.length ? <Badge tone="danger">{toFaDigits(preview.errors.length)} خطا</Badge> : null}
            </div>
            {preview.errors.length ? (
              <div className="surface max-h-72 overflow-y-auto rounded-2xl">
                <table className="w-full text-sm">
                  <thead>
                    <tr className="text-xs text-ink-faint">
                      <th className="w-20 px-3 py-2 text-start">ردیف</th>
                      <th className="w-40 px-3 py-2 text-start">ستون</th>
                      <th className="px-3 py-2 text-start">خطا</th>
                    </tr>
                  </thead>
                  <tbody>
                    {preview.errors.map((e, i) => (
                      <tr key={i} className="border-t border-[var(--line)]">
                        <td className="tabular px-3 py-1.5">{toFaDigits(e.row)}</td>
                        <td className="px-3 py-1.5">{e.column}</td>
                        <td className="px-3 py-1.5 text-danger">{e.message}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            ) : null}
            <p className="text-sm text-ink-soft">
              {preview.errors.length
                ? "ورود فقط وقتی انجام می‌شود که هیچ ردیفی خطا نداشته باشد. فایل را اصلاح و دوباره انتخاب کنید."
                : "همه ردیف‌ها معتبرند. با تأیید، همه با هم ثبت می‌شوند (همه یا هیچ)."}
            </p>
            <Button className="self-start" disabled={!!preview.errors.length || !preview.valid_rows || !ready} loading={commit.isPending} onClick={() => commit.mutate()}>
              <CheckCircle2 /> تأیید و ثبت
            </Button>
          </div>
        ) : null}
        {result ? <div className="rounded-xl bg-success/10 p-3 text-sm text-success">{onDone(result)}</div> : null}
      </CardBody>
    </Card>
  );
}

export function ImportPage() {
  const warehouses = useWarehouses();
  const [wh, setWh] = React.useState("");
  const [date, setDate] = React.useState<string | null>(todayIso());
  React.useEffect(() => {
    if (!wh && warehouses.data?.length) setWh(warehouses.data[0].id);
  }, [warehouses.data, wh]);

  return (
    <div className="grid gap-4 xl:grid-cols-2">
      <Importer
        kind="items"
        title="ورود کالاها"
        description="کد، نام، گروه، واحد، بارکدها، قیمت، وزنی، کد ترازو، مالیات و حداقل موجودی"
        onDone={(r) => `${toFaDigits(r.created)} کالای جدید ثبت و ${toFaDigits(r.updated)} کالا به‌روز شد.`}
      />
      <Importer
        kind="opening"
        title="ورود موجودی اول دوره"
        description="کد یا بارکد کالا، مقدار و بهای تمام‌شده واحد. نتیجه یک سند پیش‌نویس است."
        ready={!!wh && !!date}
        formData={{ warehouse_id: wh, document_date: date ?? "" }}
        extra={
          <div className="grid grid-cols-2 gap-3">
            <Field label="انبار">
              <Select value={wh} onChange={(e) => setWh(e.target.value)}>
                {warehouses.data?.map((w) => (
                  <option key={w.id} value={w.id}>{w.name}</option>
                ))}
              </Select>
            </Field>
            <Field label="تاریخ سند">
              <JalaliDateInput value={date} onChange={setDate} />
            </Field>
          </div>
        }
        onDone={(r) => (
          <>
            سند پیش‌نویس با {toFaDigits(r.created)} ردیف ساخته شد.{" "}
            <Link className="underline" to={`/inventory/documents/${r.document_id}`}>
              بررسی و قطعی کردن
            </Link>
          </>
        )}
      />
    </div>
  );
}
