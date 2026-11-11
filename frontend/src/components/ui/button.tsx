import { Slot } from "@radix-ui/react-slot";
import { cva, type VariantProps } from "class-variance-authority";
import { Loader2 } from "lucide-react";
import * as React from "react";
import { cn } from "@/lib/utils";

const buttonVariants = cva(
  "inline-flex items-center justify-center gap-2 whitespace-nowrap rounded-xl text-sm font-medium transition-all disabled:pointer-events-none disabled:opacity-50 [&_svg]:size-4 [&_svg]:shrink-0 cursor-pointer select-none",
  {
    variants: {
      variant: {
        // The page's one main action (save, finalize, pay): teal.
        primary:
          "bg-gradient-to-l from-accent-500 to-accent-600 font-semibold text-white shadow-[0_8px_22px_-8px] shadow-accent-600/70 hover:brightness-110 active:brightness-95",
        // A second strong action beside it (add, new): blue.
        blue: "bg-gradient-to-l from-brand-500 to-brand-600 font-semibold text-white shadow-[0_8px_22px_-8px] shadow-brand-600/70 hover:brightness-110 active:brightness-95",
        secondary:
          "border border-[var(--line)] bg-[var(--surface)] text-ink shadow-[0_4px_14px_-8px] shadow-navy-900/25 hover:border-brand-300 hover:text-brand-700 dark:hover:text-brand-200 [&_svg]:text-brand-600 dark:[&_svg]:text-brand-300",
        ghost: "text-ink-soft hover:bg-brand-500/10 hover:text-ink",
        danger: "bg-danger text-white hover:brightness-110",
        outline: "border border-[var(--line)] bg-[var(--surface)] text-ink hover:bg-[var(--surface-muted)]",
      },
      size: {
        sm: "h-8 px-3 text-xs",
        md: "h-10 px-4",
        lg: "h-12 rounded-2xl px-6 text-base",
        icon: "size-10",
      },
    },
    defaultVariants: { variant: "primary", size: "md" },
  },
);

export interface ButtonProps
  extends React.ButtonHTMLAttributes<HTMLButtonElement>,
    VariantProps<typeof buttonVariants> {
  asChild?: boolean;
  loading?: boolean;
}

export const Button = React.forwardRef<HTMLButtonElement, ButtonProps>(
  ({ className, variant, size, asChild, loading, disabled, children, ...props }, ref) => {
    if (asChild) {
      // Slot needs exactly one child, so no spinner here.
      return <Slot ref={ref} className={cn(buttonVariants({ variant, size }), className)} {...props}>{children}</Slot>;
    }
    const Comp = "button";
    return (
      <Comp
        ref={ref}
        className={cn(buttonVariants({ variant, size }), className)}
        disabled={disabled || loading}
        aria-busy={loading || undefined}
        {...props}
      >
        {loading ? <Loader2 className="animate-spin" aria-hidden /> : null}
        {children}
      </Comp>
    );
  },
);
Button.displayName = "Button";
