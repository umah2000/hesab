import { ChevronDown } from "lucide-react";
import * as React from "react";
import { Input } from "@/components/ui/form-controls";
import { toEnDigits, toFaDigits } from "@/lib/format";
import { isoToJalali, jalaliToIso } from "@/lib/jalali";
import { groupDigits } from "@/lib/money";
import { cn } from "@/lib/utils";
import type { Account, DetailAccount } from "./api";

/** Jalali date typed as 1405/07/19; emits ISO (Gregorian) or null while invalid. */
export function JalaliDateInput({
  value,
  onChange,
  className,
  id,
  invalid,
  placeholder = "سال/ماه/روز",
}: {
  value: string | null;
  onChange: (iso: string | null) => void;
  className?: string;
  id?: string;
  invalid?: boolean;
  placeholder?: string;
}) {
  const [text, setText] = React.useState(value ? isoToJalali(value) : "");
  React.useEffect(() => {
    if (value && jalaliToIso(text) !== value) setText(isoToJalali(value));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [value]);
  const bad = invalid || (text !== "" && jalaliToIso(text) === null);
  return (
    <Input
      id={id}
      dir="ltr"
      inputMode="numeric"
      placeholder={placeholder}
      value={text}
      aria-invalid={bad || undefined}
      className={cn("tabular text-center", className)}
      onChange={(e) => {
        const t = toEnDigits(e.target.value).replace(/[^\d/-]/g, "").slice(0, 10);
        setText(t);
        onChange(jalaliToIso(t));
      }}
    />
  );
}

/** Amount in display currency, grouped while typing, Latin digits for speed. */
export const MoneyInput = React.forwardRef<
  HTMLInputElement,
  { value: string; onChange: (v: string) => void } & Omit<React.InputHTMLAttributes<HTMLInputElement>, "value" | "onChange">
>(({ value, onChange, className, ...props }, ref) => (
  <Input
    ref={ref}
    dir="ltr"
    inputMode="decimal"
    value={groupDigits(value)}
    onChange={(e) => onChange(toEnDigits(e.target.value).replace(/[^\d.]/g, ""))}
    className={cn("tabular text-end", className)}
    {...props}
  />
));
MoneyInput.displayName = "MoneyInput";

type Option = { id: string; code: string; name: string; hint?: string };

/**
 * Keyboard-first picker: type a code or part of a name, arrows to move, Enter to pick.
 * An exact code match is picked on Enter even if not highlighted.
 */
export const Picker = React.forwardRef<
  HTMLInputElement,
  {
    options: Option[];
    value: string | null;
    onChange: (id: string | null) => void;
    placeholder?: string;
    invalid?: boolean;
    onPicked?: () => void;
    className?: string;
    ariaLabel?: string;
  }
>(({ options, value, onChange, placeholder, invalid, onPicked, className, ariaLabel }, ref) => {
  const selected = options.find((o) => o.id === value) ?? null;
  const [query, setQuery] = React.useState("");
  const [open, setOpen] = React.useState(false);
  const [active, setActive] = React.useState(0);
  const listId = React.useId();

  const filtered = React.useMemo(() => {
    const q = toEnDigits(query.trim()).toLowerCase();
    if (!q) return options.slice(0, 50);
    return options
      .filter((o) => o.code.toLowerCase().startsWith(q) || o.name.toLowerCase().includes(q))
      .sort((a, b) => Number(b.code.toLowerCase() === q) - Number(a.code.toLowerCase() === q) || a.code.localeCompare(b.code))
      .slice(0, 50);
  }, [options, query]);

  const pick = (o: Option | undefined) => {
    if (!o) return;
    onChange(o.id);
    setQuery("");
    setOpen(false);
    onPicked?.();
  };

  return (
    <div className={cn("relative", className)}>
      <Input
        ref={ref}
        role="combobox"
        aria-expanded={open}
        aria-controls={listId}
        aria-label={ariaLabel}
        aria-invalid={invalid || undefined}
        placeholder={placeholder}
        value={open ? query : selected ? `${toFaDigits(selected.code)} — ${selected.name}` : ""}
        onFocus={() => {
          setOpen(true);
          setQuery("");
          setActive(0);
        }}
        onBlur={() => setTimeout(() => setOpen(false), 120)}
        onChange={(e) => {
          setQuery(e.target.value);
          setActive(0);
          setOpen(true);
        }}
        onKeyDown={(e) => {
          if (e.key === "ArrowDown") {
            e.preventDefault();
            setActive((a) => Math.min(a + 1, filtered.length - 1));
          } else if (e.key === "ArrowUp") {
            e.preventDefault();
            setActive((a) => Math.max(a - 1, 0));
          } else if (e.key === "Enter" && open) {
            e.preventDefault();
            const exact = filtered.find((o) => o.code.toLowerCase() === toEnDigits(query.trim()).toLowerCase());
            pick(exact ?? filtered[active]);
          } else if (e.key === "Escape") {
            setOpen(false);
          } else if (e.key === "Delete" && !query && value) {
            onChange(null);
          }
        }}
        className="pe-8"
      />
      <ChevronDown className="pointer-events-none absolute top-1/2 left-2.5 size-4 -translate-y-1/2 text-ink-faint" />
      {open ? (
        <ul
          id={listId}
          role="listbox"
          className="glass-strong absolute z-40 mt-1 max-h-64 w-full min-w-72 overflow-y-auto rounded-xl p-1"
        >
          {filtered.length === 0 ? (
            <li className="px-3 py-2 text-sm text-ink-faint">موردی یافت نشد</li>
          ) : (
            filtered.map((o, i) => (
              <li
                key={o.id}
                role="option"
                aria-selected={i === active}
                onMouseDown={(e) => {
                  e.preventDefault();
                  pick(o);
                }}
                onMouseEnter={() => setActive(i)}
                className={cn(
                  "flex cursor-pointer items-center gap-2 rounded-lg px-3 py-1.5 text-sm",
                  i === active && "bg-brand-500/10",
                )}
              >
                <span className="tabular w-14 shrink-0 text-ink-faint">{toFaDigits(o.code)}</span>
                <span className="flex-1 text-ink">{o.name}</span>
                {o.hint ? <span className="text-[11px] text-ink-faint">{o.hint}</span> : null}
              </li>
            ))
          )}
        </ul>
      ) : null}
    </div>
  );
});
Picker.displayName = "Picker";

export function accountOptions(accounts: Account[] | undefined, opts: { postableOnly?: boolean } = {}): Option[] {
  return (accounts ?? [])
    .filter((a) => a.is_active && (!opts.postableOnly || a.level === "subsidiary"))
    .map((a) => ({ id: a.id, code: a.code, name: a.name, hint: a.requires_detail ? "نیازمند تفصیلی" : undefined }));
}

export function detailOptions(details: DetailAccount[] | undefined): Option[] {
  return (details ?? []).filter((d) => d.is_active).map((d) => ({ id: d.id, code: d.code, name: d.name }));
}
