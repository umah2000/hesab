import { useMutation } from "@tanstack/react-query";
import { ShieldCheck } from "lucide-react";
import * as React from "react";
import { Button } from "@/components/ui/button";
import { Dialog, DialogContent, DialogFooter } from "@/components/ui/dialog";
import { Field, Input } from "@/components/ui/form-controls";
import { ApiError, api } from "@/lib/api";

export type ApprovalAction = "line_delete" | "discount_over_limit" | "return";
const TITLE: Record<ApprovalAction, string> = {
  line_delete: "حذف ردیف اسکن‌شده",
  discount_over_limit: "تخفیف بالاتر از سقف صندوق‌دار",
  return: "برگشت از فروش",
};

/**
 * The supervisor types their own username and password on this register.
 * The approval is single-use, expires in minutes and is audited on the server.
 */
export function ApprovalDialog({
  registerId,
  action,
  detail,
  onApproved,
  onClose,
}: {
  registerId: string;
  action: ApprovalAction;
  detail?: string;
  onApproved: (approvalId: string, approver: string) => void;
  onClose: () => void;
}) {
  const [username, setUsername] = React.useState("");
  const [password, setPassword] = React.useState("");
  const [error, setError] = React.useState<string | null>(null);
  const grant = useMutation({
    mutationFn: () =>
      api.post<{ id: string; approved_by_name: string }>("/sales/approvals", {
        cash_register_id: registerId,
        action,
        username: username.trim(),
        password,
      }),
    onSuccess: (r) => onApproved(r.id, r.approved_by_name),
    onError: (e) => {
      setPassword("");
      setError(e instanceof ApiError ? e.message : "تأیید انجام نشد");
    },
  });
  return (
    <Dialog open onOpenChange={(o) => !o && onClose()}>
      <DialogContent title={`تأیید سرپرست: ${TITLE[action]}`} description={detail ?? "سرپرست نام کاربری و رمز خودش را وارد کند."}>
        <form
          className="flex flex-col gap-4"
          onSubmit={(e) => {
            e.preventDefault();
            setError(null);
            grant.mutate();
          }}
        >
          <Field label="نام کاربری سرپرست">
            <Input autoFocus autoComplete="off" value={username} onChange={(e) => setUsername(e.target.value)} />
          </Field>
          <Field label="رمز سرپرست" error={error ?? undefined}>
            <Input type="password" autoComplete="off" value={password} onChange={(e) => setPassword(e.target.value)} />
          </Field>
          <DialogFooter>
            <Button type="submit" loading={grant.isPending} disabled={!username.trim() || !password}>
              <ShieldCheck /> تأیید
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
