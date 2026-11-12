import { zodResolver } from "@hookform/resolvers/zod";
import { useQueryClient } from "@tanstack/react-query";
import {
  ChartColumnBig,
  CloudUpload,
  Eye,
  EyeOff,
  Globe,
  Headset,
  Info,
  LockKeyhole,
  LogIn,
  ShieldCheck,
  UserRound,
  WifiOff,
} from "lucide-react";
import * as React from "react";
import { useForm } from "react-hook-form";
import { z } from "zod";
import { BrandMark, useBranding } from "@/components/layout/branding";
import { Button } from "@/components/ui/button";
import { Checkbox, Input } from "@/components/ui/form-controls";
import { ApiError, api } from "@/lib/api";
import { toEnDigits, toFaDigits } from "@/lib/format";
import { isoToJalaliFa, todayIso } from "@/lib/jalali";
import { type Me, meKey } from "./auth";
import { LoginArt } from "./LoginArt";

const schema = z.object({
  username: z.string().trim().min(1, "نام کاربری را وارد کنید"),
  password: z.string().min(1, "رمز عبور را وارد کنید"),
});
type FormValues = z.infer<typeof schema>;

// Only the username is remembered on this device, never the password.
const REMEMBER_KEY = "nc.login.username";
function rememberedUser(): string {
  try {
    return localStorage.getItem(REMEMBER_KEY) ?? "";
  } catch {
    return "";
  }
}

const FEATURES = [
  { icon: ChartColumnBig, title: "گزارش‌های", sub: "مالی و فروش" },
  { icon: ShieldCheck, title: "امنیت", sub: "مجوز و ممیزی" },
  { icon: WifiOff, title: "فروش", sub: "بدون اینترنت" },
  { icon: CloudUpload, title: "پشتیبان", sub: "رمزنگاری‌شده" },
];

/** A field with its icon in a tinted box at the start, like the rest of the new design. */
function IconField({
  icon: Icon,
  label,
  error,
  children,
}: {
  icon: typeof UserRound;
  label: string;
  error?: string;
  children: React.ReactNode;
}) {
  return (
    <div>
      <label className="sr-only">{label}</label>
      <div
        className={
          "flex h-14 items-center overflow-hidden rounded-2xl border bg-[var(--surface)] transition focus-within:border-brand-400 focus-within:ring-4 focus-within:ring-brand-400/15 " +
          (error ? "border-danger" : "border-[var(--line)]")
        }
      >
        <span className="grid h-full w-14 shrink-0 place-items-center border-e border-[var(--line)] bg-brand-500/[0.06] text-brand-600 dark:text-brand-300">
          <Icon className="size-5" aria-hidden />
        </span>
        {children}
      </div>
      {error ? <p className="mt-1.5 text-xs text-danger">{error}</p> : null}
    </div>
  );
}

