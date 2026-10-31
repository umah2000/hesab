import { CalendarDays, ChevronDown } from "lucide-react";
import * as React from "react";
import { Input } from "@/components/ui/form-controls";
import { JalaliCalendar, Popover } from "@/components/ui/jalali-calendar";
import { toEnDigits, toFaDigits } from "@/lib/format";
import { isoToJalali, jalaliToIso } from "@/lib/jalali";
import { groupDigits } from "@/lib/money";
import { amountHint } from "@/lib/words";
import { cn } from "@/lib/utils";
import { type Account, type DetailAccount, useCurrency } from "./api";

/** Jalali date typed as 1405/07/19 or picked from the calendar that opens under the field;
 * emits ISO (Gregorian) or null while invalid. */
export function JalaliDateInput({
  value,
  onChange,
  className,
  id,
  invalid,
  placeholder = "سال/ماه/روز",
  disabled,
  "aria-label": ariaLabel,
}: {
  value: string | null;
  onChange: (iso: string | null) => void;
  className?: string;
  id?: string;
  invalid?: boolean;
  placeholder?: string;
  disabled?: boolean;
  "aria-label"?: string;
}) {
  const [text, setText] = React.useState(value ? isoToJalali(value) : "");
  const [open, setOpen] = React.useState(false);
  const wrap = React.useRef<HTMLDivElement>(null);
  React.useEffect(() => {
    if (value && jalaliToIso(text) !== value) setText(isoToJalali(value));
    if (!value && jalaliToIso(text) !== null) setText("");
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [value]);
  const bad = invalid || (text !== "" && jalaliToIso(text) === null);
  const close = React.useCallback(() => setOpen(false), []);
  return (
    <div ref={wrap} className={cn("relative", className)}>
      <Input
        id={id}
        dir="ltr"
        inputMode="numeric"
        placeholder={placeholder}
        value={text}
        disabled={disabled}
        aria-label={ariaLabel}
        aria-invalid={bad || undefined}
        aria-haspopup="dialog"
        aria-expanded={open}
        className={cn("tabular w-full pe-9 text-center", className)}
        onFocus={() => setOpen(true)}
        onClick={() => setOpen(true)}
        onKeyDown={(e) => {
          if (e.key === "Enter" || e.key === "Tab") setOpen(false);
        }}
        onChange={(e) => {
          const t = toEnDigits(e.target.value).replace(/[^\d/-]/g, "").slice(0, 10);
          setText(t);
          onChange(jalaliToIso(t));
        }}
      />
      <button
        type="button"
        tabIndex={-1}
        disabled={disabled}
        aria-label="باز کردن تقویم"
        className="absolute inset-y-0 end-0 flex w-9 items-center justify-center text-ink-faint hover:text-brand-600"
        onClick={() => setOpen((o) => !o)}
      >
        <CalendarDays className="size-4" />
      </button>
      <Popover anchor={wrap} open={open && !disabled} onClose={close}>
        <JalaliCalendar
          value={jalaliToIso(text) ?? value}
          onPick={(iso) => {
            setText(isoToJalali(iso));
            onChange(iso);
            setOpen(false);
          }}
          onClear={() => {
            setText("");
            onChange(null);
            setOpen(false);
          }}
        />
      </Popover>
    </div>
  );
}

/** Amount in display currency, grouped while typing, Latin digits for speed. Underneath,
 * the amount in words and in the other currency («یک میلیون تومان · ۱۰٬۰۰۰٬۰۰۰ ریال»);
 * ``compact`` (table rows) shows it only while the field has focus, floating over the
 * next row so the table does not move. */
export const MoneyInput = React.forwardRef<
  HTMLInputElement,
  { value: string; onChange: (v: string) => void; compact?: boolean } & Omit<
    React.InputHTMLAttributes<HTMLInputElement>,
    "value" | "onChange"
  >
>(({ value, onChange, className, compact = false, onFocus, onBlur, ...props }, ref) => {
  const currency = useCurrency();
  const [focused, setFocused] = React.useState(false);
  const hint = amountHint(value, currency);
  const show = hint && (!compact || focused);
  return (
    <div className="relative w-full">
      <Input
        ref={ref}
        dir="ltr"
        inputMode="decimal"
        value={groupDigits(value)}
        onChange={(e) => onChange(toEnDigits(e.target.value).replace(/[^\d.]/g, ""))}
        onFocus={(e) => {
          setFocused(true);
          onFocus?.(e);
        }}
        onBlur={(e) => {
          setFocused(false);
          onBlur?.(e);
        }}
        className={cn("tabular text-end", className)}
        {...props}
      />
      {show ? (
        <div
          dir="rtl"
          aria-live="polite"
          className={cn(
            "text-xs text-ink-soft",
            compact
              ? "surface absolute inset-x-0 top-full z-20 mt-1 min-w-56 rounded-lg px-2 py-1 shadow-lg"
              : "mt-1 leading-5",
          )}
        >
          {hint}
        </div>
      ) : null}
    </div>
  );
});
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
