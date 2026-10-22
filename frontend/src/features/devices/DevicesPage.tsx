import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Ban, Cpu, KeyRound, ListChecks, Pencil, Plus, Printer } from "lucide-react";
import * as React from "react";
import { toast } from "sonner";
import { PageTitle } from "@/components/layout/AppShell";
import { Button } from "@/components/ui/button";
import { Card, CardBody, CardHeader } from "@/components/ui/card";
import { Dialog, DialogContent, DialogFooter } from "@/components/ui/dialog";
import { Badge, EmptyState, ErrorBox, Spinner } from "@/components/ui/feedback";
import { Checkbox, Field, Input, Select } from "@/components/ui/form-controls";
import { Table, Td, Th, Tr } from "@/components/ui/table";
import type { Branch, CashRegister } from "@/features/settings/types";
import { ApiError, api, newIdempotencyKey } from "@/lib/api";
import { formatDateTime, toFaDigits } from "@/lib/format";
import { CardTerminalsCard } from "./CardTerminals";
import { type Device, type Job, JOB_LABEL, KIND_LABEL, TRANSPORT_LABEL, type Transport } from "./api";

const onError = (e: unknown) => toast.error(e instanceof ApiError ? e.message : "خطا");

type Config = {
  name: string;
  printer_transport: Transport;
  printer_address: string;
  paper_width: 58 | 80;
  cut_paper: boolean;
  drawer_enabled: boolean;
  drawer_pin: 2 | 5;
};

const ADDRESS_HINT: Record<Transport, string> = {
  none: "",
  tcp: "نشانی و درگاه چاپگر شبکه، مثلاً 192.168.1.50:9100",
  windows: "نام چاپگر دقیقاً همان‌طور که در «Printers & scanners» ویندوز آمده",
  serial: "مثلاً COM3:9600",
};

function StatusBadge({ d }: { d: Device }) {
  if (d.status === "revoked") return <Badge tone="neutral">باطل‌شده</Badge>;
  if (d.status === "pending") return <Badge tone="warning">منتظر جفت‌سازی</Badge>;
  return d.online ? <Badge tone="success">متصل</Badge> : <Badge tone="danger">قطع</Badge>;
}