export function LoginPage() {
  const brand = useBranding();
  const qc = useQueryClient();
  const [showPassword, setShowPassword] = React.useState(false);
  const [serverError, setServerError] = React.useState<string | null>(null);
  const [forgot, setForgot] = React.useState(false);
  const [remember, setRemember] = React.useState(() => rememberedUser() !== "");
  const form = useForm<FormValues>({
    resolver: zodResolver(schema),
    defaultValues: { username: rememberedUser(), password: "" },
  });

  const onSubmit = form.handleSubmit(async (values) => {
    setServerError(null);
    const username = toEnDigits(values.username);
    try {
      const me = await api.post<Me>("/auth/login", { username, password: values.password });
      try {
        if (remember) localStorage.setItem(REMEMBER_KEY, username);
        else localStorage.removeItem(REMEMBER_KEY);
      } catch {
        /* storage unavailable: nothing to remember */
      }
      qc.setQueryData(meKey, me);
    } catch (e) {
      setServerError(e instanceof ApiError ? e.message : "خطای ناشناخته");
    }
  });

  const name = brand.data?.organization_name || "NEXTCAM ERP";
  const phone = brand.data?.support_phone;
  const website = brand.data?.support_website;
  const year = isoToJalaliFa(todayIso()).slice(0, 4);

  return (
    <div className="relative flex min-h-full flex-col overflow-hidden">
      {/* soft shapes behind everything */}
      <div className="pointer-events-none fixed inset-0" aria-hidden>
        <div className="absolute -top-40 -left-40 size-[36rem] rounded-full bg-brand-300/25 blur-3xl" />
        <div className="absolute -right-32 -bottom-48 size-[34rem] rounded-full bg-accent-300/30 blur-3xl" />
        <div className="absolute top-1/4 left-1/3 size-80 rounded-full bg-white/50 blur-3xl dark:bg-brand-500/10" />
      </div>

      <main className="relative mx-auto grid w-full max-w-7xl flex-1 items-center gap-10 px-4 py-8 sm:px-8 lg:grid-cols-[minmax(0,26rem)_1fr] lg:gap-16 xl:grid-cols-[minmax(0,28rem)_1fr]">
        {/* sign-in card (first in RTL: on the right) */}
        <section className="glass-strong w-full rounded-[2rem] p-7 sm:p-9" aria-labelledby="login-title">
          <div className="flex flex-col items-center text-center">
            <BrandMark size={brand.data?.logo_version ? 84 : 60} />
            <p className="mt-3 text-2xl font-black tracking-tight text-ink">{name}</p>
            <p className="mt-1 text-sm text-ink-soft">نرم‌افزار حسابداری و فروش فروشگاهی</p>
          </div>
          <div className="my-6 flex items-center gap-2" aria-hidden>
            <span className="h-px flex-1 bg-gradient-to-l from-transparent to-brand-300/70" />
            <span className="size-2 rounded-full bg-accent-500 ring-4 ring-accent-500/15" />
            <span className="h-px flex-1 bg-gradient-to-r from-transparent to-brand-300/70" />
          </div>
          <h1 id="login-title" className="mb-5 text-center text-xl font-black text-ink">
            ورود به سامانه
          </h1>

          <form onSubmit={onSubmit} className="flex flex-col gap-4" noValidate>
            <IconField icon={UserRound} label="نام کاربری" error={form.formState.errors.username?.message}>
              <Input
                id="username"
                autoComplete="username"
                autoFocus={!rememberedUser()}
                dir="ltr"
                placeholder="نام کاربری"
                className="h-full rounded-none border-0 bg-transparent text-end shadow-none focus:ring-0 focus-visible:outline-none"
                aria-label="نام کاربری"
                aria-invalid={!!form.formState.errors.username}
                {...form.register("username")}
              />
            </IconField>
            <IconField icon={LockKeyhole} label="رمز عبور" error={form.formState.errors.password?.message}>
              <Input
                id="password"
                type={showPassword ? "text" : "password"}
                autoComplete="current-password"
                autoFocus={!!rememberedUser()}
                dir="ltr"
                placeholder="رمز عبور"
                className="h-full rounded-none border-0 bg-transparent text-end shadow-none focus:ring-0 focus-visible:outline-none"
                aria-label="رمز عبور"
                aria-invalid={!!form.formState.errors.password}
                {...form.register("password")}
              />
              <button
                type="button"
                onClick={() => setShowPassword((v) => !v)}
                className="grid h-full w-12 shrink-0 place-items-center text-ink-faint hover:text-ink"
                aria-label={showPassword ? "پنهان کردن رمز" : "نمایش رمز"}
              >
                {showPassword ? <EyeOff className="size-5" /> : <Eye className="size-5" />}
              </button>
            </IconField>

            <div className="flex flex-wrap items-center justify-between gap-2 text-sm">
              <label className="flex cursor-pointer items-center gap-2 text-ink-soft">
                <Checkbox checked={remember} onCheckedChange={(v) => setRemember(v === true)} />
                نام کاربری را به خاطر بسپار
              </label>
              <button
                type="button"
                onClick={() => setForgot((v) => !v)}
                className="text-brand-600 hover:underline dark:text-brand-300"
                aria-expanded={forgot}
              >
                رمز عبور را فراموش کرده‌ام؟
              </button>
            </div>
            {forgot ? (
              <p className="flex items-start gap-2 rounded-xl bg-brand-500/10 px-3 py-2.5 text-sm text-ink-soft" role="note">
                <Info className="mt-0.5 size-4 shrink-0 text-brand-600 dark:text-brand-300" aria-hidden />
                رمز را مدیر سیستم از بخش «کاربران» بازنشانی می‌کند؛ پس از ورود، رمز تازه را عوض کنید.
              </p>
            ) : null}

            {serverError ? (
              <p role="alert" className="rounded-xl bg-danger/10 px-3 py-2.5 text-sm text-danger">
                {serverError}
              </p>
            ) : null}

            <Button
              type="submit"
              size="lg"
              className="mt-1 h-14 rounded-2xl bg-gradient-to-l from-accent-500 to-brand-600 text-base shadow-brand-600/50"
              loading={form.formState.isSubmitting}
            >
              <LogIn className="!size-5 rotate-180" aria-hidden /> ورود
            </Button>
          </form>
        </section>

        {/* welcome side (hidden on narrow screens) */}
        <section className="hidden flex-col items-center text-center lg:flex" aria-label="معرفی">
          <h2 className="text-4xl leading-tight font-black text-ink xl:text-5xl">مدیریت هوشمند فروشگاه شما</h2>
          <p className="mt-3 text-xl font-semibold text-ink-soft">حسابداری، فروش و انبار در یک نرم‌افزار</p>
          <ul className="mt-8 flex divide-x divide-x-reverse divide-[var(--line)]">
            {FEATURES.map((f) => (
              <li key={f.title} className="flex w-32 flex-col items-center gap-2 px-3">
                <f.icon className="size-9 text-brand-600 dark:text-brand-300" aria-hidden />
                <span className="text-sm leading-snug font-semibold text-ink">
                  {f.title}
                  <br />
                  <span className="font-normal text-ink-soft">{f.sub}</span>
                </span>
              </li>
            ))}
          </ul>
          <LoginArt className="mt-8 w-full max-w-xl" />
        </section>
      </main>

      <footer className="relative border-t border-white/40 bg-gradient-to-l from-navy-800/90 to-navy-900/90 px-4 py-3 text-xs text-white/80 sm:px-8">
        <div className="mx-auto flex max-w-7xl flex-wrap items-center justify-between gap-3">
          <span>
            © {year} {name} · NEXTCAM ERP
          </span>
          <span className="flex flex-wrap items-center gap-4">
            {website ? (
              <span className="flex items-center gap-1.5" dir="ltr">
                <Globe className="size-4" aria-hidden /> {website}
              </span>
            ) : null}
            {phone ? (
              <span className="flex items-center gap-1.5">
                <Headset className="size-4" aria-hidden /> پشتیبانی: <span dir="ltr">{toFaDigits(phone)}</span>
              </span>
            ) : null}
          </span>
        </div>
      </footer>
    </div>
  );
}
