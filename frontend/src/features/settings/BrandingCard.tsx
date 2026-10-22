import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { ImagePlus, Info, Save, Trash2 } from "lucide-react";
import * as React from "react";
import { toast } from "sonner";
import { brandingKey, logoUrl } from "@/components/layout/branding";
import { Logo } from "@/components/layout/Logo";
import { Button } from "@/components/ui/button";
import { Card, CardBody, CardHeader } from "@/components/ui/card";
import { ErrorBox, Spinner } from "@/components/ui/feedback";
import { Field, Input } from "@/components/ui/form-controls";
import { useCan } from "@/features/auth/auth";
import { ApiError, api, upload } from "@/lib/api";
import type { Organization } from "./types";

const onError = (e: unknown) => toast.error(e instanceof ApiError ? e.message : "خطا");
type AboutFields = Pick<Organization, "about" | "phone" | "address" | "website">;

/** The shop's logo (sidebar, login page, receipts) and its «درباره ما» text. */
export function BrandingCard() {
  const qc = useQueryClient();
  const can = useCan();
  const editable = can("settings.manage");
  const org = useQuery({ queryKey: ["organization"], queryFn: () => api.get<Organization>("/organization/settings") });
  const [draft, setDraft] = React.useState<Partial<AboutFields>>({});
  React.useEffect(() => setDraft({}), [org.data?.row_version]);
  const input = React.useRef<HTMLInputElement>(null);

  const done = (o: Organization, message: string) => {
    qc.setQueryData(["organization"], o);
    qc.invalidateQueries({ queryKey: brandingKey });
    qc.invalidateQueries({ queryKey: ["system", "about"] });
    toast.success(message);
  };
  const setLogo = useMutation({
    mutationFn: (f: File) => upload<Organization>("/organization/logo", f),
    onSuccess: (o) => done(o, "لوگو ذخیره شد"),
    onError,
  });
  const removeLogo = useMutation({
    mutationFn: () => api.del<Organization>("/organization/logo", ""),
    onSuccess: (o) => done(o, "لوگو حذف شد"),
    onError,
  });
  const save = useMutation({
    mutationFn: () => api.put<Organization>("/organization/settings", draft, org.data?.row_version ?? ""),
    onSuccess: (o) => done(o, "«درباره ما» ذخیره شد"),
    onError,
  });

  if (org.isLoading) return <Card><Spinner /></Card>;
  if (org.isError || !org.data) return <Card><ErrorBox error={org.error} /></Card>;
  const v = { ...org.data, ...draft };
  const set = (k: keyof AboutFields) => (e: React.ChangeEvent<HTMLInputElement | HTMLTextAreaElement>) =>
    setDraft({ ...draft, [k]: e.target.value });

  return (
    <Card>
      <CardHeader icon={<Info className="size-5" />} title="لوگو و درباره ما" description="لوگو در منو، صفحه‌ی ورود و فیش چاپی دیده می‌شود؛ «درباره ما» برای همه‌ی کاربران" />
      <CardBody className="grid gap-5 md:grid-cols-[14rem_1fr]">
        <div className="flex flex-col items-center gap-3">
          <div className="flex size-40 items-center justify-center rounded-2xl bg-[var(--surface)] p-3 ring-1 ring-[var(--line)]">
            {org.data.logo_version ? (
              <img src={logoUrl(org.data.logo_version)} alt="لوگوی سازمان" className="max-h-full max-w-full object-contain" />
            ) : (
              <Logo size={72} />
            )}
          </div>
          {editable ? (
            <div className="flex gap-2">
              <Button size="sm" variant="outline" loading={setLogo.isPending} onClick={() => input.current?.click()}>
                <ImagePlus /> {org.data.logo_version ? "تغییر لوگو" : "بارگذاری لوگو"}
              </Button>
              {org.data.logo_version ? (
                <Button
                  size="sm"
                  variant="ghost"
                  className="text-danger"
                  loading={removeLogo.isPending}
                  onClick={() => window.confirm("لوگو حذف شود؟") && removeLogo.mutate()}
                >
                  <Trash2 /> حذف
                </Button>
              ) : null}
            </div>
          ) : null}
          <p className="text-center text-xs text-ink-faint">PNG با زمینه‌ی شفاف بهترین است؛ JPEG و WebP هم پذیرفته می‌شود. حداکثر ۱۵ مگابایت.</p>
          <input
            ref={input}
            type="file"
            accept="image/png,image/jpeg,image/webp"
            hidden
            onChange={(e) => {
              const f = e.target.files?.[0];
              if (f) setLogo.mutate(f);
              e.target.value = "";
            }}
          />
        </div>
        <div className="grid gap-4 md:grid-cols-2">
          <Field htmlFor="org-about" label="درباره ما" className="md:col-span-2" hint="معرفی کوتاه فروشگاه؛ در صفحه‌ی «درباره» دیده می‌شود">
            <textarea
              id="org-about"
              rows={4}
              maxLength={2000}
              value={v.about ?? ""}
              disabled={!editable}
              onChange={set("about")}
              className="w-full rounded-xl border border-[var(--line)] bg-[var(--surface)] px-3 py-2 text-sm text-ink outline-none focus:ring-2 focus:ring-brand-400 disabled:opacity-60"
            />
          </Field>
          <Field htmlFor="org-phone" label="تلفن">
            <Input id="org-phone" dir="ltr" value={v.phone ?? ""} disabled={!editable} maxLength={40} onChange={set("phone")} />
          </Field>
          <Field htmlFor="org-website" label="وب‌سایت">
            <Input id="org-website" dir="ltr" placeholder="shop.example.ir" value={v.website ?? ""} disabled={!editable} maxLength={200} onChange={set("website")} />
          </Field>
          <Field htmlFor="org-address" label="نشانی" className="md:col-span-2">
            <Input id="org-address" value={v.address ?? ""} disabled={!editable} maxLength={300} onChange={set("address")} />
          </Field>
          {editable ? (
            <div className="md:col-span-2">
              <Button onClick={() => save.mutate()} loading={save.isPending} disabled={Object.keys(draft).length === 0}>
                <Save /> ذخیره‌ی درباره ما
              </Button>
            </div>
          ) : null}
        </div>
      </CardBody>
    </Card>
  );
}
