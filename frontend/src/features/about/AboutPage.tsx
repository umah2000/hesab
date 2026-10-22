import { useQuery } from "@tanstack/react-query";
import { Code2, Globe, Mail, MapPin, Phone, Store } from "lucide-react";
import { PageTitle } from "@/components/layout/AppShell";
import { Logo } from "@/components/layout/Logo";
import { logoUrl } from "@/components/layout/branding";
import { Card, CardBody, CardHeader } from "@/components/ui/card";
import { ErrorBox, Spinner } from "@/components/ui/feedback";
import { api } from "@/lib/api";
import { formatDate, toFaDigits } from "@/lib/format";

type About = {
  organization: {
    name: string;
    about: string | null;
    phone: string | null;
    address: string | null;
    website: string | null;
    logo_version: string | null;
  };
  app: { name: string; version: string; released: string };
  developer: Partial<Record<"name" | "role" | "phone" | "email" | "website" | "support_hours", string>>;
};

const href = (site: string) => (/^https?:\/\//.test(site) ? site : `https://${site}`);

function Line({ icon, children }: { icon: React.ReactNode; children: React.ReactNode }) {
  return (
    <p className="flex items-center gap-2 text-sm text-ink-soft">
      <span className="text-ink-faint">{icon}</span>
      {children}
    </p>
  );
}

/** «درباره»: the shop (its own text and logo), the program version and its developer. */
export function AboutPage() {
  const q = useQuery({ queryKey: ["system", "about"], queryFn: () => api.get<About>("/system/about"), staleTime: 300_000 });
  if (q.isLoading) return <Spinner />;
  if (q.isError || !q.data) return <ErrorBox error={q.error} />;
  const { organization: o, app, developer: d } = q.data;
  const hasDeveloper = Object.keys(d).length > 0;

  return (
    <div className="flex flex-col gap-4">
      <PageTitle title="درباره" subtitle="معرفی فروشگاه، نسخه‌ی برنامه و پشتیبانی" />
      <Card>
        <CardHeader icon={<Store className="size-5" />} title="درباره ما" />
        <CardBody className="flex flex-col gap-5 sm:flex-row sm:items-start">
          <div className="flex size-32 shrink-0 items-center justify-center self-center rounded-2xl bg-[var(--surface)] p-3 ring-1 ring-[var(--line)] sm:self-start">
            {o.logo_version ? <img src={logoUrl(o.logo_version)} alt="" className="max-h-full max-w-full object-contain" /> : <Logo size={64} />}
          </div>
          <div className="flex min-w-0 flex-col gap-2">
            <h2 className="text-xl font-extrabold text-ink">{o.name}</h2>
            {o.about ? (
              <p className="whitespace-pre-line text-sm leading-7 text-ink">{o.about}</p>
            ) : (
              <p className="text-sm text-ink-faint">متن «درباره ما» هنوز نوشته نشده است (تنظیمات ← لوگو و درباره ما).</p>
            )}
            {o.phone ? <Line icon={<Phone className="size-4" />}><span dir="ltr">{toFaDigits(o.phone)}</span></Line> : null}
            {o.address ? <Line icon={<MapPin className="size-4" />}>{o.address}</Line> : null}
            {o.website ? (
              <Line icon={<Globe className="size-4" />}>
                <a href={href(o.website)} target="_blank" rel="noopener noreferrer" dir="ltr" className="text-brand-600 hover:underline dark:text-brand-300">
                  {o.website}
                </a>
              </Line>
            ) : null}
          </div>
        </CardBody>
      </Card>

      <Card>
        <CardHeader icon={<Code2 className="size-5" />} title="برنامه و برنامه‌نویس" />
        <CardBody className="grid gap-4 sm:grid-cols-2">
          <div className="flex items-center gap-3">
            <Logo size={44} />
            <div>
              <p className="font-bold text-ink">{app.name}</p>
              <p className="text-sm text-ink-soft">
                نسخه‌ی <span dir="ltr" className="font-mono">{app.version}</span> · {formatDate(app.released)}
              </p>
            </div>
          </div>
          {hasDeveloper ? (
            <div className="flex flex-col gap-1.5">
              {d.name ? <p className="font-bold text-ink">{d.name}{d.role ? <span className="font-normal text-ink-soft"> · {d.role}</span> : null}</p> : null}
              {d.phone ? <Line icon={<Phone className="size-4" />}><span dir="ltr">{toFaDigits(d.phone)}</span></Line> : null}
              {d.email ? (
                <Line icon={<Mail className="size-4" />}>
                  <a href={`mailto:${d.email}`} dir="ltr" className="text-brand-600 hover:underline dark:text-brand-300">{d.email}</a>
                </Line>
              ) : null}
              {d.website ? (
                <Line icon={<Globe className="size-4" />}>
                  <a href={href(d.website)} target="_blank" rel="noopener noreferrer" dir="ltr" className="text-brand-600 hover:underline dark:text-brand-300">{d.website}</a>
                </Line>
              ) : null}
              {d.support_hours ? <p className="text-xs text-ink-faint">ساعات پشتیبانی: {d.support_hours}</p> : null}
            </div>
          ) : (
            <p className="text-sm text-ink-faint">اطلاعات تماس برنامه‌نویس در این نسخه ثبت نشده است.</p>
          )}
        </CardBody>
      </Card>
    </div>
  );
}
