import { useMutation } from "@tanstack/react-query";
import { Search } from "lucide-react";
import * as React from "react";
import { Button } from "@/components/ui/button";
import { Dialog, DialogContent, DialogFooter } from "@/components/ui/dialog";
import { Field, Input } from "@/components/ui/form-controls";
import { ApiError, api } from "@/lib/api";
import { toEnDigits } from "@/lib/format";
import type { Invoice } from "./api";

/** Find a sale of this branch on the register by its automatic or manual number (ADR-0029). */
export function FindInvoiceDialog({ registerId, onFound, onClose }: { registerId: string; onFound: (inv: Invoice) => void; onClose: () => void }) {
  const [number, setNumber] = React.useState("");
  const [error, setError] = React.useState<string | null>(null);
  const find = useMutation({
    mutationFn: () =>
      api.get<Invoice>(`/sales/registers/${registerId}/invoices/find?number=${encodeURIComponent(toEnDigits(number.trim()))}`),
    onSuccess: onFound,
    onError: (e) => setError(e instanceof ApiError ? e.message : "فاکتور پیدا نشد"),
  });
  return (
    <Dialog open onOpenChange={(o) => !o && onClose()}>
      <DialogContent title="برگشت از فروش" description="شماره‌ی فاکتور (خودکار یا دستی) را بزنید یا بارکد فیش را اسکن کنید." className="max-w-md">
        <form
          className="flex flex-col gap-3"
          onSubmit={(e) => {
            e.preventDefault();
            setError(null);
            if (number.trim()) find.mutate();
          }}
        >
          <Field label="شماره فاکتور">
            <Input autoFocus dir="ltr" className="h-14 text-center text-2xl" value={number} onChange={(e) => setNumber(e.target.value)} aria-invalid={!!error || undefined} />
          </Field>
          {error ? (
            <p role="alert" className="text-sm text-danger">
              {error}
            </p>
          ) : null}
          <DialogFooter>
            <Button type="submit" loading={find.isPending} disabled={!number.trim()}>
              <Search /> یافتن فاکتور
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