export function DevicesPage() {
  const list = useQuery({ queryKey: ["devices"], queryFn: () => api.get<Device[]>("/devices"), refetchInterval: 10_000 });
  const [editing, setEditing] = React.useState<Device | "new" | null>(null);
  const [code, setCode] = React.useState<Device | null>(null);
  const [jobs, setJobs] = React.useState<Device | null>(null);
  const qc = useQueryClient();
  const act = useMutation({
    mutationFn: ({ d, action }: { d: Device; action: "pairing-code" | "revoke" | "test-print" }): Promise<Device | Job> =>
      action === "test-print"
        ? api.post<Job>(`/devices/${d.id}/test-print`)
        : api.post<Device>(`/devices/${d.id}/${action}`, undefined, { version: d.row_version }),
    onSuccess: (res, { action }) => {
      qc.invalidateQueries({ queryKey: ["devices"] });
      if (action === "pairing-code") setCode(res as Device);
      else if (action === "revoke") toast.success("دستگاه باطل شد؛ توکن آن دیگر پذیرفته نمی‌شود");
      else toast.success("صفحه آزمایشی به صف چاپ رفت");
    },
    onError,
  });
  return (
    <>
      <PageTitle
        title="دستگاه‌های صندوق"
        subtitle="Device Agent هر صندوق، چاپگر فیش و کشوی پول"
        actions={
          <Button onClick={() => setEditing("new")}>
            <Plus /> دستگاه جدید
          </Button>
        }
      />
      <Card className="mb-4">
        <CardHeader icon={<Cpu className="size-5" />} title="نحوه کار" description="Device Agent روی رایانه صندوق نصب می‌شود و خودش به سرور وصل می‌شود؛ مرورگر هرگز مستقیم با دستگاه صحبت نمی‌کند." />
        <CardBody className="text-sm text-ink-soft">
          <ol className="list-decimal space-y-1 pe-5">
            <li>دستگاه را این‌جا تعریف کنید و چاپگر آن را تنظیم کنید؛ یک کد جفت‌سازی ۱۵ دقیقه‌ای نمایش داده می‌شود.</li>
            <li>روی رایانه صندوق فرمان جفت‌سازی را اجرا کنید (راهنمای نصب Device Agent).</li>
            <li>«چاپ آزمایشی» را بزنید. تا پیش از آزمون موفق روی همان چاپگر، پشتیبانی آن مدل تأییدنشده است.</li>
            <li>
              برای فروش هنگام قطع شبکه، صندوق را از نشانی <span dir="ltr" className="font-mono">http://127.0.0.1:47616/pos</span> روی همان رایانه باز کنید.
              فروش‌های آفلاین پس از وصل‌شدن ارسال می‌شوند و تعارض‌ها در «فروش ← فروش‌های آفلاین» می‌آیند.
            </li>
          </ol>
        </CardBody>
      </Card>
      <Card>
        <div className="surface m-4 overflow-hidden rounded-2xl">
          {list.isLoading ? (
            <Spinner />
          ) : list.isError ? (
            <ErrorBox error={list.error} />
          ) : !list.data?.length ? (
            <EmptyState icon={Printer} title="هنوز دستگاهی تعریف نشده" description="تا آن زمان فیش از طریق مرورگر چاپ می‌شود." />
          ) : (
            <Table>
              <thead>
                <tr>
                  <Th>دستگاه</Th>
                  <Th>صندوق</Th>
                  <Th>وضعیت</Th>
                  <Th>چاپگر</Th>
                  <Th>کشوی پول</Th>
                  <Th>آخرین ارتباط</Th>
                  <Th className="w-80" />
                </tr>
              </thead>
              <tbody>
                {list.data.map((d) => (
                  <Tr key={d.id}>
                    <Td>
                      <div className="font-medium">{d.name}</div>
                      <div className="text-xs text-ink-faint">
                        {d.agent_version ? `نسخه ${toFaDigits(d.agent_version)}` : "—"}
                        {d.platform ? ` · ${d.platform}` : ""}
                      </div>
                    </Td>
                    <Td>{d.cash_register_name ?? "—"}</Td>
                    <Td>
                      <StatusBadge d={d} />
                    </Td>
                    <Td>
                      <div>{TRANSPORT_LABEL[d.printer_transport]}</div>
                      {d.printer_address ? <div className="text-xs text-ink-faint" dir="ltr">{d.printer_address}</div> : null}
                      {d.printer_state && d.printer_state !== "ok" ? <Badge tone="danger">{d.printer_state}</Badge> : null}
                    </Td>
                    <Td>{d.drawer_enabled ? `فعال (پایه ${toFaDigits(d.drawer_pin)})` : "—"}</Td>
                    <Td className="text-ink-soft">
                      <div>{d.last_seen_at ? formatDateTime(d.last_seen_at) : "—"}</div>
                      {d.offline_queue > 0 ? <Badge tone="warning">{toFaDigits(d.offline_queue)} فروش آفلاین ارسال‌نشده</Badge> : null}
                      {d.last_sync_at ? <div className="text-xs text-ink-faint">آخرین ارسال آفلاین: {formatDateTime(d.last_sync_at)}</div> : null}
                    </Td>
                    <Td>
                      {d.status !== "revoked" ? (
                        <div className="flex flex-wrap justify-end gap-1">
                          <Button size="sm" variant="outline" onClick={() => setEditing(d)}>
                            <Pencil /> تنظیم
                          </Button>
                          <Button size="sm" variant="outline" disabled={!d.online || d.printer_transport === "none"} onClick={() => act.mutate({ d, action: "test-print" })}>
                            <Printer /> چاپ آزمایشی
                          </Button>
                          <Button size="sm" variant="ghost" onClick={() => setJobs(d)} aria-label={`کارهای ${d.name}`}>
                            <ListChecks />
                          </Button>
                          <Button size="sm" variant="ghost" onClick={() => act.mutate({ d, action: "pairing-code" })}>
                            <KeyRound /> کد جفت‌سازی
                          </Button>
                          <Button
                            size="sm"
                            variant="ghost"
                            onClick={() => window.confirm(`«${d.name}» باطل شود؟ Agent آن دیگر کار نمی‌کند.`) && act.mutate({ d, action: "revoke" })}
                          >
                            <Ban /> ابطال
                          </Button>
                        </div>
                      ) : null}
                    </Td>
                  </Tr>
                ))}
              </tbody>
            </Table>
          )}
        </div>
      </Card>
      {editing ? (
        <DeviceDialog
          device={editing === "new" ? null : editing}
          onClose={() => setEditing(null)}
          onCreated={(d) => {
            setEditing(null);
            setCode(d);
          }}
        />
      ) : null}
      <CardTerminalsCard />
      {code?.pairing_code ? <PairingDialog device={code} onClose={() => setCode(null)} /> : null}
      {jobs ? <JobsDialog device={jobs} onClose={() => setJobs(null)} /> : null}
    </>
  );
}

