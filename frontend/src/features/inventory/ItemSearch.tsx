import { useQueryClient } from "@tanstack/react-query";
import { Loader2, ScanBarcode } from "lucide-react";
import * as React from "react";
import { toast } from "sonner";
import { Input } from "@/components/ui/form-controls";
import { ApiError, api, type Page } from "@/lib/api";
import { toFaDigits } from "@/lib/format";
import { fromPersianLayout } from "@/lib/keyboard";
import { cn } from "@/lib/utils";
import type { ItemSummary, Lookup } from "./api";
import { trimQty } from "./api";

export type Picked = {
  item_id: string;
  code: string;
  name: string;
  unit_id?: string;
  qty?: string;
  /** The scanned code, when resolved by lookup (scale labels are re-read by the server). */
  barcode?: string;
  source?: Lookup["source"];
};

/**
 * Scan or type. Enter with a barcode/code resolves it exactly (incl. scale labels);
 * typing a name shows suggestions. The field stays focused for consecutive scans.
 */
export const ItemSearch = React.forwardRef<
  HTMLInputElement,
  { onPick: (p: Picked) => void; placeholder?: string; autoFocus?: boolean; className?: string; inputClassName?: string }
>(({ onPick, placeholder = "اسکن بارکد یا جست‌وجوی نام/کد کالا", autoFocus, className, inputClassName }, ref) => {
  const qc = useQueryClient();
  const [text, setText] = React.useState("");
  const [results, setResults] = React.useState<ItemSummary[]>([]);
  const [open, setOpen] = React.useState(false);
  const [active, setActive] = React.useState(0);
  const [busy, setBusy] = React.useState(false);
  const [error, setError] = React.useState<string | null>(null);

  React.useEffect(() => {
    const q = text.trim();
    if (q.length < 2 || /^[\d۰-۹]{6,}$/.test(q)) {
      setResults([]);
      return;
    }
    const t = setTimeout(async () => {
      try {
        const page = await qc.fetchQuery({
          queryKey: ["inventory", "item-search", q],
          queryFn: () => api.get<Page<ItemSummary>>(`/inventory/items?q=${encodeURIComponent(q)}&page_size=12&active=true`),
          staleTime: 30_000,
        });
        setResults(page.items);
        setActive(0);
        setOpen(true);
      } catch {
        /* suggestions are best-effort */
      }
    }, 250);
    return () => clearTimeout(t);
  }, [text, qc]);

  const pick = (p: Picked) => {
    onPick(p);
    setText("");
    setResults([]);
    setOpen(false);
    setError(null);
  };

  const resolve = async () => {
    const q = text.trim();
    if (!q) return;
    if (open && results[active]) {
      const r = results[active];
      pick({ item_id: r.id, code: r.code, name: r.name });
      return;
    }
    setBusy(true);
    const lookup = (code: string) => api.get<Lookup>(`/inventory/items/lookup?barcode=${encodeURIComponent(code)}`);
    try {
      let code = q;
      let l: Lookup;
      try {
        l = await lookup(code);
      } catch (e) {
        // A scanner typing through a Persian keyboard layout sends Persian letters.
        const latin = fromPersianLayout(q);
        if (!latin || !(e instanceof ApiError) || e.status !== 404) throw e;
        l = await lookup(latin);
        code = latin;
        toast.warning("زبان صفحه‌کلید روی فارسی است؛ برای اسکن مطمئن آن را انگلیسی کنید");
      }
      pick({ item_id: l.item_id, code: l.code, name: l.name, unit_id: l.unit_id, qty: trimQty(l.qty), barcode: code, source: l.source });
    } catch (e) {
      setError(e instanceof ApiError ? e.message : "کالا یافت نشد");
      setText("");
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className={cn("relative", className)}>
      <ScanBarcode className="pointer-events-none absolute top-1/2 right-3 size-5 -translate-y-1/2 text-brand-500" />
      <Input
        ref={ref}
        autoFocus={autoFocus}
        value={text}
        placeholder={placeholder}
        aria-label="اسکن یا جست‌وجوی کالا"
        aria-invalid={!!error || undefined}
        className={cn("h-12 ps-10 text-base", inputClassName)}
        onChange={(e) => {
          setText(e.target.value);
          setError(null);
        }}
        onBlur={() => setTimeout(() => setOpen(false), 150)}
        onKeyDown={(e) => {
          if (e.key === "Enter") {
            e.preventDefault();
            void resolve();
          } else if (e.key === "ArrowDown") {
            e.preventDefault();
            setOpen(true);
            setActive((a) => Math.min(a + 1, results.length - 1));
          } else if (e.key === "ArrowUp") {
            e.preventDefault();
            setActive((a) => Math.max(a - 1, 0));
          } else if (e.key === "Escape") {
            setOpen(false);
          }
        }}
      />
      {busy ? <Loader2 className="absolute top-1/2 left-3 size-4 -translate-y-1/2 animate-spin text-ink-faint" /> : null}
      {error ? (
        <p role="alert" className="mt-1 text-sm text-danger">
          {error}
        </p>
      ) : null}
      {open && results.length ? (
        <ul role="listbox" className="glass-strong absolute z-40 mt-1 max-h-72 w-full overflow-y-auto rounded-xl p-1">
          {results.map((r, i) => (
            <li
              key={r.id}
              role="option"
              aria-selected={i === active}
              onMouseDown={(e) => {
                e.preventDefault();
                pick({ item_id: r.id, code: r.code, name: r.name });
              }}
              onMouseEnter={() => setActive(i)}
              className={cn("flex cursor-pointer items-center gap-3 rounded-lg px-3 py-2 text-sm", i === active && "bg-brand-500/10")}
            >
              <span className="tabular w-20 shrink-0 text-ink-faint" dir="ltr">
                {r.code}
              </span>
              <span className="flex-1 text-ink">{r.name}</span>
              <span className="tabular text-xs text-ink-faint">
                موجودی {toFaDigits(trimQty(r.stock_qty))} {r.base_unit_name}
              </span>
            </li>
          ))}
        </ul>
      ) : null}
    </div>
  );
});
ItemSearch.displayName = "ItemSearch";
