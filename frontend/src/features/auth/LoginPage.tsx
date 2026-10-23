import { zodResolver } from "@hookform/resolvers/zod";
import { useQueryClient } from "@tanstack/react-query";
import { Eye, EyeOff, LockKeyhole, UserRound } from "lucide-react";
import * as React from "react";
import { useForm } from "react-hook-form";
import { z } from "zod";
import { BrandMark, useBranding } from "@/components/layout/branding";
import { Button } from "@/components/ui/button";
import { Field, Input } from "@/components/ui/form-controls";
import { ApiError, api } from "@/lib/api";
import { toEnDigits } from "@/lib/format";
import { type Me, meKey } from "./auth";

const schema = z.object({
  username: z.string().trim().min(1, "نام کاربری را وارد کنید"),
  password: z.string().min(1, "رمز عبور را وارد کنید"),
});
type FormValues = z.infer<typeof schema>;

export function LoginPage() {
  const brand = useBranding();
  const qc = useQueryClient();
  const [showPassword, setShowPassword] = React.useState(false);
  const [serverError, setServerError] = React.useState<string | null>(null);
  const form = useForm<FormValues>({ resolver: zodResolver(schema) });

  const onSubmit = form.handleSubmit(async (values) => {
    setServerError(null);
    try {
      const me = await api.post<Me>("/auth/login", {
        username: toEnDigits(values.username),
        password: values.password,
      });
      qc.setQueryData(meKey, me);
    } catch (e) {
      setServerError(e instanceof ApiError ? e.message : "خطای ناشناخته");
    }
  });

  return (
    <main className="grid min-h-full place-items-center p-4">
      <div className="pointer-events-none fixed inset-0 overflow-hidden" aria-hidden>
        <div className="absolute -top-24 -right-24 size-[28rem] rounded-full bg-brand-400/30 blur-3xl" />
        <div className="absolute -bottom-32 -left-16 size-[30rem] rounded-full bg-[oklch(0.8_0.12_200)]/30 blur-3xl" />
        <div className="absolute top-1/3 left-1/3 size-72 rounded-full bg-[oklch(0.8_0.12_330)]/25 blur-3xl" />
      </div>

      <div className="glass-strong relative w-full max-w-md rounded-3xl p-8 sm:p-10">
        <div className="mb-8 flex flex-col items-center gap-3 text-center">
          <BrandMark size={brand.data?.logo_version ? 88 : 56} />
          <div>
            <h1 className="text-2xl font-extrabold tracking-tight text-ink">{brand.data?.organization_name || "NEXTCAM ERP"}</h1>
            <p className="mt-1 text-sm text-ink-faint">{brand.data?.organization_name ? "NEXTCAM ERP · " : ""}حسابداری، فروش و انبارداری</p>
          </div>
        </div>

        <form onSubmit={onSubmit} className="flex flex-col gap-4" noValidate>
          <Field label="نام کاربری" htmlFor="username" error={form.formState.errors.username?.message}>
            <div className="relative">
              <UserRound className="pointer-events-none absolute top-1/2 right-3 size-4 -translate-y-1/2 text-ink-faint" />
              <Input
                id="username"
                autoComplete="username"
                autoFocus
                dir="ltr"
                className="h-12 pe-3 ps-10 text-end"
                aria-invalid={!!form.formState.errors.username}
                {...form.register("username")}
              />
            </div>
          </Field>
          <Field label="رمز عبور" htmlFor="password" error={form.formState.errors.password?.message}>
            <div className="relative">
              <LockKeyhole className="pointer-events-none absolute top-1/2 right-3 size-4 -translate-y-1/2 text-ink-faint" />
              <Input
                id="password"
                type={showPassword ? "text" : "password"}
                autoComplete="current-password"
                dir="ltr"
                className="h-12 px-10 text-end"
                aria-invalid={!!form.formState.errors.password}
                {...form.register("password")}
              />
              <button
                type="button"
                onClick={() => setShowPassword((v) => !v)}
                className="absolute top-1/2 left-3 -translate-y-1/2 text-ink-faint hover:text-ink"
                aria-label={showPassword ? "پنهان کردن رمز" : "نمایش رمز"}
              >
                {showPassword ? <EyeOff className="size-4" /> : <Eye className="size-4" />}
              </button>
            </div>
          </Field>

          {serverError ? (
            <p role="alert" className="rounded-xl bg-danger/10 px-3 py-2.5 text-sm text-danger">
              {serverError}
            </p>
          ) : null}

          <Button type="submit" size="lg" className="mt-2" loading={form.formState.isSubmitting}>
            ورود به سامانه
          </Button>
        </form>
      </div>
    </main>
  );
}