function PairingDialog({ device, onClose }: { device: Device; onClose: () => void }) {
  const server = window.location.origin;
  return (
    <Dialog open onOpenChange={(o) => !o && onClose()}>
      <DialogContent title={`جفت‌سازی «${device.name}»`} description="این کد فقط همین یک بار نمایش داده می‌شود و ۱۵ دقیقه اعتبار دارد.">
        <div className="surface rounded-2xl p-4 text-center">
          <div className="text-xs text-ink-faint">کد جفت‌سازی</div>
          <div className="tabular my-2 text-4xl font-black tracking-widest" dir="ltr" data-testid="pairing-code">
            {device.pairing_code}
          </div>
        </div>
        <p className="mt-4 text-sm text-ink-soft">روی رایانه همین صندوق، در خط فرمان مدیر (Administrator):</p>
        <pre className="surface mt-2 overflow-x-auto rounded-xl p-3 text-xs" dir="ltr">
          {`nextcam-agent pair --server ${server} --code ${device.pairing_code}\nnextcam-agent run`}
        </pre>
        <p className="mt-2 text-xs text-ink-faint">پس از جفت‌سازی، وضعیت دستگاه در این صفحه «متصل» می‌شود. اگر Agent قبلی روی صندوق کار می‌کند، با جفت شدن Agent جدید متوقف می‌شود.</p>
        <DialogFooter>
          <Button onClick={onClose}>بستم</Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}

function DeviceDialog({ device, onClose, onCreated }: { device: Device | null; onClose: () => void; onCreated: (d: Device) => void }) {
  const qc = useQueryClient();
  const branches = useQuery({ queryKey: ["branches"], queryFn: () => api.get<Branch[]>("/organization/branches") });
  const [branch, setBranch] = React.useState<string>(device?.branch_id ?? "");
  const branchId = branch || branches.data?.[0]?.id || "";
  const registers = useQuery({
    queryKey: ["branches", branchId, "registers"],
    queryFn: () => api.get<CashRegister[]>(`/organization/branches/${branchId}/cash-registers`),
    enabled: !!branchId && !device,
  });
  const [register, setRegister] = React.useState<string>("");
  const [c, setC] = React.useState<Config>({
    name: device?.name ?? "",
    printer_transport: device?.printer_transport ?? "tcp",
    printer_address: device?.printer_address ?? "",
    paper_width: device?.paper_width ?? 80,
    cut_paper: device?.cut_paper ?? true,
    drawer_enabled: device?.drawer_enabled ?? false,
    drawer_pin: device?.drawer_pin ?? 2,
  });
  const keyRef = React.useRef(newIdempotencyKey());
  const set = <K extends keyof Config>(k: K, v: Config[K]) => setC((p) => ({ ...p, [k]: v }));
  const save = useMutation({
    mutationFn: () => {
      const body = {
        ...c,
        printer_address: c.printer_transport === "none" ? null : c.printer_address.trim() || null,
        drawer_enabled: c.printer_transport === "none" ? false : c.drawer_enabled,
      };
      return device
        ? api.put<Device>(`/devices/${device.id}`, body, device.row_version)
        : api.post<Device>("/devices", { ...body, branch_id: branchId, cash_register_id: register || null }, { idempotencyKey: keyRef.current });
    },
    onSuccess: (d) => {
      qc.invalidateQueries({ queryKey: ["devices"] });
      if (device) {
        toast.success("تنظیمات ذخیره شد؛ Agent در ارتباط بعدی آن را می‌گیرد");
        onClose();
      } else onCreated(d);
    },
    onError: (e) => {
      keyRef.current = newIdempotencyKey();
      onError(e);
    },
  });
  return (
    <Dialog open onOpenChange={(o) => !o && onClose()}>
      <DialogContent title={device ? `تنظیم «${device.name}»` : "دستگاه جدید"} className="max-w-xl">
        <div className="grid gap-3 sm:grid-cols-2">
          <Field label="نام دستگاه" className="sm:col-span-2">
            <Input value={c.name} onChange={(e) => set("name", e.target.value)} placeholder="مثلاً صندوق ۱" />
          </Field>
          {!device ? (
            <>
              <Field label="شعبه">
                <Select value={branchId} onChange={(e) => { setBranch(e.target.value); setRegister(""); }}>
                  {branches.data?.map((b) => (
                    <option key={b.id} value={b.id}>{b.name}</option>
                  ))}
                </Select>
              </Field>
              <Field label="صندوق">
                <Select value={register} onChange={(e) => setRegister(e.target.value)}>
                  <option value="">— بدون صندوق —</option>
                  {registers.data?.filter((r) => r.is_active).map((r) => (
                    <option key={r.id} value={r.id}>{r.name}</option>
                  ))}
                </Select>
              </Field>
            </>
          ) : null}
          <Field label="اتصال چاپگر فیش">
            <Select value={c.printer_transport} onChange={(e) => set("printer_transport", e.target.value as Transport)}>
              {(Object.keys(TRANSPORT_LABEL) as Transport[]).map((t) => (
                <option key={t} value={t}>{TRANSPORT_LABEL[t]}</option>
              ))}
            </Select>
          </Field>
          <Field label="عرض کاغذ">
            <Select value={c.paper_width} onChange={(e) => set("paper_width", Number(e.target.value) as 58 | 80)} disabled={c.printer_transport === "none"}>
              <option value={80}>۸۰ میلی‌متر</option>
              <option value={58}>۵۸ میلی‌متر</option>
            </Select>
          </Field>
          {c.printer_transport !== "none" ? (
            <Field label="نشانی چاپگر" hint={ADDRESS_HINT[c.printer_transport]} className="sm:col-span-2">
              <Input dir="ltr" value={c.printer_address} onChange={(e) => set("printer_address", e.target.value)} />
            </Field>
          ) : null}
          <label className="flex items-center gap-2 text-sm">
            <Checkbox checked={c.cut_paper} onCheckedChange={(v) => set("cut_paper", v === true)} disabled={c.printer_transport === "none"} />
            برش کاغذ پس از چاپ
          </label>
          <label className="flex items-center gap-2 text-sm">
            <Checkbox checked={c.drawer_enabled} onCheckedChange={(v) => set("drawer_enabled", v === true)} disabled={c.printer_transport === "none"} />
            کشوی پول متصل به چاپگر
          </label>
          {c.drawer_enabled ? (
            <Field label="پایه کشو" hint="بیشتر کشوها پایه ۲ هستند؛ اگر باز نشد ۵ را امتحان کنید">
              <Select value={c.drawer_pin} onChange={(e) => set("drawer_pin", Number(e.target.value) as 2 | 5)}>
                <option value={2}>پایه ۲</option>
                <option value={5}>پایه ۵</option>
              </Select>
            </Field>
          ) : null}
        </div>
        <DialogFooter>
          <Button loading={save.isPending} disabled={c.name.trim().length < 2} onClick={() => save.mutate()}>
            {device ? "ذخیره" : "تعریف و دریافت کد جفت‌سازی"}
          </Button>
          <Button variant="ghost" onClick={onClose}>انصراف</Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}

function JobsDialog({ device, onClose }: { device: Device; onClose: () => void }) {
  const jobs = useQuery({ queryKey: ["devices", device.id, "jobs"], queryFn: () => api.get<Job[]>(`/devices/${device.id}/jobs`), refetchInterval: 3000 });
  return (
    <Dialog open onOpenChange={(o) => !o && onClose()}>
      <DialogContent title={`کارهای اخیر «${device.name}»`} className="max-w-2xl">
        {jobs.isLoading ? (
          <Spinner />
        ) : !jobs.data?.length ? (
          <EmptyState icon={ListChecks} title="کاری ثبت نشده" />
        ) : (
          <div className="surface overflow-hidden rounded-2xl">
            <Table>
              <thead>
                <tr>
                  <Th>زمان</Th>
                  <Th>نوع</Th>
                  <Th>وضعیت</Th>
                  <Th>خطا</Th>
                </tr>
              </thead>
              <tbody>
                {jobs.data.map((j) => (
                  <Tr key={j.id}>
                    <Td className="text-ink-soft">{formatDateTime(j.created_at)}</Td>
                    <Td>{KIND_LABEL[j.kind]}</Td>
                    <Td>
                      <Badge tone={j.status === "done" ? "success" : j.status === "failed" || j.status === "expired" ? "danger" : "info"}>
                        {JOB_LABEL[j.status]}
                      </Badge>
                    </Td>
                    <Td className="text-sm text-ink-soft">{j.error ?? "—"}</Td>
                  </Tr>
                ))}
              </tbody>
            </Table>
          </div>
        )}
      </DialogContent>
    </Dialog>
  );
}
