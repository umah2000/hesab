import { zodResolver } from "@hookform/resolvers/zod";
import { useQueryClient } from "@tanstack/react-query";
import { KeyRound } from "lucide-react";
import { useForm } from "react-hook-form";
import { toast } from "sonner";
import { z } from "zod";
import { Logo } from "@/components/layout/Logo";
import { Button } from "@/components/ui/button";
import { Card, CardBody, CardHeader } from "@/components/ui/card";
import { Field, Input } from "@/components/ui/form-controls";
import { ApiError, api } from "@/lib/api";
import { meKey, useMe } from "./auth";

const schema = z
  .object({
    current_password: z.string().min(1, "رمز فعلی را وارد کنید"),
    new_password: z.string().min(8, "حداقل ۸ کاراکتر").regex(/\d/, "باید شامل عدد باشد").regex(/[^\d\s]/, "باید شامل حرف باشد"),
    confirm: z.string(),
  })
  .refine((v) => v.new_password === v.confirm, { path: ["confirm"], message: "تکرار رمز یکسان نیست" });
type Values = z.infer<typeof schema>;

export function ChangePasswordForm() {
  const qc = useQueryClient();
  const form = useForm<Values>({ resolver: zodResolver(schema) });
  const e = form.formState.errors;
  const onSubmit = form.handleSubmit(async (v) => {
    try {
      await api.post("/auth/change-password", { current_password: v.current_password, new_password: v.new_password });
      toast.success("رمز عبور تغییر کرد؛ نشست‌های دیگر شما بسته شد");
      form.reset();
      qc.invalidateQueries({ queryKey: meKey });
    } catch (err) {
      toast.error(err instanceof ApiError ? err.message : "خطا");
    }
  });
  return (
    <form onSubmit={onSubmit} className="flex flex-col gap-4" noValidate>
      <Field label="رمز فعلی" htmlFor="cp-cur" error={e.current_password?.message}>
        <Input id="cp-cur" type="password" dir="ltr" autoComplete="current-password" {...form.register("current_password")} />
      </Field>
      <Field label="رمز جدید" htmlFor="cp-new" error={e.new_password?.message} hint="حداقل ۸ کاراکتر، شامل حرف و عدد">
        <Input id="cp-new" type="password" dir="ltr" autoComplete="new-password" {...form.register("new_password")} />
      </Field>
      <Field label="تکرار رمز جدید" htmlFor="cp-conf" error={e.confirm?.message}>
        <Input id="cp-conf" type="password" dir="ltr" autoComplete="new-password" {...form.register("confirm")} />
      </Field>
      <Button type="submit" loading={form.formState.isSubmitting}>
        <KeyRound /> تغییر رمز
      </Button>
    </form>
  );
}

export function AccountPage() {
  return (
    <Card className="max-w-lg">
      <CardHeader icon={<KeyRound className="size-5" />} title="تغییر رمز عبور" />
      <CardBody>
        <ChangePasswordForm />
      </CardBody>
    </Card>
  );
}

/** Shown instead of the app until a user with a temporary password sets their own. */
export function ForcePasswordChange() {
  const { data: me } = useMe();
  return (
    <main className="grid min-h-full place-items-center p-4">
      <div className="glass-strong w-full max-w-md rounded-3xl p-8">
        <div className="mb-6 flex items-center gap-3">
          <Logo size={44} />
          <div>
            <h1 className="text-lg font-bold text-ink">{me?.full_name}، رمز خود را تعیین کنید</h1>
            <p className="text-sm text-ink-faint">رمز فعلی موقت است و باید تغییر کند.</p>
          </div>
        </div>
        <ChangePasswordForm />
      </div>
    </main>
  );
}
